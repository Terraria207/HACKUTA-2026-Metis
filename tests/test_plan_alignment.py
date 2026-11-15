"""Regression tests for the plan-alignment corrections (overview vs. implementation review)."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from metis.config import Config
from metis.graph import graph
from metis.providers import AtlasVectors, ProviderUnavailable, Providers

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "c44e0c8ee63ca166450922a373c7409c5d26b00b"


def depth3(store, journey, island="linear-algebra"):
    g = graph(store, store.get("journeys", journey["id"]))
    return next(gg for gg in g["groups"] if gg["depth"] == 3 and gg["island"] == island)


def test_events_since_is_journey_scoped_and_cursor_ordered(app):
    s = app.state.store
    for t, jid in [(4, "a"), (1, "a"), (2, "b"), (3, "a")]:
        s.put("events", {"id": f"ev{t}", "journey_id": jid, "kind": "x", "data": {}, "time": t})
    assert [e["id"] for e in s.events_since("a", 3)] == ["ev3", "ev4"]
    assert [e["id"] for e in s.events_since("b", 0)] == ["ev2"]
    assert s.events_since("a", 5) == []


def test_ranking_orders_tier_then_bridge_then_literature_then_support():
    from metis.pipeline import ranking_key

    cited_low = {"tier": "cited", "bridge_score": {"value": 0.1}, "existing": "Existing"}
    intuitive_high = {"tier": "intuitive", "bridge_score": {"value": 0.9}, "existing": "Not found"}
    assert ranking_key(cited_low, 1) > ranking_key(intuitive_high, 5)
    a = {"tier": "intuitive", "bridge_score": {"value": 0.5}, "existing": "Not found"}
    b = {"tier": "intuitive", "bridge_score": {"value": 0.5}, "existing": "Existing"}
    assert ranking_key(a, 1) > ranking_key(b, 3)
    assert ranking_key(a, 2) > ranking_key(a, 1)
    c = dict(b, existing="Unchecked")
    assert ranking_key(a, 0) > ranking_key(c, 0) > ranking_key(b, 0)
    assert ranking_key({"tier": "intuitive", "existing": "Not found"}, 9) < ranking_key(b, 0), "a missing bridge score ranks below any scored edge"


def integration_setup(app, journey):
    s = app.state.store
    j = s.get("journeys", journey["id"])
    g = graph(s, j)
    nodes = {n["id"]: n for n in g["concepts"]}
    group = depth3(s, journey)
    paper = {
        "id": "p1", "journey_id": j["id"], "text": "paper text", "home_group": group["id"],
        "msc": group["msc"], "ancestors": group["ancestors"], "concept_ids": [],
    }
    s.put("papers", paper)
    new_id = "r1:concept:a"
    s.put("concepts", {
        "id": new_id, "layer": "journey:" + j["id"], "run_id": "r1", "name": "New operator",
        "statement": "A new operator statement.", "description": "new", "kind": "theorem",
        "status": "Established", "home_group": group["id"], "ancestors": group["ancestors"],
        "island": "linear-algebra", "source": {}, "integrated": False, "fixture": False,
        "embedding": [0.1, 0.2, 0.3],
    })
    nodes[new_id] = s.get("concepts", new_id)
    run = {
        "id": "r1", "journey_id": j["id"], "paper_id": "p1", "fixture": False, "attempt": 0,
        "before": {"nodes": [n for n in nodes if n != new_id], "edges": []},
    }
    return s, j, g, nodes, group, paper, run, new_id


def evidence():
    return [{"source": "input-paper", "location": "p. 2", "excerpt": "x" * 40}]


def test_integration_loop_chains_through_integration_nodes_to_existing_graph(app, client, journey, monkeypatch):
    w = app.state.worker
    s, j, g, nodes, group, paper, run, new_id = integration_setup(app, journey)
    anchor = "linear-algebra@fixture-1:spectral"
    calls = []

    def call(role, payload, run_, key, grounded=False):
        calls.append((role, key))
        if key == "integrate:0":
            assert [c["id"] for c in payload["unconnected_concepts"]] == [new_id]
            return {
                "nodes": [{"key": "L", "name": "Standard lemma", "statement": "Standard lemma statement.",
                           "description": "lemma", "kind": "lemma", "msc": group["msc"],
                           "source": {"reference": "ref", "location": "Lemma 2", "excerpt": "..."}}],
                "edges": [
                    {"premises": ["L"], "conclusion": new_id, "type": "dependency", "directed": True,
                     "tier": "cited", "argument": "uses the lemma", "evidence": evidence()},
                    {"premises": [anchor], "conclusion": "L", "type": "dependency", "directed": True,
                     "tier": "cited", "argument": "the lemma rests on the spectral theorem", "evidence": evidence()},
                    {"premises": ["L"], "conclusion": new_id, "type": "implies", "directed": True,
                     "tier": "verified", "argument": "claims verification", "evidence": evidence()},
                ],
            }
        if key.startswith("integrate-vectors:"):
            return {"embeddings": [[0.3, 0.3, 0.3]]}
        raise AssertionError(key)

    monkeypatch.setattr(w, "call", call)
    monkeypatch.setattr(w, "near_duplicates", lambda *a, **k: [])
    created = w.integrate(run, j, g, nodes, paper, {"a": new_id})
    assert len(created) == 1
    node = s.get("concepts", created[0])
    assert node["status"] == "Established"
    assert node["source"]["kind"] == "integration" and node["source"]["level"] == 0
    assert node["source"]["reference"]["location"] == "Lemma 2"
    edges = s.all("edges", layer="journey:" + j["id"])
    assert len(edges) == 2, "a verified-tier integration claim must be rejected"
    assert all(e["provenance"]["kind"] == "integration" and e["provenance"]["level"] == 0 for e in edges)
    assert w.connected_to("journey:" + j["id"], created[0], set(run["before"]["nodes"]))
    assert [k for _, k in calls if k.startswith("integrate:")] == ["integrate:0"]
    summaries = [t["summary"] for t in s.all("trace", run_id="r1")]
    assert "Integration level completed" in summaries
    assert not any("depth limit" in x for x in summaries)


def test_integration_loop_stops_at_depth_and_flags_open_chains(app, client, journey, monkeypatch):
    w = app.state.worker
    s, j, g, nodes, group, paper, run, new_id = integration_setup(app, journey)
    s.patch("journeys", j["id"], settings=dict(j["settings"], integration_depth=2))
    j = s.get("journeys", j["id"])
    levels = []

    def call(role, payload, run_, key, grounded=False):
        if key.startswith("integrate:"):
            level = int(key.split(":")[1])
            levels.append(level)
            target = payload["unconnected_concepts"][0]["id"]
            return {
                "nodes": [{"key": "N", "name": "Lemma " + str(level), "statement": "Lemma %d statement." % level,
                           "description": "d", "kind": "lemma", "msc": group["msc"], "source": {}}],
                "edges": [{"premises": ["N"], "conclusion": target, "type": "dependency", "directed": True,
                           "tier": "intuitive", "argument": "rests on", "evidence": []}],
            }
        if key.startswith("integrate-vectors:"):
            return {"embeddings": [[0.2, 0.2, 0.2]]}
        raise AssertionError(key)

    monkeypatch.setattr(w, "call", call)
    monkeypatch.setattr(w, "near_duplicates", lambda *a, **k: [])
    created = w.integrate(run, j, g, nodes, paper, {"a": new_id})
    assert levels == [0, 1] and len(created) == 2
    summaries = [t["summary"] for t in s.all("trace", run_id="r1")]
    assert any("depth limit" in x for x in summaries)


def test_fixture_integration_loop_never_invents_links(app, client, journey):
    w = app.state.worker
    s, j, g, nodes, group, paper, run, new_id = integration_setup(app, journey)
    assert w.integrate(dict(run, fixture=True), j, g, nodes, paper, {"a": new_id}) == []
    assert not s.all("edges", layer="journey:" + j["id"])


def test_conjecture_attempt_sets_proven_only_on_machine_verification(app, client, journey, monkeypatch, tmp_path):
    from metis.concepts import attempt_accepted_conjectures, prove_conjecture

    w, s = app.state.worker, app.state.store
    j = s.get("journeys", journey["id"])
    group = depth3(s, journey)
    node = {
        "id": j["id"] + ":odysseus:c1", "layer": "journey:" + j["id"], "run_id": "r0", "name": "Conjecture",
        "statement": "Every X is Y.", "description": "conj", "kind": "conjecture", "status": "Accepted",
        "home_group": group["id"], "ancestors": group["ancestors"], "island": group["island"],
        "source": {"agent": "Odysseus"}, "integrated": False, "fixture": False,
    }
    s.put("concepts", node)
    run = {"id": "r1", "journey_id": j["id"], "fixture": False, "attempt": 0}
    assert attempt_accepted_conjectures(w, dict(run, fixture=True), 1) == []
    assert attempt_accepted_conjectures(w, run, 0) == []
    assert attempt_accepted_conjectures(w, run, 1) == [node["id"]]
    current = s.get("concepts", node["id"])
    assert current["status"] == "Accepted" and current["formal_attempt"]["status"] == "unavailable"
    w.config.lean_image = "registry/lean@sha256:" + "a" * 64
    w.config.lean_project = str(tmp_path)
    seen = []

    def call(role, payload, run_, key, grounded=False):
        seen.append(role)
        return {"statement": "True", "proof": "trivial"} if role == "hephaestus" else {"matches": True}

    monkeypatch.setattr(w, "call", call)
    monkeypatch.setattr("metis.formal.verify", lambda *a, **k: {"status": "failed", "machine_verified": False})
    attempt_accepted_conjectures(w, run, 1)
    current = s.get("concepts", node["id"])
    assert current["status"] == "Accepted" and current["formal_attempt"]["status"] == "failed"
    assert seen == ["hephaestus", "alignment"]
    assert attempt_accepted_conjectures(w, run, 1) == [], "failed attempts are not silently retried"
    s.patch("concepts", node["id"], formal_attempt=None)
    monkeypatch.setattr("metis.formal.verify", lambda *a, **k: {"status": "verified", "machine_verified": True})
    attempt_accepted_conjectures(w, dict(run, id="r2"), 1)
    assert s.get("concepts", node["id"])["status"] == "Proven"
    assert attempt_accepted_conjectures(w, dict(run, id="r3"), 1) == []
    with pytest.raises(ValueError):
        prove_conjecture(w, run, j, dict(node, kind="definition"), "k")
    assert any(t["agent"] == "Hephaestus" and "Conjecture proof attempt" in t["summary"] for t in s.all("trace"))


def test_discoveries_feed_includes_proven_and_accepted_concepts(client, app, journey):
    s = app.state.store
    group = depth3(s, journey)
    base = {
        "layer": "journey:" + journey["id"], "run_id": "r0", "description": "d", "home_group": group["id"],
        "ancestors": group["ancestors"], "island": group["island"], "source": {"agent": "Odysseus"},
        "integrated": False, "fixture": False,
    }
    s.put("concepts", dict(base, id="c-proven", name="Proven one", statement="S1", kind="conjecture", status="Proven"))
    s.put("concepts", dict(base, id="c-accepted", name="Accepted one", statement="S2", kind="conjecture", status="Accepted"))
    s.put("concepts", dict(base, id="c-proposed", name="Quarantined", statement="S3", kind="conjecture", status="Proposed"))
    feed = client.get("/api/discoveries").json()
    kinds = [d["kind"] for d in feed]
    assert kinds == ["proven concept", "accepted conjecture"]
    assert feed[0]["concept"]["id"] == "c-proven" and feed[0]["journey_name"] == journey["name"]


def declarations():
    decls = [
        {"name": "Matrix.det", "kind": "def", "module": "Mathlib.LinearAlgebra.Matrix.Determinant.Basic", "line": 5,
         "type": "Matrix n n R → R", "docstring": "The determinant of a matrix. More text.", "dependencies": []},
        {"name": "Matrix.det_mul", "kind": "theorem", "module": "Mathlib.LinearAlgebra.Matrix.Determinant.Basic",
         "line": 10, "type": "∀ (M N : Matrix n n R), (M * N).det = M.det * N.det",
         "docstring": "The determinant is multiplicative.", "dependencies": ["Matrix.det", "Matrix.mul"]},
        {"name": "Module.rank", "kind": "def", "module": "Mathlib.LinearAlgebra.Dimension.Basic", "line": 3,
         "type": "Cardinal", "docstring": "The rank of a module.", "dependencies": []},
        {"name": "Matrix.undocumented", "kind": "theorem", "module": "Mathlib.LinearAlgebra.Matrix.Trace",
         "line": 1, "type": "True", "docstring": None, "dependencies": ["Matrix.det"]},
        {"name": "Big.thm", "kind": "theorem", "module": "Mathlib.LinearAlgebra.Span", "line": 7, "type": "True",
         "docstring": "Uses many lemmas.", "dependencies": ["Dep.d%d" % i for i in range(25)]},
    ]
    decls += [
        {"name": "Dep.d%d" % i, "kind": "def", "module": "Mathlib.LinearAlgebra.Span", "line": 20 + i,
         "type": "Nat", "docstring": "Dependency %d." % i, "dependencies": []}
        for i in range(25)
    ]
    return decls


def test_script_mapping_builds_importable_mathlib_module():
    from metis.gods import build_bundle, script_mapping, select_foundational
    from scripts.prepare_module import validate

    spec = json.loads((ROOT / "deploy/msc/linear-algebra.json").read_text(encoding="utf-8"))
    selected = select_foundational(declarations(), 100, 1)
    names = {d["name"] for d in selected}
    assert "Matrix.undocumented" not in names, "undocumented with no dependents is not selected"
    assert {"Matrix.det", "Module.rank", "Big.thm", "Matrix.det_mul"} <= names
    assert selected[0]["name"] == "Matrix.det", "ranked by dependents first"
    undocumented_hub = dict(declarations()[3], name="Hub.lemma", dependencies=[])
    extra = [undocumented_hub] + [dict(d, dependencies=["Hub.lemma"]) for d in declarations()[:2]]
    assert "Hub.lemma" in {d["name"] for d in select_foundational(extra, 10, 1)}, "undocumented results others rely on are selected"
    from metis.gods import short_description
    assert short_description(undocumented_hub) == "Hub.lemma: True"
    mapping = script_mapping(selected, spec, "la-test@1")
    assert mapping["declarations"]["Matrix.det"]["home_group"] == "la-test@1:15A15"
    assert mapping["declarations"]["Module.rank"]["home_group"] == "la-test@1:15A03"
    assert mapping["declarations"]["Matrix.det"]["description"] == "The determinant of a matrix."
    bundle = build_bundle(selected, mapping, "la-test@1", "1", COMMIT, ["linear-algebra"], {"url": "x"})
    validate(bundle)
    assert all(e["type"] == "dependency" and e["tier"] == "intuitive" for e in bundle["edges"])
    big_id = "la-test@1:" + hashlib.sha256(b"Big.thm").hexdigest()[:20]
    big = next(e for e in bundle["edges"] if e["conclusion"] == big_id)
    assert len(big["premises"]) == 20 and big["evidence"][0]["truncated"] and big["evidence"][0]["dependencies_total"] == 25
    det = next(c for c in bundle["concepts"] if c["source"]["declaration"] == "Matrix.det")
    assert det["source"]["url"] == "https://github.com/leanprover-community/mathlib4/blob/" + COMMIT + "/Mathlib/LinearAlgebra/Matrix/Determinant/Basic.lean#L5"
    assert det["statement"] == "Matrix n n R → R" and det["status"] == "Established"
    groups = {g["id"]: g for g in bundle["groups"]}
    assert groups["la-test@1:15A15"]["concept_count"] == 2
    assert groups["la-test@1:15"]["depth"] == 1 and groups["la-test@1:15A"]["parent"] == "la-test@1:15"


def test_bridge_module_carries_cross_island_dependency_edges():
    from metis.gods import bridge_bundle, build_bundle, script_mapping
    from scripts.prepare_module import validate

    la_spec = json.loads((ROOT / "deploy/msc/linear-algebra.json").read_text(encoding="utf-8"))
    gt_spec = json.loads((ROOT / "deploy/msc/graph-theory.json").read_text(encoding="utf-8"))
    la = [declarations()[0]]
    gt = [{"name": "SimpleGraph.det_adj", "kind": "theorem", "module": "Mathlib.Combinatorics.SimpleGraph.AdjMatrix",
           "line": 2, "type": "True", "docstring": "Determinant of an adjacency matrix.", "dependencies": ["Matrix.det"]}]
    la_bundle = build_bundle(la, script_mapping(la, la_spec, "la@1"), "la@1", "1", COMMIT, ["linear-algebra"], {"url": "x"})
    gt_bundle = build_bundle(gt, script_mapping(gt, gt_spec, "gt@1"), "gt@1", "1", COMMIT, ["graph-theory"], {"url": "x"})
    assert not gt_bundle["edges"], "cross-module dependencies are not island-internal edges"
    bridge = bridge_bundle([la_bundle, gt_bundle], [{"declarations": la}, {"declarations": gt}], "la-gt-bridge@1", "1", COMMIT, {"url": "x"})
    assert len(bridge["edges"]) == 1 and bridge["module"]["requires"] == ["la@1", "gt@1"]
    assert bridge["edges"][0]["premises"] == [la_bundle["concepts"][0]["id"]]
    assert bridge["module"]["islands"] == ["graph-theory", "linear-algebra"]
    validate(bridge, [la_bundle, gt_bundle])


class FakeGods:
    def __init__(self):
        self.keys = []

    def call(self, role, payload, operation, key, grounded=False):
        assert role == "gods" and operation["kind"] == "module_build"
        self.keys.append(key)
        if key == "gods:groups":
            return {"descriptions": {"15A15": "Determinants, permanents and traces of matrices."}}
        if key.startswith("gods:batch"):
            return {"decisions": {
                "Matrix.det": {"foundational": True, "home_group": "15A09", "description": "The determinant.", "name": "Determinant", "duplicate_of": None},
                "Module.rank": {"foundational": False},
                "Matrix.det_mul": {"foundational": True, "duplicate_of": "Matrix.det"},
                "Big.thm": {"foundational": True, "home_group": "99Z99"},
            }}
        if key == "gods:gaps":
            return {"candidates": [{"name": "Cramer's rule", "statement": "s", "description": "d", "kind": "theorem",
                                    "home_group": "15A06", "source": {"url": "u", "location": "Thm 1"}}]}
        raise AssertionError(key)


def test_gods_curation_refines_script_mapping_and_holds_gap_fillers_for_review():
    from metis.gods import curate, select_foundational

    spec = json.loads((ROOT / "deploy/msc/linear-algebra.json").read_text(encoding="utf-8"))
    selected = select_foundational(declarations(), 100, 1)
    providers = FakeGods()
    mapping, pending = curate(providers, selected, spec, "la@1", {"id": "build_1", "kind": "module_build"}, batch=40)
    decls = mapping["declarations"]
    assert "Module.rank" not in decls and "Matrix.det_mul" not in decls
    assert decls["Matrix.det"]["home_group"] == "la@1:15A09" and decls["Matrix.det"]["placement"] == "gods"
    assert decls["Matrix.det"]["name"] == "Determinant"
    assert decls["Big.thm"]["home_group"] == "la@1:15A03" and decls["Big.thm"]["placement"] == "script", "invalid group keeps script placement"
    assert decls["Dep.d0"]["placement"] == "script", "undecided declarations keep script placement"
    assert next(g for g in mapping["groups"] if g["msc"] == "15A15")["description"].startswith("Determinants")
    assert mapping["method"].startswith("gods-curated")
    assert pending and pending[0]["reviewed"] is False
    assert providers.keys[0] == "gods:groups" and providers.keys[-1] == "gods:gaps"


def test_build_operation_is_budgeted_and_provider_admits_only_gods_or_embeddings(app, monkeypatch):
    from metis.gods import build_operation

    s = app.state.store
    cfg = Config(mode="live", allow_live=True, live_budget=10)
    with pytest.raises(ValueError):
        build_operation(s, cfg, "digest", "linear-algebra", 10)
    with pytest.raises(ValueError):
        build_operation(s, cfg, "digest", "linear-algebra", 0)
    op = build_operation(s, cfg, "digest", "linear-algebra", 2)
    assert op["kind"] == "module_build" and s.get("operations", op["id"]) == op
    p = Providers(s, cfg)
    spec = {"provider": "anthropic", "model": "test", "key_env": "TEST_KEY", "max_cost_usd": 0.2,
            "input_usd_per_million": 1, "output_usd_per_million": 1}
    p.roles = {"gods": dict(spec), "penelope": dict(spec), "embeddings": dict(spec, provider="voyage")}
    monkeypatch.setenv("TEST_KEY", "never-return-me")
    p._request = Mock(return_value={"decisions": {}})
    assert p.call("gods", {"x": 1}, op, "k1") == {"decisions": {}}
    with pytest.raises(ProviderUnavailable):
        p.call("penelope", {"x": 1}, op, "k2")
    setup = {"id": "setup_1", "kind": "module_setup", "budget_usd": 2, "fixture": False}
    s.insert("operations", setup)
    with pytest.raises(ProviderUnavailable):
        p.call("gods", {"x": 1}, setup, "k3")
    assert p._request.call_count == 1


def test_auto_embed_search_requires_atlas_and_routes_duplicate_matching(app, client, journey, monkeypatch):
    monkeypatch.delenv("METIS_ATLAS_AUTO_EMBED", raising=False)
    assert not AtlasVectors(app.state.store).auto_embed
    monkeypatch.setenv("METIS_ATLAS_AUTO_EMBED", "true")
    v = AtlasVectors(app.state.store)
    assert v.auto_embed and v.auto_model == "voyage-4"
    with pytest.raises(ProviderUnavailable):
        v.search_text("concepts", "symmetric matrix", ["module:x"])
    with pytest.raises(ProviderUnavailable):
        v.search("concepts", [0.1] * 3, ["module:x"])

    class Fake:
        auto_embed = True

        def __init__(self, store):
            self.calls = []

        def search_text(self, collection, text, layers, limit=5):
            Fake.text = text
            return [{"id": "linear-algebra@fixture-1:spectral", "score": 0.9}]

        def search(self, *a, **k):
            raise AssertionError("vector search must not be used when automated embedding is enabled")

    monkeypatch.setattr("metis.pipeline.AtlasVectors", Fake)
    w, s = app.state.worker, app.state.store
    j = s.get("journeys", journey["id"])
    nodes = {n["id"]: n for n in graph(s, j)["concepts"]}
    found = w.near_duplicates(j, nodes, "A real symmetric matrix", None)
    assert [n["id"] for n in found] == ["linear-algebra@fixture-1:spectral"] and Fake.text == "A real symmetric matrix"


def test_example_roster_covers_every_role_with_plan_provider_families():
    from metis.providers import ROLES
    from metis.api import RoleSpec

    roster = json.loads((ROOT / "deploy/providers.example.json").read_text(encoding="utf-8"))
    roles = {k: v for k, v in roster.items() if not k.startswith("_")}
    assert set(roles) == set(ROLES)
    for role, spec in roles.items():
        RoleSpec.model_validate(spec)
    assert roles["gods"]["provider"] == "anthropic" and roles["hephaestus"]["provider"] == "mistral"
    assert roles["crew2"]["provider"] == "xai" and roles["crew3"]["provider"] == "nvidia"
    assert roles["tiresias"]["provider"] == "gemini" and roles["penelope"]["provider"] == "openai"
    assert roles["embeddings"]["model"] == "voyage-4"
    index = json.loads((ROOT / "deploy/atlas-auto-embed-index.json").read_text(encoding="utf-8"))
    assert index["fields"][0] == {"type": "autoEmbed", "modality": "text", "path": "description", "model": "voyage-4"}


def test_simplified_view_ships_cytoscape_same_origin_and_status_legend():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert '/static/vendor/cytoscape.min.js' in html and 'id="graphCanvas"' in html
    assert "Proven (machine verified)" in js and "Accepted" in js
    vendored = (ROOT / "web/vendor/cytoscape.min.js").read_bytes()
    assert hashlib.sha256(vendored).hexdigest() == "71fa9ebec21a7ca2c40cff6aacc30d1f6464e363662ad4b2c197e1adc770cd94"
    assert "cytoscape({" in js and 'Proven: "#2e7d4f"' in js and "junction:" in js


def test_csp_stays_strict_apart_from_cytoscape_container_style(client):
    csp = client.get("/api/status").headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "style-src 'self' 'unsafe-hashes' 'sha256-pgvDUBa4IjFA2yuSJ2cqcyxmNYJMborsd0ORcRv9vw8='" in csp


def test_corpus_bundles_import_in_prerequisite_order_and_are_idempotent(tmp_path):
    import time
    from metis.base import import_corpus
    from metis.store import Store

    store = Store(Config(mode="fixture", sqlite_path=str(tmp_path / "corpus.sqlite")))
    start = time.time()
    imported = import_corpus(store)
    elapsed = time.time() - start
    ids = {m["id"] for m in store.all("modules") if m["status"] == "ready"}
    assert {"linear-algebra-mathlib@2026-11-15.1", "graph-theory-mathlib@2026-11-15.1",
            "probability-mathlib@2026-11-15.1", "number-theory-mathlib@2026-11-15.1"} <= ids
    assert set(imported) == ids and len(imported) == len(list((ROOT / "corpus").glob("*.json")))
    bridges = [m for m in store.all("modules") if m.get("requires")]
    assert bridges and all(set(b["requires"]) <= ids for b in bridges)
    la = store.get("modules", "linear-algebra-mathlib@2026-11-15.1")
    assert la["mathlib_version"] == COMMIT and la["source"]["selection"]["selected"] == 800
    concepts = store.all("concepts", layer="module:linear-algebra-mathlib@2026-11-15.1")
    assert len(concepts) == 800 and all(c["status"] == "Established" and c["source"]["url"].startswith("https://github.com/leanprover-community/mathlib4/blob/" + COMMIT) for c in concepts)
    edges = store.all("edges", layer="module:linear-algebra-mathlib@2026-11-15.1")
    assert edges and all(e["type"] == "dependency" and e["tier"] == "intuitive" and len(e["premises"]) <= 20 for e in edges)
    assert import_corpus(store) == [], "second startup imports nothing"
    assert elapsed < 60
