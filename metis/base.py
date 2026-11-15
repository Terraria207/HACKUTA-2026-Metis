"""Versioned, traceable small fixture corpus. Not an extracted mathlib corpus."""

from metis.graph import EdgeInput, duplicate_key

ISLANDS = {
    "number-theory": ("Number theory", "11", "11B", "11B83"),
    "linear-algebra": ("Linear algebra", "15", "15A", "15A03"),
    "graph-theory": ("Graph theory", "05", "05C", "05C50"),
    "probability": ("Probability", "60", "60B", "60B20"),
}


def seed(store):
    for island, (name, field, region, village) in ISLANDS.items():
        if island == "number-theory":
            continue  # Explicitly import the real corpus; never fabricate a fixture.
        mid = island + "@fixture-1"
        if store.get("modules", mid):
            continue
        layer = "module:" + mid
        groups = []
        for depth, (code, title) in enumerate(
            (
                (field, name),
                (region, name + " structures"),
                (
                    village,
                    {
                        "linear-algebra": "Vector spaces",
                        "graph-theory": "Spectral graph theory",
                        "probability": "Random matrices",
                    }[island],
                ),
            ),
            1,
        ):
            gid = mid + ":" + code
            groups.append(gid)
            store.put(
                "groups",
                {
                    "id": gid,
                    "layer": layer,
                    "island": island,
                    "msc": code,
                    "name": title,
                    "depth": depth,
                    "parent": groups[-2] if depth > 1 else None,
                    "ancestors": groups.copy(),
                    "description": title,
                    "concept_count": 2,
                    "fixture": True,
                },
            )
        concepts = {
            "linear-algebra": [
                (
                    "vector",
                    "Vector space",
                    "A vector space over a field with addition and scalar multiplication.",
                    "definition",
                ),
                (
                    "spectral",
                    "Spectral theorem",
                    "A real symmetric matrix admits an orthonormal basis of eigenvectors.",
                    "theorem",
                ),
            ],
            "graph-theory": [
                (
                    "adjacency",
                    "Adjacency matrix",
                    "The adjacency matrix of a finite undirected simple graph is real symmetric.",
                    "definition",
                ),
                (
                    "graph-spectrum",
                    "Graph spectrum",
                    "The eigenvalues of the adjacency matrix of an undirected graph are real.",
                    "theorem",
                ),
            ],
            "probability": [
                (
                    "covariance",
                    "Covariance matrix",
                    "The covariance matrix of a random vector with finite second moments is positive semidefinite.",
                    "definition",
                ),
                (
                    "variance",
                    "Variance of linear combinations",
                    "For real a and finite-second-moment random vector X, Var(aᵀX) = aᵀ Cov(X) a.",
                    "theorem",
                ),
            ],
        }[island]
        for i, (short, title, statement, kind) in enumerate(concepts):
            store.put(
                "concepts",
                {
                    "id": mid + ":" + short,
                    "layer": layer,
                    "name": title,
                    "statement": statement,
                    "description": statement,
                    "kind": kind,
                    "home_group": groups[-1],
                    "ancestors": groups.copy(),
                    "island": island,
                    "status": "Established",
                    "integrated": True,
                    "fixture": True,
                    "source": {
                        "agent": "fixture curator",
                        "url": "https://msc2020.org/",
                        "note": "Illustrative corpus; no formal verification claimed",
                    },
                    "embedding": [0.8, 0.6, 0.1 + i * 0.1],
                },
            )
        store.put(
            "modules",
            {
                "id": mid,
                "name": name,
                "islands": [island],
                "version": "fixture-1",
                "mathlib_version": None,
                "status": "ready",
                "fixture": True,
                "source": "Manually authored illustrative fixture, not mathlib extraction",
                "groups": groups,
            },
        )


