"""Backend support for the UI spec: route finder, Odyssey discussion, key settings, basis-group
builds, the slim sea-map endpoint and the Load Journey list."""
import json
import os
import stat
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from metis.api import create_app
from metis.config import Config
from metis.graph import route
from tests.conftest import complete

ROOT = Path(__file__).resolve().parents[1]


def finished_run(client, app, journey):
    g = client.get(f"/api/journeys/{journey['id']}/graph").json()
    group = next(x for x in g["groups"] if x["depth"] == 3 and x["island"] == "linear-algebra")
    paper = client.post(f"/api/journeys/{journey['id']}/papers",
                        json={"title": "Sample", "kind": "fixture", "home_group": group["id"]}).json()
    run = client.post(f"/api/journeys/{journey['id']}/runs", json={"paper_id": paper["id"]}).json()
    complete(app)
    return paper, client.get(f"/api/journeys/{journey['id']}/runs/{run['id']}").json()


def node(i, **extra):
    return {"id": i, "name": i, "statement": i, "status": "Established", **extra}


def edge(i, premises, conclusion, tier="cited", kind="implies", directed=True, **extra):
    return {"id": i, "premises": premises, "conclusion": conclusion, "type": kind, "tier": tier, "directed": directed,
            "review_status": "passed", "evidence": [{"source": "src-" + i, "location": "p.1"}], "argument": "because", **extra}


def test_proof_route_is_a_tree_through_hyperedges_and_refuses_weak_or_reversed_edges():
    nodes = {i: node(i) for i in "ABCDXY"}
    edges = [edge("e1", ["A"], "B"), edge("e2", ["B", "X"], "C", "verified"), edge("e3", ["A"], "X"),
             edge("e4", ["C"], "D", "intuitive"), edge("e5", ["C", "Y"], "D")]
    r = route(nodes, edges, "A", "C")
    assert r["found"] and r["complete"] and r["tier"] == "cited" and r["length"] == 2 and r["total_steps"] == 3
    last = r["steps"][-1]
    assert [p["from"] for p in last["premises"]] == [1, 2], "every premise of the hyperedge is reached by its own step"
    assert "complete logical argument" in r["result"] and "1. A" in r["text"]
    # Y cannot be derived from A: the route exists only with Y as an extra premise, and says so.
    r = route(nodes, edges, "A", "D")
    assert r["found"] and not r["complete"] and r["assumptions"] == [{"id": "Y", "name": "Y"}]
    assert "additional premise" in r["result"] and "[assumed]" in r["text"]
    # Direction is respected, and intuitive edges are never proof steps.
    assert not route(nodes, edges, "C", "A")["found"]
    assert not route(nodes, [edges[3]], "C", "D")["found"]
    assert "No route exists" in route(nodes, edges, "C", "A")["message"]


def test_any_route_uses_every_accepted_edge_either_way_and_is_only_a_conjecture():
    nodes = {i: node(i) for i in "ABC"}
    nodes["P"] = node("P", status="Proposed")
    edges = [edge("e1", ["A"], "B", "intuitive", "dependency"), edge("e2", ["C"], "B", "cited"),
             edge("bad", ["A"], "C", review_status="rejected"), edge("q", ["A"], "P")]
    edges[2]["review_status"] = "rejected"
    r = route(nodes, edges, "A", "C", "any")
    assert r["found"] and not r["complete"] and r["tier"] == "intuitive" and r["length"] == 2
    assert r["steps"][1]["reversed"] and "against its direction" in r["text"]
    assert "conjecture" in r["result"].lower() and "descriptive relations" in r["result"]
    assert not route(nodes, edges, "A", "P", "any")["found"], "quarantined nodes are never on a route"
    assert route(nodes, edges, "A", "A", "any")["length"] == 0
    with pytest.raises(ValueError):
        route(nodes, edges, "A", "nope")
    with pytest.raises(ValueError):
        route(nodes, edges, "A", "B", "shortest")


