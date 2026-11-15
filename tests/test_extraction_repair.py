"""Malformed internal-paper edges must not silently disappear from live extraction."""
import copy
from unittest.mock import Mock
import pytest
from test_api import paper, run


@pytest.mark.parametrize("failure", ["numeric-tier", "unknown-reference", "invalid-concept", "empty"])
def test_live_extraction_repairs_relationships_once(app, client, journey, monkeypatch, failure):
    w, s = app.state.worker, app.state.store
    r = dict(run(client, journey, paper(client, journey)), fixture=False)
    _, _, nodes = w.context(r)
    existing = list(nodes.values())[:2]
    good = {
        "concepts": [
            dict(key=str(i), name=n["name"], statement=n["statement"],
                 description=n["description"], kind=n["kind"], msc="15A")
            for i, n in enumerate(existing)
        ],
        "edges": [dict(premises=["0"], conclusion="1", type="dependency",
                       directed=True, tier="intuitive", argument="Uses this definition.", evidence=[])],
        "msc_codes": ["15A"],
    }
    bad = copy.deepcopy(good)
    if failure == "numeric-tier":
        bad["edges"][0]["tier"] = 1
    elif failure == "unknown-reference":
        bad["edges"][0]["premises"] = ["missing"]
    elif failure == "invalid-concept":
        bad["concepts"][0]["msc"] = ["15A"]
    else:
        bad["edges"] = []
    calls = []
    def fake_call(role, payload, run, key):
        calls.append(key)
        if key == "extract":
            return bad
        if key == "extract:repair":
            assert payload["paper_text"]
            return good
        if key == "extract-vectors":
            return {"embeddings": [[1, 0, 0]] * 2}
        raise AssertionError(key)
    monkeypatch.setattr(w, "call", fake_call)
    monkeypatch.setattr(w, "stage3", Mock())
    w.stage0(r)
    assert calls == ["extract", "extract:repair", "extract-vectors"]
    assert len(s.all("edges", run_id=r["id"])) == 1
    assert s.all("extractions")[0]["extraction"] == good
    # Cache re-use does not repeat paid repair, and the saved relation is idempotent.
    w.stage0(r)
    assert calls.count("extract:repair") == 1
    assert len(s.all("edges", run_id=r["id"])) == 1


def test_still_invalid_repair_fails_before_caching_or_embedding(app, client, journey, monkeypatch):
    w, s = app.state.worker, app.state.store
    r = dict(run(client, journey, paper(client, journey)), fixture=False)
    bad = {"concepts": [], "edges": [{"tier": 1}], "msc_codes": []}
    mocked = Mock(return_value=bad)
    monkeypatch.setattr(w, "call", mocked)
    with pytest.raises(ValueError, match="after one repair"):
        w.stage0(r)
    assert mocked.call_count == 2
    assert not s.all("extractions")
    assert not w.run_edges(r)


@pytest.mark.parametrize("relation, expected", [
    ("dependency", "not a logical implication"),
    ("defined_from", "not a logical implication"),
    ("implies", "require every stated hypothesis"),
])
def test_review_receives_correct_relation_semantics(app, client, journey, monkeypatch, relation, expected):
    w = app.state.worker
    r = run(client, journey, paper(client, journey))
    w.stage0(r)
    e = w.run_edges(r)[0]
    e = dict(e, type=relation)
    _, _, nodes = w.context(r)
    payloads = []
    def fake_call(role, payload, run, key):
        payloads.append(payload)
        if role == "hypothesis":
            return dict(hypotheses_match=True, premises_necessary=True, counterexample_found=False)
        return dict(verdict="pass", well_defined=True, not_duplicate=True, not_trivial=True,
                    citation_valid=False)
    monkeypatch.setattr(w, "call", fake_call)
    w.review(dict(r, fixture=False), e, nodes, "semantic-test")
    assert len(payloads) == 2
    assert all(expected in p["relation_semantics"] for p in payloads)