def import_module(store, bundle):
    """Import immutable reviewed modules. Raw dependency graphs can never become inference."""
    m = bundle["module"]
    mid = m["id"]
    import hashlib
    import json
    fingerprint = hashlib.sha256(json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old = store.get("modules", mid)
    if old and (old.get("status") != "building" or old.get("bundle_sha256") != fingerprint):
        raise ValueError("Module version already exists; publish a new version")
    if not m.get("version") or not m.get("source") or not m.get("islands"):
        raise ValueError("Module requires version, source and islands")
    for name in ("groups", "concepts", "edges"):
        ids = [d["id"] for d in bundle.get(name, [])]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate identifiers within bundle")
    layer = "module:" + mid
    required = m.get("requires", [])
    if any(
        not store.get("modules", r) or store.get("modules", r)["status"] != "ready"
        for r in required
    ):
        raise ValueError("Required module versions must be ready")
    external_groups = {
        g["id"]: g
        for g in store.all("groups")
        if g.get("layer") in {"module:" + r for r in required}
    }
    external_nodes = {
        n["id"]: n
        for n in store.all("concepts")
        if n.get("layer") in {"module:" + r for r in required}
    }
    for name in ("groups", "concepts", "edges"):
        if any(store.get(name, d["id"]) and not (
            old and store.get(name, d["id"]).get("layer") == layer
        ) for d in bundle.get(name, [])):
            raise ValueError("Imported identifiers must be globally unique")
    groups = {g["id"]: g for g in bundle.get("groups", [])}
    nodes = {n["id"]: n for n in bundle.get("concepts", [])}
    if not groups and not external_groups or not nodes and not external_nodes:
        raise ValueError("Module requires concepts/groups or pinned prerequisites")
    for g in groups.values():
        if (
            g["depth"] not in (1, 2, 3)
            or len(g["ancestors"]) != g["depth"]
            or g["ancestors"][-1] != g["id"]
        ):
            raise ValueError("Invalid group ancestry")
        if g.get("island") not in m["islands"]:
            raise ValueError("Group island must belong to its module")
        if g["depth"] == 1:
            if g.get("parent") is not None or g["ancestors"] != [g["id"]]:
                raise ValueError("Invalid island root")
        else:
            parent = {**external_groups, **groups}.get(g.get("parent"))
            if not parent:
                raise ValueError("Missing group parent")
            if (
                parent["depth"] != g["depth"] - 1
                or parent["island"] != g["island"]
                or g["ancestors"] != parent["ancestors"] + [g["id"]]
            ):
                raise ValueError("Group ancestry must match its parent")
    for n in nodes.values():
        if n["home_group"] not in {**external_groups, **groups} or not n.get("source"):
            raise ValueError("Concept requires home group and source")
        if n.get("status") == "Proven":
            raise ValueError(
                "Import does not certify natural language concepts as Proven"
            )
        n.update(
            ancestors={**external_groups, **groups}[n["home_group"]]["ancestors"],
            status="Established",
        )
    edges = []
    for raw in bundle.get("edges", []):
        e = dict(raw, **EdgeInput.model_validate(raw).model_dump())
        if not all(
            n in nodes or n in external_nodes for n in e["premises"] + [e["conclusion"]]
        ):
            raise ValueError("Module edge endpoint missing")
        if e["type"] == "dependency":
            e["tier"] = "intuitive"
            e["inference"] = False
        elif e["tier"] == "verified":
            raise ValueError(
                "Import cannot mint verified edges: use local audited formal verification"
            )
        elif e["tier"] != "cited" or not any(
            v.get("source") and v.get("location") and v.get("reviewed")
            for v in e["evidence"]
        ):
            raise ValueError("Base inference requires reviewed citation")
        e.update(
            layer=layer,
            duplicate_key=duplicate_key(e),
            review_status="passed",
            existing="Existing" if e["tier"] == "cited" else "Unchecked",
            fixture=bool(m.get("fixture")),
            support_count=1,
        )
        edges.append(e)
    # Building modules are invisible; ready is written last.
    if not old and not store.insert("modules", dict(m, status="building", bundle_sha256=fingerprint)):
        raise ValueError("Concurrent module publication; retry preparation")
    for collection, docs in [
        ("groups", groups.values()),
        ("concepts", nodes.values()),
        ("edges", edges),
    ]:
        for d in docs:
            store.put(collection, dict(d, layer=layer))
    return store.put("modules", dict(m, status="ready", bundle_sha256=fingerprint))


def catalog(store, live=False):
    """Deployment inventory, never a claim of exhaustive mathematical coverage."""
    modules = []
    for m in store.all("modules"):
        layer = "module:" + m["id"]
        counts = {key: len(store.all(key, layer=layer)) for key in ("concepts", "edges", "groups")}
        modules.append(dict(m, counts=counts, available=m.get("status") == "ready" and not (live and m.get("fixture")),
                            coverage=m.get("coverage", "Illustrative fixture" if m.get("fixture") else "Curated scope; incomplete")))
    return {"fields": [{"id": i, "name": meta[0], "ready": any(m["available"] and i in m["islands"] for m in modules),
                        "modules": [m for m in modules if i in m["islands"]]} for i, meta in ISLANDS.items()]}


def validate_selection(store, chosen, islands, live=False):
    if len(set(chosen)) != len(chosen) or any(i not in ISLANDS for i in islands):
        raise ValueError("Duplicate module or unknown field")
    modules = [store.get("modules", mid) for mid in chosen]
    if any(not m or m.get("status") != "ready" or (live and m.get("fixture")) for m in modules):
        raise ValueError("Select ready modules compatible with the deployment mode")
    if any(not set(m.get("requires", [])).issubset(chosen) for m in modules):
        raise ValueError("Select exact pinned prerequisites")
    for island in islands:
        roots = [m for m in modules if m["islands"] == [island] and not m.get("additive")]
        if len(roots) != 1:
            raise ValueError("Select exactly one root version per field; use an additive extension or a new journey")
    if set(islands) != {i for m in modules for i in m["islands"]}:
        raise ValueError("Modules must cover exactly the selected fields")


def import_corpus(store, directory=None, log=None):
    """Fixture-mode startup import of the reviewed bundles shipped in corpus/, in prerequisite
    order, skipping versions already published. Vectors are not fabricated: fixture similarity
    is reported unavailable for these concepts. Live deployments use scripts/prepare_module.py.
    Returns the module IDs imported now."""
    import json
    from pathlib import Path

    directory = Path(directory or Path(__file__).resolve().parent.parent / "corpus")
    bundles = []
    for path in sorted(directory.glob("*.json")):
        try:
            bundle = json.loads(path.read_text())
        except ValueError:
            continue
        if isinstance(bundle, dict) and isinstance(bundle.get("module"), dict) and bundle["module"].get("id"):
            bundles.append(bundle)
    imported, pending = [], list(bundles)
    for _ in range(len(bundles) + 1):
        remaining = []
        for bundle in pending:
            mid = bundle["module"]["id"]
            existing = store.get("modules", mid)
            if existing and existing.get("status") == "ready":
                continue
            requires = bundle["module"].get("requires", [])
            if any((store.get("modules", r) or {}).get("status") != "ready" for r in requires):
                remaining.append(bundle)
                continue
            try:
                # One SQLite write transaction per bundle: thousands of autocommitted inserts
                # would otherwise fsync one by one at every fixture startup.
                with store.transaction():
                    import_module(store, bundle)
                imported.append(mid)
            except ValueError as exc:
                if log:
                    log("corpus import skipped %s: %s" % (mid, exc))
        if not remaining:
            break
        pending = remaining
    return imported