def test_route_endpoint_and_map_endpoint(client, app, journey):
    paper, run = finished_run(client, app, journey)
    m = client.get(f"/api/journeys/{journey['id']}/map").json()
    assert m["latest_run"] == run["id"] and m["journey"]["islands"] == journey["islands"]
    assert {"id", "name", "status", "island", "home_group", "layer", "integrated"} <= set(m["concepts"][0])
    assert "statement" not in m["concepts"][0] and "embedding" not in m["concepts"][0]
    assert "argument" not in m["edges"][0] and {"tier", "existing", "review_status", "run_id"} <= set(m["edges"][0])
    listed = next(p for p in m["papers"] if p["id"] == paper["id"])
    assert listed["concept_ids"] and "text" not in listed
    before = client.get(f"/api/journeys/{journey['id']}/map", params={"run_id": run["id"], "before": True}).json()
    assert before["before"] and len(before["concepts"]) < len(m["concepts"])
    a, b = listed["concept_ids"][:2]
    r = client.post(f"/api/journeys/{journey['id']}/route", json={"start": a, "end": b, "kind": "any"}).json()
    assert r["found"] and r["steps"][0]["tier"] == "intuitive"
    r = client.post(f"/api/journeys/{journey['id']}/route", json={"start": a, "end": b, "kind": "proof"}).json()
    assert not r["found"], "fixture associations are never proof steps"
    assert client.post(f"/api/journeys/{journey['id']}/route", json={"start": a, "end": "x"}).status_code == 400


def test_discussion_narrates_agents_folds_crew_and_links_to_trace(client, app, journey):
    _, run = finished_run(client, app, journey)
    lines = client.get(f"/api/journeys/{journey['id']}/discussion", params={"run_id": run["id"]}).json()
    trace = {t["id"]: t for t in client.get(f"/api/journeys/{journey['id']}/trace", params={"run_id": run["id"]}).json()}
    assert lines and all(d["source"] == "template" and d["fixture"] for d in lines), "fixture mode never calls a narrator"
    speakers = {d["speaker"] for d in lines}
    assert {"The decomposer", "Penelope", "Hephaestus", "Tiresias", "Odysseus"} <= speakers
    assert "system" not in {d["agent"] for d in lines}
    assert all(set(d["trace_ids"]) <= set(trace) for d in lines), "every pop-up links to its trace entries"
    assert [d["time"] for d in lines] == sorted(d["time"] for d in lines)
    crew = [d for d in lines if d["step"] == 2]
    assert crew and not any(d["summary"] == "Proposal recorded" for d in lines), "proposals are folded, never one pop-up each"
    assert all(trace[t]["summary"] == "Proposal recorded" for d in crew for t in d["trace_ids"])
    assert all("proposal(s) recorded" in d["summary"] and d["facts"]["perspective"] for d in crew)
    verdict = next(d for d in lines if d["agent"] == "Penelope" and d["target"])
    assert verdict["facts"]["tier"] in ("intuitive", "cited", "verified") and verdict["target"]["kind"] == "edge"
    assert verdict["summary"] in verdict["line"], "the template keeps the trace summary word for word"
    later = client.get(f"/api/journeys/{journey['id']}/discussion", params={"after": lines[-1]["time"]}).json()
    assert later == []
    from metis import narrator
    folded = narrator.discuss_fold(app.state.worker, run, {"crew": "Polites", "band": "far", "kind": "group", "perspective": "historical"},
                                   ["a", "b", "c"], [crew[0]["target"]["id"]], 2)
    assert folded["trace_ids"] == ["a", "b", "c"] and "2 malformed" in folded["summary"] and folded["speaker"] == "Polites"
    assert folded["facts"]["proposals"] and "→" in folded["facts"]["proposals"][0]


