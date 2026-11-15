import hashlib
import json
import math
from collections import deque
from pydantic import BaseModel, Field, model_validator
from typing import Literal

TIERS = {"intuitive": 0, "cited": 1, "verified": 2}
INFERENCE = {"implies", "equivalent"}
RELATIONS = {
    "implies",
    "equivalent",
    "defined_from",
    "generalizes",
    "special_case",
    "dependency",
    "related",
}


class Settings(BaseModel):
    tree_weight: float = Field(0.5, ge=0, le=1)
    d_max: int = Field(8, ge=1, le=50)
    group_ratio: float = Field(0.5, ge=0, le=1)
    k: int = Field(50, ge=1, le=200)
    p: int = Field(5, ge=1, le=10)
    integration_depth: int = Field(2, ge=0, le=4)
    new_node_threshold: int = Field(3, ge=3, le=20)
    blind_support: int = Field(2, ge=2, le=4)
    proof_attempts: int = Field(3, ge=0, le=20)
    formalize_definitions: bool = False
    budget_usd: float = Field(0, ge=0, allow_inf_nan=False)


class EdgeInput(BaseModel):
    premises: list[str] = Field(min_length=1, max_length=20)
    conclusion: str
    directed: bool = True
    type: Literal[
        "implies",
        "equivalent",
        "defined_from",
        "generalizes",
        "special_case",
        "dependency",
        "related",
    ] = "implies"
    tier: Literal["intuitive", "cited", "verified"] = "intuitive"
    argument: str = Field(min_length=1, max_length=20000)
    evidence: list[dict] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def check(self):
        if (
            len(set(self.premises)) != len(self.premises)
            or self.conclusion in self.premises
        ):
            raise ValueError("Duplicate or self premise")
        if not self.directed and (len(self.premises) != 1 or self.type != "equivalent"):
            raise ValueError("Undirected equivalence requires exactly two nodes")
        if self.type == "equivalent" and self.directed:
            raise ValueError("Equivalence must be undirected")
        return self


def duplicate_key(edge):
    ends = (
        sorted(edge["premises"] + [edge["conclusion"]])
        if not edge["directed"]
        else [sorted(edge["premises"]), edge["conclusion"]]
    )
    return hashlib.sha256(
        json.dumps([edge["type"], edge["directed"], ends], sort_keys=True).encode()
    ).hexdigest()


def visible_layers(journey):
    return {"journey:" + journey["id"]} | {"module:" + m for m in journey["modules"]}


def graph(store, journey):
    layers = visible_layers(journey)
    result = {
        name: [d for d in store.all(name) if d.get("layer") in layers]
        for name in ("groups", "concepts", "edges")
    }
    invalid = {
        m["target_id"]
        for m in store.all("memory", journey_id=journey["id"])
        if m.get("kind") == "invalidation"
    }
    overrides = {
        m["target_id"]: m
        for m in store.all("memory", journey_id=journey["id"])
        if m.get("kind") == "edge_review_override"
    }
    result["edges"] = [
        dict(
            e, tier=overrides[e["id"]]["tier"], existing=overrides[e["id"]]["existing"]
        )
        if e["id"] in overrides
        else e
        for e in result["edges"]
    ]
    overlays = {e["base_edge_id"]: e for e in result["edges"] if e.get("base_edge_id")}
    result["edges"] = [e for e in result["edges"] if not e.get("base_edge_id")]
    for i, e in enumerate(result["edges"]):
        overlay = overlays.get(e["id"])
        if overlay:
            e = dict(
                e,
                journey_overlay=overlay["id"],
                support_count=e.get("support_count", 1)
                + overlay.get("support_count", 1),
            )
            if overlay.get("review_status") == "passed" and not overlay.get(
                "invalidated"
            ):
                e["journey_evidence"] = overlay.get("evidence", [])
            result["edges"][i] = e
    for name in ("concepts", "edges"):
        result[name] = [
            dict(d, invalidated=True) if d["id"] in invalid else d for d in result[name]
        ]
    return result


def usable(edge, nodes):
    return (
        edge.get("review_status") == "passed"
        and edge.get("tier") in ("cited", "verified")
        and not edge.get("invalidated")
        and all(
            n in nodes
            and nodes[n]["status"] != "Proposed"
            and not nodes[n].get("invalidated")
            for n in edge["premises"] + [edge["conclusion"]]
        )
    )


def tree_distance(a, b):
    depth = 0
    for x, y in zip(a["ancestors"], b["ancestors"]):
        if x != y:
            break
        depth += 1
    return max(0, 3 - depth)


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return None
    denom = math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return max(0, min(1, sum(x * y for x, y in zip(a, b)) / denom)) if denom else 0


def adjacency(nodes, edges, exclude=None):
    adj = {n: set() for n in nodes}
    for e in edges:
        if e["id"] == exclude or e["type"] == "dependency" or not usable(e, nodes):
            continue
        for p in e["premises"]:
            adj[p].add(e["conclusion"])
            adj[e["conclusion"]].add(p)
    return adj


