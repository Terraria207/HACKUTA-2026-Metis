import pytest
from metis.graph import *


def node(i, anc=None, status="Established", embedding=None):
    return dict(
        id=i,
        status=status,
        ancestors=anc or ["a", "b", "c"],
        embedding=embedding or [1, 0],
        description=i,
        statement=i,
        kind="theorem",
    )


def edge(p, c, tier="cited", **kw):
    return dict(
        id="-".join(p) + ">" + c,
        premises=p,
        conclusion=c,
        directed=True,
        type="implies",
        tier=tier,
        review_status="passed",
        **kw,
    )


def test_and_or_and_cycles():
    nodes = {i: node(i) for i in "ABCD"}
    hyper = edge(["A", "B"], "C")
    assert "C" not in proof_closure(["A"], nodes, [hyper])
    assert (
        proof_closure(["A", "B"], nodes, [hyper])["C"]["label"]
        == "literature supported"
    )
    assert "C" in proof_closure(["A"], nodes, [edge(["A"], "C"), edge(["B"], "C")])
    assert proof_closure([], nodes, [edge(["A"], "B"), edge(["B"], "A")]) == {}
    assert "A" not in proof_closure(["C"], nodes, [edge(["A"], "C")])


def test_equivalence():
    nodes = {i: node(i) for i in "AB"}
    e = edge(["A"], "B")
    e.update(type="equivalent", directed=False)
    assert "A" in proof_closure(["B"], nodes, [e])


@pytest.mark.parametrize(
    "relation", ["defined_from", "generalizes", "special_case", "dependency", "related"]
)
def test_non_inference_never_proves(relation):
    nodes = {i: node(i) for i in "AB"}
    e = edge(["A"], "B")
    e["type"] = relation
    assert "B" not in proof_closure(["A"], nodes, [e])


def test_quarantine_and_invalidation():
    nodes = {i: node(i) for i in "AB"}
    e = edge(["A"], "B")
    nodes["B"]["status"] = "Proposed"
    assert "B" not in proof_closure(["A"], nodes, [e])
    assert not adjacency(nodes, [e])["A"]
    assert score(e, nodes, [e], Settings().model_dump())["value"] is None
    nodes["B"]["status"] = "Accepted"
    e["invalidated"] = True
    assert "B" not in proof_closure(["A"], nodes, [e])


def test_distance_hyperedge_star_exclusion_and_cap():
    nodes = {i: node(i) for i in "ABCD"}
    e = edge(["A", "B"], "C")
    adj = adjacency(nodes, [e])
    assert distance(adj, "A", "C", 8) == 1
    assert distance(adj, "C", "A", 8) == 1
    assert distance(adj, "A", "B", 8) == 2
    assert distance(adj, "A", "D", 8) == 8
    assert distance(adjacency(nodes, [e], e["id"]), "A", "C", 8) == 8
    for tier in ("intuitive",):
        e["tier"] = tier
        assert not adjacency(nodes, [e])["A"]


def test_score_tree_only_and_preedge():
    nodes = {"A": node("A", ["a", "b", "c"]), "B": node("B", ["d", "e", "f"])}
    e = edge(["A"], "B")
    s = score(e, nodes, [e], Settings().model_dump())
    assert s["value"] == 1
    assert s["pairs"][0]["tree_only"]
    assert s["pairs"][0]["graph_distance"] == 8
    nodes["B"]["embedding"] = None
    assert score(e, nodes, [], Settings().model_dump())["value"] is None
    assert cosine([1, 0], [-1, 0]) == 0


def test_machine_composition_is_conservative():
    nodes = {i: node(i) for i in "AB"}
    e = edge(["A"], "B", "verified")
    assert (
        proof_closure(["A"], nodes, [e])["B"]["label"]
        == "machine-verified steps; composition unverified"
    )
    assert "B" not in proof_closure(["A"], nodes, [dict(e, tier="cited")], False)


def test_identity_type_direction_and_order():
    a = edge(["A", "B"], "C")
    b = dict(a, premises=["B", "A"])
    assert duplicate_key(a) == duplicate_key(b)
    assert duplicate_key(a) != duplicate_key(dict(a, type="defined_from"))
    e = edge(["A"], "B")
    e.update(type="equivalent", directed=False)
    assert duplicate_key(e) == duplicate_key(dict(e, premises=["B"], conclusion="A"))


def test_blinding():
    n = {i: node(i) for i in "AB"}
    e = dict(
        edge(["A"], "B"),
        argument="Argument",
        evidence=[],
        provenance={"agent": "Crew", "perspective": "historical"},
        support_count=4,
    )
    serialized = str(blind_edge(e, n))
    assert (
        "Crew" not in serialized
        and "historical" not in serialized
        and "support_count" not in serialized
    )