def test_narrator_restyles_wording_only_and_never_breaks_a_run(app, client, journey):
    from metis import narrator

    w, s = app.state.worker, app.state.store
    assert narrator.faithful("The thread holds, I say.", "Proposal passed", {"tier": "intuitive"})
    assert not narrator.faithful("It is verified!", "Proposal passed", {"tier": "intuitive"})
    assert not narrator.faithful("A novel result.", "Literature status: Not found", {})
    assert narrator.faithful("Nothing was found — not found in my searches.", "Literature status: Not found", {})
    assert not narrator.faithful("", "x", {}) and not narrator.faithful("x" * 501, "x", {})
    run = {"id": "r_live", "journey_id": journey["id"], "fixture": False}
    entry = {"id": "t1", "step": 3, "agent": "Penelope", "summary": "Proposal passed", "data": {}}
    w.providers.roles = {"narrator": {}}
    w.providers.call = Mock(return_value={"line": "I unpicked it twice; the thread holds."})
    d = narrator.discuss(w, run, entry)
    assert d["source"] == "narrator" and d["line"].startswith("I unpicked")
    w.providers.call = Mock(return_value={"line": "This is verified and novel."})
    d = narrator.discuss(w, dict(run, id="r_live2"), dict(entry, id="t2"))
    assert d["source"] == "template" and "Proposal passed" in d["line"], "an unfaithful line is replaced by the template"
    w.providers.call = Mock(side_effect=RuntimeError("budget"))
    d = narrator.discuss(w, dict(run, id="r_live3"), dict(entry, id="t3"))
    assert d["source"] == "template"
    s.patch("journeys", journey["id"], settings=dict(s.get("journeys", journey["id"])["settings"], narration=False))
    w.providers.call = Mock(return_value={"line": "unused"})
    assert narrator.discuss(w, dict(run, id="r_live4"), dict(entry, id="t4"))["source"] == "template"
    w.providers.call.assert_not_called()
    assert narrator.discuss(w, run, dict(entry, id="t5", agent="system")) is None


def test_load_journey_list_names_dates_counts_and_resume(client, app, journey):
    unnamed = client.post("/api/journeys", json={"name": "", "islands": ["linear-algebra"]})
    assert unnamed.status_code == 201 and unnamed.json()["name"] == "" and unnamed.json()["created"] > 0
    finished_run(client, app, journey)
    rows = client.get("/api/journeys").json()
    assert rows[0]["id"] == journey["id"], "sorted by last activity, newest first"
    row = rows[0]
    assert row["papers_run"] == 1 and row["review_documents"] == 1 and row["new_connections"] == 0
    assert row["active_run"] is None and row["status"] == "ready"
    g = client.get(f"/api/journeys/{unnamed.json()['id']}/graph").json()
    group = next(x for x in g["groups"] if x["depth"] == 3)
    p = client.post(f"/api/journeys/{unnamed.json()['id']}/papers", json={"title": "S", "kind": "fixture", "home_group": group["id"]}).json()
    r = client.post(f"/api/journeys/{unnamed.json()['id']}/runs", json={"paper_id": p["id"]}).json()
    client.post(f"/api/journeys/{unnamed.json()['id']}/runs/{r['id']}/pause")
    row = next(x for x in client.get("/api/journeys").json() if x["id"] == unnamed.json()["id"])
    assert row["active_run"] == {"id": r["id"], "status": "paused"}, "a paused run offers Resume"


