"""Basis groups come from the data: any MSC 2020 field that holds mathlib declarations can be
built and used, not a fixed list of four."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metis.api import create_app
from metis.config import Config
from metis.exportindex import (build_index, check_rules, island_entry, island_key, island_meta, load_index,
                               load_island, load_rules, place, slug, tree)

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "c44e0c8ee63ca166450922a373c7409c5d26b00b"
MSC = {
    "fields": {"05": "Combinatorics", "11": "Number theory", "15": "Linear and multilinear algebra; matrix theory",
               "28": "Measure and integration", "46": "Functional analysis", "54": "General topology",
               "91": "Game theory, economics, finance, and other social and behavioral sciences"},
    "subfields": {"05A": "Enumerative combinatorics", "05C": "Graph theory", "11A": "Elementary number theory",
                  "15A": "Basic linear algebra", "28A": "Classical measure theory", "46B": "Normed linear spaces and Banach spaces",
                  "54D": "Fairly general properties of topological spaces", "91A": "Game theory"},
    "subtopics": {"05A99": "Enumerative combinatorics", "05C50": "Graphs and linear algebra", "05C99": "Graph theory",
                  "11A41": "Primes", "15A03": "Vector spaces, linear dependence, rank", "28A12": "Contents, measures, outer measures",
                  "28A20": "Measurable and nonmeasurable functions", "46B99": "Normed linear spaces",
                  "54D10": "Lower separation axioms", "54D30": "Compactness", "91A46": "Combinatorial games"},
    "source": "test", "sha256": "0", "retrieved": "2026-11-15", "licence": "test",
}
RULES = """# test placement
Mathlib.Topology\t54D10
Mathlib.Topology.Compactness\t54D30
Mathlib.MeasureTheory\t28A12
Mathlib.Analysis\t46B99
Mathlib.Combinatorics\t05A99
Mathlib.Combinatorics.SimpleGraph\t05C50
Mathlib.NumberTheory\t11A41
Mathlib.LinearAlgebra\t15A03
Mathlib.SetTheory.Game\t91A46
Mathlib.Tactic\t-
"""


def decl(name, module, deps=(), doc="Documented.", kind="theorem"):
    return {"name": name, "kind": kind, "module": module, "line": 7, "type": "T " + name, "docstring": doc,
            "fields": [], "dependencies": list(deps)}


DECLS = [
    decl("IsCompact", "Mathlib.Topology.Compactness.Compact", kind="def"),
    decl("isCompact_univ", "Mathlib.Topology.Compactness.Compact", ["IsCompact"]),
    decl("T2Space", "Mathlib.Topology.Separation.Hausdorff", kind="class"),
    decl("Measure", "Mathlib.MeasureTheory.Measure.Basic", kind="def"),
    decl("measure_compact_lt_top", "Mathlib.MeasureTheory.Measure.Regular", ["Measure", "IsCompact"]),
    decl("Norm", "Mathlib.Analysis.Normed.Group.Basic", kind="class"),
    decl("norm_nonneg", "Mathlib.Analysis.Normed.Group.Basic", ["Norm"]),
    decl("Finset.card", "Mathlib.Combinatorics.Enumerative.Basic", kind="def"),
    decl("SimpleGraph", "Mathlib.Combinatorics.SimpleGraph.Basic", kind="structure"),
    decl("SimpleGraph.adjMatrix", "Mathlib.Combinatorics.SimpleGraph.AdjMatrix", ["SimpleGraph", "Finset.card"]),
    decl("Nat.Prime", "Mathlib.NumberTheory.Basic", kind="def"),
    decl("Module.rank", "Mathlib.LinearAlgebra.Dimension.Basic", kind="def"),
    decl("PGame", "Mathlib.SetTheory.Game.PGame", kind="inductive"),
    decl("simp_helper", "Mathlib.Tactic.Simp"),
    decl("stray", "Mathlib.Unknown.Area"),
]


@pytest.fixture
def index_dir(tmp_path):
    rules_file = tmp_path / "paths.txt"
    rules_file.write_text(RULES)
    out = tmp_path / "index"
    build_index([json.dumps(d) for d in DECLS], MSC, load_rules(rules_file), str(out), COMMIT, "leanprover/lean4:v4.19.0", "abc")
    return out


def app_for(tmp_path, index_dir, name="a"):
    return create_app(Config(mode="fixture", sqlite_path=str(tmp_path / (name + ".sqlite")), import_corpus=False,
                             provider_file=str(tmp_path / "p.json"), keys_file=str(tmp_path / "k.json"),
                             mathlib_export=str(index_dir)), False)


def build(client, app, island):
    job = client.post("/api/modules/build", json={"island": island})
    assert job.status_code == 202, job.text
    for thread in app.state.build_threads:
        thread.join(timeout=60)
    status = client.get("/api/modules/builds/" + job.json()["id"]).json()
    assert status["status"] == "ready", status
    return status["module_id"]


def test_placement_rules_longest_prefix_tooling_and_unplaced(tmp_path):
    rules_file = tmp_path / "paths.txt"
    rules_file.write_text(RULES)
    rules = load_rules(rules_file)
    assert place("Mathlib.Topology.Compactness.Compact", rules) == "54D30", "the longest prefix wins"
    assert place("Mathlib.Topology.Separation.Hausdorff", rules) == "54D10"
    assert place("Mathlib.Topology", rules) == "54D10" and place("Mathlib.TopologyX.Foo", rules) is None
    assert place("Mathlib.Tactic.Simp", rules) == "-" and place("Mathlib.Unknown.Area", rules) is None
    check_rules(rules, MSC)
    with pytest.raises(ValueError, match="99Z99"):
        check_rules(dict(rules, **{"Mathlib.Foo": "99Z99"}), MSC)
    for bad in ("Mathlib.A 54D30\n", "NotMathlib.A\t54D30\n", "Mathlib.A\t54D30\nMathlib.A\t54D10\n"):
        rules_file.write_text(bad)
        with pytest.raises(ValueError):
            load_rules(rules_file)


def test_basis_groups_are_msc_fields_with_graph_theory_kept_apart():
    assert island_key("54D30") == "54" and island_key("05C50") == "05C" and island_key("05A99") == "05"
    assert island_meta("54", MSC) == {"id": "general-topology", "name": "General topology", "msc": "54", "field": "General topology"}
    assert island_meta("15", MSC)["id"] == "linear-algebra" and island_meta("15", MSC)["name"] == "Linear algebra"
    assert island_meta("05C", MSC)["id"] == "graph-theory" and island_meta("05", MSC)["id"] == "combinatorics"
    long = island_meta("91", MSC)["id"]
    assert long == "game-theory-economics-finance-and-other-social" and len(long) <= 48, "cut at a word, not mid-word"
    assert slug("Category theory; homological algebra") == "category-theory-homological-algebra"
    graph, rest = tree("05C", MSC), tree("05", MSC)
    assert [s["msc"] for s in graph["subfields"]] == ["05C"] and [s["msc"] for s in rest["subfields"]] == ["05A"]
    assert graph["field"] == {"msc": "05", "name": "Combinatorics"}
    assert [t["msc"] for t in tree("54", MSC)["subfields"][0]["subtopics"]] == ["54D10", "54D30"], "the complete MSC subtree"


def test_index_holds_every_group_the_data_has_and_nothing_else(index_dir):
    index = load_index(str(index_dir))
    ids = [e["id"] for e in index["islands"]]
    assert ids == ["combinatorics", "graph-theory", "number-theory", "linear-algebra", "measure-and-integration",
                   "functional-analysis", "general-topology", "game-theory-economics-finance-and-other-social"]
    assert index["totals"] == {"declarations": 15, "placed": 13, "left_out_as_tooling": 1, "unplaced": 1,
                               "unplaced_by_area": {"Mathlib.Unknown": 1}}, "unplaced declarations are counted, not guessed"
    assert index["mathlib"] == COMMIT and "not gods-curated" in index["placement"]["method"]
    topology = island_entry(str(index_dir), "general-topology")
    assert topology["declarations"] == 3 and topology["populated_subtopics"] == 2 and topology["msc"] == "54"
    spec, declarations, mathlib, lean = load_island(str(index_dir), "general-topology")
    assert spec["island"] == "general-topology" and spec["field"]["msc"] == "54" and mathlib == COMMIT
    assert {d["name"]: d["msc"] for d in declarations} == {"IsCompact": "54D30", "isCompact_univ": "54D30", "T2Space": "54D10"}
    with pytest.raises(ValueError):
        load_island(str(index_dir), "atlantis")
    assert load_index("") is None and load_index(str(index_dir / "missing")) is None


def test_picker_offers_every_group_in_the_data_and_builds_any_of_them(tmp_path, index_dir):
    app = app_for(tmp_path, index_dir)
    with TestClient(app) as client:
        cat = client.get("/api/catalog").json()
        fields = {f["id"]: f for f in cat["fields"]}
        assert set(fields) == {"combinatorics", "graph-theory", "number-theory", "linear-algebra", "probability",
                               "measure-and-integration", "functional-analysis", "general-topology",
                               "game-theory-economics-finance-and-other-social"}
        assert cat["export"]["basis_groups"] == 8 and cat["export"]["declarations"] == 13
        assert [f["state"] for f in cat["fields"]][:3] == ["ready"] * 3, "saved groups are listed first"
        topology = fields["general-topology"]
        assert topology["state"] == "needs_building" and topology["buildable"] and topology["declarations"] == 3 and topology["msc"] == "54"
        assert fields["probability"]["state"] == "ready" and not fields["probability"]["buildable"], "no data for it in this export"
        assert fields["linear-algebra"]["state"] == "ready" and fields["linear-algebra"]["can_build_new"], "a saved group can be rebuilt from the export"
        module = build(client, app, "general-topology")
        assert module == "general-topology-mathlib@c44e0c8e-script"
        cat = client.get("/api/catalog").json()
        topology = next(f for f in cat["fields"] if f["id"] == "general-topology")
        assert topology["state"] == "ready" and topology["recommended"] == module and not topology["can_build_new"]
        saved = next(m for m in topology["modules"] if m["id"] == module)
        assert saved["counts"] == {"concepts": 3, "edges": 1, "groups": 4} and saved["name"] == "General topology"
        j = client.post("/api/journeys", json={"name": "", "islands": ["general-topology"], "modules": [module]})
        assert j.status_code == 201
        m = client.get(f"/api/journeys/{j.json()['id']}/map").json()
        assert m["journey"]["island_names"] == {"general-topology": "General topology"}
        assert {g["msc"] for g in m["groups"] if g["depth"] == 3} == {"54D10", "54D30"}, "the group tree is the MSC subtree"
        compact = next(c for c in m["concepts"] if c["name"] == "IsCompact")
        assert next(g for g in m["groups"] if g["id"] == compact["home_group"])["msc"] == "54D30"
        new_la = build(client, app, "linear-algebra")
        la = next(f for f in client.get("/api/catalog").json()["fields"] if f["id"] == "linear-algebra")
        assert la["recommended"] == new_la == "linear-algebra-mathlib@c44e0c8e-script" and not la["can_build_new"]
        assert client.post("/api/modules/build", json={"island": "probability"}).status_code == 400
        assert client.post("/api/journeys", json={"name": "x", "islands": ["atlantis"]}).status_code == 400


def test_a_journey_can_use_more_than_four_groups_with_bridges_built_on_demand(tmp_path, index_dir):
    app = app_for(tmp_path, index_dir)
    islands = ["general-topology", "measure-and-integration", "functional-analysis", "combinatorics", "graph-theory"]
    with TestClient(app) as client:
        modules = [build(client, app, i) for i in islands]
        result = client.post("/api/modules/bridges", json={"modules": modules}).json()
        assert len(result["bridges"]) == 2 and result["built"] == result["bridges"], "only pairs that share a link get a bridge"
        again = client.post("/api/modules/bridges", json={"modules": modules}).json()
        assert sorted(again["bridges"]) == sorted(result["bridges"]) and again["built"] == [], "each pair is worked out once"
        s = app.state.store
        bridges = [s.get("modules", b) for b in result["bridges"]]
        pairs = {tuple(sorted(i for i in b["islands"])) for b in bridges}
        assert pairs == {("general-topology", "measure-and-integration"), ("combinatorics", "graph-theory")}
        assert all(b["counts"]["concepts"] == 0 and b["counts"]["edges"] == 1 and "↔" in b["name"] for b in bridges)
        assert len([b for b in s.all("builds") if b["id"].startswith("nolink:")]) == 8, "pairs without a link are remembered"
        edge = s.layered("edges", ["module:" + next(b["id"] for b in bridges if "measure-and-integration" in b["islands"])])[0]
        assert edge["type"] == "dependency" and edge["tier"] == "intuitive", "bridges are dependency metadata, never inference"
        j = client.post("/api/journeys", json={"name": "Five", "islands": islands, "modules": modules + result["bridges"]})
        assert j.status_code == 201 and len(j.json()["islands"]) == 5
        m = client.get(f"/api/journeys/{j.json()['id']}/map").json()
        assert len({c["island"] for c in m["concepts"]}) == 5
        # Default selection (no explicit modules) picks the saved groups and their bridges too.
        d = client.post("/api/journeys", json={"name": "Default", "islands": ["general-topology", "measure-and-integration"]})
        assert d.status_code == 201 and len(d.json()["modules"]) == 3
        assert client.post("/api/modules/bridges", json={"modules": []}).status_code == 400
        assert client.post("/api/modules/bridges", json={"modules": ["nope"]}).status_code == 404
        thirteen = client.post("/api/journeys", json={"name": "x", "islands": ["general-topology"] * 13})
        assert thirteen.status_code == 422


def test_store_reads_only_the_layers_asked_for(tmp_path):
    from metis.store import Store

    s = Store(Config(mode="fixture", sqlite_path=str(tmp_path / "s.sqlite")))
    for i in range(6):
        s.put("concepts", {"id": f"c{i}", "layer": "module:a" if i < 4 else "journey:j", "n": i, "flag": i % 2 == 0, "tag": None if i else "x"})
    assert sorted(d["id"] for d in s.layered("concepts", ["journey:j"])) == ["c4", "c5"]
    assert len(s.layered("concepts", ["module:a", "journey:j"])) == 6 and s.layered("concepts", []) == []
    assert s.count_layer("concepts", "module:a") == 4 and s.count_layer("concepts", "module:none") == 0
    assert [d["id"] for d in s.all("concepts", layer="module:a", n=2)] == ["c2"]
    assert sorted(d["id"] for d in s.all("concepts", flag=True)) == ["c0", "c2", "c4"], "non-string filters still compare in Python"
    assert sorted(d["id"] for d in s.all("concepts", tag=None)) == ["c1", "c2", "c3", "c4", "c5"]
    assert s.all("concepts", layer="module:a", missing="x") == []


def test_indexed_declarations_use_their_recorded_subtopic(index_dir):
    from metis.gods import build_bundle, script_mapping, select_foundational
    from scripts.prepare_module import validate

    spec, declarations, mathlib, _ = load_island(str(index_dir), "general-topology")
    selected = select_foundational(declarations, 100)
    mapping = script_mapping(selected, spec, "top@1")
    assert mapping["declarations"]["IsCompact"]["home_group"] == "top@1:54D30"
    assert mapping["declarations"]["T2Space"]["home_group"] == "top@1:54D10"
    bundle = build_bundle(selected, mapping, "top@1", "1", mathlib, ["general-topology"], {"url": "x"})
    validate(bundle)
    with pytest.raises(ValueError, match="No MSC subtopic"):
        script_mapping([dict(selected[0], msc="46B99")], spec, "top@2")


def test_msc_table_parser_reads_the_official_layout_and_cleans_tex():
    from scripts.fetch_msc import parse, plain_text

    rows = ['code\ttext\tdescription', '"54-XX"\t"General topology"\t"General topology"',
            '"54-01"\t"Introductory exposition"\t"x"', '"54Dxx"\t"Fairly general properties"\t"x"',
            '"54D30"\t"Compactness"\t"Compactness"', '"28A05"\t"Classes of sets (Borel fields, \\(\\sigma\\)-rings, etc.)"\t"x"',
            '"03F40"\t"G\xf6del numberings"\t"x"']
    table = parse("\r\n".join(rows).encode("latin-1"), complete=False)
    assert table["fields"] == {"54": "General topology"} and table["subfields"] == {"54D": "Fairly general properties"}
    assert table["subtopics"] == {"54D30": "Compactness", "28A05": "Classes of sets (Borel fields, σ-rings, etc.)", "03F40": "Gödel numberings"}
    assert table["general_codes_left_out"] == 1
    assert plain_text("(\\infty,1)-categories in \\mathbb{R}^n, \\mathrm{SO}-cobordism") == "(∞,1)-categories in ℝ^n, SO-cobordism"
    with pytest.raises(ValueError, match="incomplete"):
        parse("\r\n".join(rows).encode("latin-1"))


def test_shipped_placement_table_is_well_formed_and_covers_every_mathematical_area():
    rules = load_rules(ROOT / "deploy/msc/mathlib-paths.txt")
    assert len(rules) > 1000
    assert all(code == "-" or re.fullmatch(r"\d\d[A-Z]\d\d", code) for code in rules.values())
    areas = ["Algebra", "AlgebraicGeometry", "AlgebraicTopology", "Analysis", "CategoryTheory", "Combinatorics", "Computability",
             "Condensed", "Control", "Data", "Dynamics", "FieldTheory", "GroupTheory", "InformationTheory", "LinearAlgebra",
             "Logic", "MeasureTheory", "ModelTheory", "NumberTheory", "Order", "Probability", "RepresentationTheory",
             "RingTheory", "Topology"]
    for area in areas:
        assert place("Mathlib." + area + ".Some.Module", rules) not in (None, "-"), area
    assert place("Mathlib.Geometry.Manifold.Basic", rules) == "58A05" and place("Mathlib.SetTheory.Cardinal.Basic", rules) == "03E10"
    assert place("Mathlib.Topology.Compactness.Compact", rules) == "54D30"
    assert place("Mathlib.Tactic.Ring", rules) is None, "tooling areas have no rule and are never extracted"
    local = ROOT / ".lean/msc/msc2020.json"
    if local.is_file():  # the official table is fetched, not committed (CC BY-NC-SA)
        check_rules(rules, json.loads(local.read_text()))


def test_extractor_leaves_out_plumbing_but_keeps_lemmas_named_eq():
    lean = (ROOT / "deploy/lean/Extract.lean").read_text()
    assert "env.isProjectionFn n" in lean and "Linter.isDeprecated env n" in lean and "instanceNames.contains n" in lean
    assert '(s.startsWith "eq_" && s.length > 3 && (s.drop 3).all Char.isDigit)' in lean, "only equation lemmas eq_1, eq_2, …"
    assert 's.startsWith "eq_")' not in lean and '("fields", Json.arr' in lean