def distance(adj, start, end, cap):
    if start == end:
        return 0
    q = deque([(start, 0)])
    seen = {start}
    while q:
        n, d = q.popleft()
        if d >= cap:
            continue
        for other in adj.get(n, ()):
            if other == end:
                return d + 1
            if other not in seen:
                seen.add(other)
                q.append((other, d + 1))
    return cap


def score(edge, nodes, edges, settings, anchors=None):
    if any(
        nodes[n]["status"] == "Proposed" or nodes[n].get("invalidated")
        for n in edge["premises"] + [edge["conclusion"]]
    ):
        return {
            "value": None,
            "pairs": [],
            "reason": "Quarantined or invalidated endpoint",
            "measured_before_edge": True,
        }
    adj = adjacency(nodes, edges, edge["id"])
    cap = settings["d_max"]
    connected = set(anchors or ()) & nodes.keys()
    if anchors is not None:
        todo = list(connected)
        while todo:
            for neighbor in adj.get(todo.pop(), ()):
                if neighbor not in connected:
                    connected.add(neighbor)
                    todo.append(neighbor)
    pairs = []
    for p in edge["premises"]:
        a, b = nodes[p], nodes[edge["conclusion"]]
        similarity = cosine(a.get("embedding"), b.get("embedding"))
        if similarity is None:
            pairs.append(
                {"premise": p, "score": None, "reason": "Embedding unavailable"}
            )
            continue
        td = tree_distance(a, b)
        gd = distance(adj, p, b["id"], cap)
        integrated = (
            bool(adj.get(p))
            and bool(adj.get(b["id"]))
            and a.get("integrated", True)
            and b.get("integrated", True)
        )
        if anchors is not None:
            integrated = (
                bool(adj.get(p))
                and bool(adj.get(b["id"]))
                and p in connected
                and b["id"] in connected
            )
        wt = settings["tree_weight"] if integrated else 1
        pairs.append(
            {
                "premise": p,
                "similarity": similarity,
                "tree_distance": td,
                "graph_distance": gd,
                "tree_only": not integrated,
                "score": similarity * (wt * td / 3 + (1 - wt) * gd / cap),
            }
        )
    scores = [p["score"] for p in pairs if p["score"] is not None]
    return {
        "value": max(scores) if scores else None,
        "pairs": pairs,
        "measured_before_edge": True,
    }


def proof_closure(starts, nodes, edges, allow_cited=True):
    """Least fixed point enforces AND hyperedges, OR alternatives, direction and quarantine.
    Cited arguments are literature supported, NEVER machine verified.
    """
    reached = {
        n: {"label": "assumption", "edges": []}
        for n in starts
        if n in nodes
        and nodes[n]["status"] != "Proposed"
        and not nodes[n].get("invalidated")
    }
    changed = True
    while changed:
        changed = False
        for e in edges:
            if (
                e["type"] not in INFERENCE
                or not usable(e, nodes)
                or (not allow_cited and e["tier"] != "verified")
            ):
                continue
            directions = [(e["premises"], e["conclusion"])]
            if not e["directed"]:
                directions.append(([e["conclusion"]], e["premises"][0]))
            for premises, conclusion in directions:
                if all(p in reached for p in premises) and conclusion not in reached:
                    # Exact formal composition is not checked by this graph traversal.
                    reached[conclusion] = {
                        "label": "literature supported"
                        if e["tier"] == "cited"
                        or any(
                            reached[p]["label"] == "literature supported"
                            for p in premises
                        )
                        else "machine-verified steps; composition unverified",
                        "edges": list(
                            dict.fromkeys(
                                sum((reached[p]["edges"] for p in premises), [])
                                + [e["id"]]
                            )
                        ),
                    }
                    changed = True
    return reached


def blind_edge(edge, nodes):
    return {
        "premises": [
            {
                "id": p,
                "statement": nodes[p]["statement"],
                "description": nodes[p]["description"],
                "kind": nodes[p]["kind"],
            }
            for p in edge["premises"]
        ],
        "conclusion": {
            "id": edge["conclusion"],
            "statement": nodes[edge["conclusion"]]["statement"],
            "description": nodes[edge["conclusion"]]["description"],
            "kind": nodes[edge["conclusion"]]["kind"],
        },
        "directed": edge["directed"],
        "type": edge["type"],
        "tier": edge["tier"],
        "argument": edge["argument"],
        "evidence": edge["evidence"],
    }


def invalidate_dependents(store, journey, edge_id, reason):
    g = graph(store, journey)
    bad = {edge_id}
    changed = True
    while changed:
        changed = False
        for e in g["edges"]:
            if e["id"] not in bad and any(
                dep in bad for dep in e.get("proof_dependencies", [])
            ):
                bad.add(e["id"])
                changed = True
    for ident in bad:
        store.put(
            "memory",
            {
                "id": journey["id"] + ":invalid:" + ident,
                "journey_id": journey["id"],
                "kind": "invalidation",
                "target_id": ident,
                "reason": reason,
            },
        )
    for e in g["edges"]:
        if e["id"] in bad and e["layer"] == "journey:" + journey["id"]:
            history = e.get("tier_history", []) + [
                {"tier": e["tier"], "action": "invalidated", "reason": reason}
            ]
            store.patch("edges", e["id"], invalidated=True, tier_history=history)
    return sorted(bad)