def test_settings_roster_keys_are_stored_privately_and_never_returned(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = Config(mode="fixture", sqlite_path=str(tmp_path / "a.sqlite"), import_corpus=False,
                    provider_file=str(tmp_path / "providers.json"), keys_file=str(tmp_path / "keys.json"),
                    api_token="token")
    app = create_app(config, False)
    with TestClient(app) as client:
        auth = {"Authorization": "Bearer token"}
        s = client.get("/api/settings", headers=auth).json()
        assert s["roster"]["gods"]["default_model"] == "claude-fable-5-2" and s["roster"]["gods"]["default_verified"]
        assert s["roster"]["narrator"]["default_model"] == "claude-haiku-5-5" and s["roster"]["odysseus"]["default_model"] == "claude-opus-5-5"
        assert s["roster"]["hephaestus"]["default_model"] is None and not s["roster"]["crew2"]["default_verified"]
        assert s["roster"]["crew0"]["label"].startswith("Eurylochus") and s["roster"]["embeddings"]["key_label"] == "MongoDB Atlas"
        assert not s["keys_required"] and s["ready"], "fixture mode needs no keys"
        assert s["keys"]["ANTHROPIC_API_KEY"] == {"set": False, "source": None, "test": None, "label": "Anthropic"}
        secret = "sk-test-NEVER-RETURN-1234567890"
        r = client.put("/api/settings/keys", headers=auth, json={"ANTHROPIC_API_KEY": secret})
        assert r.status_code == 200 and r.json()["ANTHROPIC_API_KEY"]["source"] == "stored"
        assert secret not in r.text and secret not in client.get("/api/settings", headers=auth).text
        assert stat.S_IMODE(os.stat(tmp_path / "keys.json").st_mode) == 0o600
        assert app.state.worker.providers.keys.get("ANTHROPIC_API_KEY") == secret
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-environment")
        assert app.state.worker.providers.keys.get("ANTHROPIC_API_KEY") == "from-environment", "environment wins"
        assert client.get("/api/settings", headers=auth).json()["keys"]["ANTHROPIC_API_KEY"]["source"] == "environment"
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        assert client.put("/api/settings/keys", headers=auth, json={"NOT_A_KEY": "abcdefghij"}).status_code == 400
        assert client.put("/api/settings/keys", headers=auth, json={"ANTHROPIC_API_KEY": "short"}).status_code == 400
        t = client.post("/api/settings/keys/test", headers=auth, json={"role": "gods"}).json()
        assert t["ok"] is False and t["status"] == "unavailable", "fixture mode makes no provider call"
        assert client.put("/api/settings/keys", headers=auth, json={"ANTHROPIC_API_KEY": None}).json()["ANTHROPIC_API_KEY"]["set"] is False
    # Reloading reads the private file; without a token only this machine may write keys.
    open_app = create_app(Config(mode="fixture", sqlite_path=str(tmp_path / "b.sqlite"), import_corpus=False,
                                 provider_file=str(tmp_path / "providers.json"), keys_file=str(tmp_path / "keys2.json")), False)
    with TestClient(open_app) as client:
        assert client.put("/api/settings/keys", json={"ANTHROPIC_API_KEY": "abcdefghij"}).status_code == 403


def test_key_test_is_one_budgeted_call_for_exactly_that_role(app, monkeypatch):
    from metis.providers import Providers, ProviderUnavailable

    s = app.state.store
    cfg = Config(mode="live", allow_live=True, live_budget=5, provider_file="", keys_file=str(Path(app.state.store.config.sqlite_path).parent / "k.json"))
    p = Providers(s, cfg)
    spec = {"provider": "anthropic", "model": "claude-haiku-5-5", "key_env": "ANTHROPIC_API_KEY", "max_cost_usd": 0.05,
            "input_usd_per_million": 1, "output_usd_per_million": 1}
    p.roles = {"narrator": dict(spec), "gods": dict(spec)}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    op = {"id": "keytest_1", "kind": "key_test", "role": "narrator", "budget_usd": 0.05, "fixture": False}
    s.insert("operations", op)
    p._request = Mock(return_value={"ok": True})
    with pytest.raises(ProviderUnavailable):
        p.call("narrator", {"task": "t"}, op, "test")  # no key anywhere
    p.keys.set("ANTHROPIC_API_KEY", "stored-key-123456")
    op2 = dict(op, id="keytest_2"); s.insert("operations", op2)
    assert p.call("narrator", {"task": "t"}, op2, "test") == {"ok": True}
    assert p._request.call_args[0][1] == "stored-key-123456", "the stored key is used when the environment has none"
    with pytest.raises(ProviderUnavailable):
        p.call("gods", {"task": "t"}, op2, "other")
    assert p.roster()["narrator"]["ready"] and not p.roster()["decomposer"]["ready"]
    p.keys.mark("ANTHROPIC_API_KEY", False, "401")
    assert not p.roster()["narrator"]["ready"], "a failed test blocks Start until it passes"


def small_export(path):
    decls = [
        {"name": "Nat.Prime", "kind": "def", "module": "Mathlib.NumberTheory.Basic", "line": 3, "type": "ℕ → Prop",
         "docstring": "A prime natural number.", "dependencies": []},
        {"name": "Nat.exists_infinite_primes", "kind": "theorem", "module": "Mathlib.NumberTheory.PrimeCounting", "line": 9,
         "type": "∀ n, ∃ p, n ≤ p ∧ Nat.Prime p", "docstring": "Euclid's theorem.", "dependencies": ["Nat.Prime"]},
        {"name": "Unrelated.thing", "kind": "def", "module": "Mathlib.Topology.Basic", "line": 1, "type": "Type",
         "docstring": "Elsewhere.", "dependencies": []},
    ]
    path.write_text(json.dumps({"mathlib": "c44e0c8ee63ca166450922a373c7409c5d26b00b", "lean": "leanprover/lean4:v4.19.0",
                                "declarations": decls}), encoding="utf-8")


def test_missing_basis_group_is_marked_and_built_in_app(tmp_path):
    export = tmp_path / "export.json"
    small_export(export)
    config = Config(mode="fixture", sqlite_path=str(tmp_path / "a.sqlite"), import_corpus=False,
                    provider_file=str(tmp_path / "p.json"), keys_file=str(tmp_path / "k.json"),
                    mathlib_export=str(export))
    app = create_app(config, False)
    with TestClient(app) as client:
        fields = {f["id"]: f for f in client.get("/api/catalog").json()["fields"]}
        assert fields["linear-algebra"]["state"] == "ready" and fields["linear-algebra"]["recommended"] == "linear-algebra@fixture-1"
        nt = fields["number-theory"]
        assert nt["state"] == "needs_building" and nt["buildable"] and "gods will build" in nt["build_note"]
        assert client.post("/api/journeys", json={"name": "x", "islands": ["number-theory"]}).status_code == 400
        job = client.post("/api/modules/build", json={"island": "number-theory"})
        assert job.status_code == 202
        for thread in app.state.build_threads:
            thread.join(timeout=30)
        status = client.get("/api/modules/builds/" + job.json()["id"]).json()
        assert status["status"] == "ready" and status["percent"] == 100, status
        assert status["module_id"] == "number-theory-mathlib@c44e0c8e-script" and status["method"].startswith("script")
        fields = {f["id"]: f for f in client.get("/api/catalog").json()["fields"]}
        assert fields["number-theory"]["state"] == "ready" and fields["number-theory"]["recommended"] == status["module_id"]
        module = next(m for m in fields["number-theory"]["modules"] if m["id"] == status["module_id"])
        assert module["counts"] == {"concepts": 2, "edges": 1, "groups": 44} or module["counts"]["concepts"] == 2
        j = client.post("/api/journeys", json={"name": "", "islands": ["number-theory"], "modules": [status["module_id"]]})
        assert j.status_code == 201
        again = client.post("/api/modules/build", json={"island": "number-theory"})
        for thread in app.state.build_threads:
            thread.join(timeout=30)
        assert client.get("/api/modules/builds/" + again.json()["id"]).json()["status"] == "ready"
        assert client.post("/api/modules/build", json={"island": "atlantis"}).status_code == 400
    bare = create_app(Config(mode="fixture", sqlite_path=str(tmp_path / "b.sqlite"), import_corpus=False,
                             provider_file=str(tmp_path / "p.json"), keys_file=str(tmp_path / "k.json")), False)
    with TestClient(bare) as client:
        nt = next(f for f in client.get("/api/catalog").json()["fields"] if f["id"] == "number-theory")
        assert nt["state"] == "needs_building" and not nt["buildable"] and "METIS_MATHLIB_EXPORT" in nt["build_note"]
        assert client.post("/api/modules/build", json={"island": "number-theory"}).status_code == 400


def test_failed_build_leaves_catalog_unchanged(tmp_path):
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"mathlib": "c44e0c8ee63ca166450922a373c7409c5d26b00b", "declarations": []}), encoding="utf-8")
    app = create_app(Config(mode="fixture", sqlite_path=str(tmp_path / "a.sqlite"), import_corpus=False,
                            provider_file=str(tmp_path / "p.json"), keys_file=str(tmp_path / "k.json"),
                            mathlib_export=str(export)), False)
    with TestClient(app) as client:
        job = client.post("/api/modules/build", json={"island": "number-theory"}).json()
        for thread in app.state.build_threads:
            thread.join(timeout=30)
        status = client.get("/api/modules/builds/" + job["id"]).json()
        assert status["status"] == "failed" and "no declarations" in status["error"]
        nt = next(f for f in client.get("/api/catalog").json()["fields"] if f["id"] == "number-theory")
        assert nt["state"] == "needs_building"


def test_interface_structure_follows_the_ui_spec_and_keeps_the_csp(client):
    import re
    import shutil
    import struct
    import subprocess

    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    for ident in ("titleScreen", "titleCanvas", "logo", "scrollNew", "scrollLoad", "scrollFound", "setup", "setSail",
                  "transition", "flyScroll", "mapScreen", "seaCanvas", "graphCanvas", "bottle", "routePanel", "details",
                  "discussion", "portrait", "minimap", "legend", "viewToggle", "fitAll", "returnTitle", "costCounter",
                  "reportDialog", "historyDialog", "traceDialog", "logDialog", "settingsDialog", "beforeBar", "resumeBanner"):
        assert f'id="{ident}"' in html, ident
    for label in ("New Journey", "Load Journey", "Key Discoveries", "Set sail", "Message in a bottle", "Route finder",
                  "Proof route", "Any route", "Simplified view (G)", "Fit all"):
        assert label in html, label
    # The strict Content-Security-Policy allows no inline script and no inline style attribute.
    assert "style=" not in html and not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert set(re.findall(r'<script defer src="([^"]+)"', html)) == {
        "/static/vendor/cytoscape.min.js", "/static/pixel.js", "/static/title.js", "/static/seamap.js", "/static/app.js"}
    scripts = {name: (ROOT / "web" / name).read_text(encoding="utf-8") for name in ("pixel.js", "title.js", "seamap.js", "app.js")}
    assert all('style="' not in text for text in scripts.values())
    for name in list(scripts) + ["style.css", "art/metis-logo.png", "vendor/cytoscape.min.js"]:
        assert client.get("/static/" + name).status_code == 200, name
    png = (ROOT / "web/art/metis-logo.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (170, 70), "the wordmark at its true pixel grid"
    # Spec behaviours that live in the scripts.
    assert "const ZOOMS = [0.25, 0.5, 1, 2, 3, 4, 6, 8]" in scripts["seamap.js"], "zoom in whole steps"
    for hull in ("Trireme", "Merchant ship", "Raft"):
        assert hull in scripts["pixel.js"]
    assert "fresh" in scripts["pixel.js"] and "old" in scripts["pixel.js"], "sail shows new or old"
    for speaker in ("odysseus", "penelope", "hephaestus", "tiresias", "eurylochus", "elpenor", "polites", "perimedes", "gods", "decomposer"):
        assert speaker + ":" in scripts["pixel.js"], speaker
    app = scripts["app.js"]
    for needle in ('e.key === "g"', "Sail to the map", "Open review document", "skipTransition", "prefers-reduced-motion",
                   'e.key === "ArrowRight"', "navigator.clipboard.writeText", "data-test-role", "Notification"):
        assert needle in app, needle
    if shutil.which("node"):
        for name in scripts:
            assert subprocess.run(["node", "--check", str(ROOT / "web" / name)], capture_output=True).returncode == 0, name
    assert (ROOT / "docs/metis-ui-spec.txt").read_text(encoding="utf-8").startswith("Metis — UI Spec")
