"""The gods (overview, Base graph): curation of a base module from a pinned mathlib export.

By script, with no model: the MSC 2020 group tree for an island (deploy/msc/<island>.json), the
declarations with their proof dependencies, and a documented path-prefix placement with mathlib
docstrings as descriptions.

By judgment, the gods role (Claude in the roster), run once per island module ahead of time:
which results count as foundational and at what level of detail; exactly one home group per
concept; merged duplicates; a short description for each group and concept; textbook results that
fill gaps in mathlib. Gap-fillers are emitted for human review and are never imported on a model's
say-so: a model's citation claim is not a reviewed citation. Dependency edges are compiler metadata,
never inference, and import can never mint verified edges (implementation-review items 2 and 4).
"""

import hashlib
import json
import math
import re

KIND = {
    "theorem": "theorem",
    "def": "definition",
    "structure": "definition",
    "inductive": "definition",
    "class": "definition",
    "opaque": "definition",
    "axiom": "axiom",
}
MAX_PREMISES = 20
MATHLIB_BLOB = "https://github.com/leanprover-community/mathlib4/blob/"


def groups_for(spec, module_id):
    field, island = spec["field"], spec["island"]
    root = module_id + ":" + field["msc"]
    groups = [
        {
            "id": root,
            "name": field["name"],
            "msc": field["msc"],
            "depth": 1,
            "parent": None,
            "ancestors": [root],
            "island": island,
            "description": field["name"],
            "concept_count": 0,
        }
    ]
    for sf in spec["subfields"]:
        sid = module_id + ":" + sf["msc"]
        groups.append(
            {
                "id": sid,
                "name": sf["name"],
                "msc": sf["msc"],
                "depth": 2,
                "parent": root,
                "ancestors": [root, sid],
                "island": island,
                "description": sf["name"],
                "concept_count": 0,
            }
        )
        for st in sf["subtopics"]:
            tid = module_id + ":" + st["msc"]
            groups.append(
                {
                    "id": tid,
                    "name": st["name"],
                    "msc": st["msc"],
                    "depth": 3,
                    "parent": sid,
                    "ancestors": [root, sid, tid],
                    "island": island,
                    "description": st["name"],
                    "concept_count": 0,
                }
            )
    return groups


def place(spec, module_name):
    """Longest matching module-path prefix; the island default otherwise."""
    best = None
    for prefix, msc in spec["paths"]:
        if module_name == prefix or module_name.startswith(prefix + "."):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, msc)
    return best[1] if best else spec["default"]


def dependents(declarations):
    counts = {d["name"]: 0 for d in declarations}
    for d in declarations:
        for dep in set(d.get("dependencies", [])):
            if dep in counts and dep != d["name"]:
                counts[dep] += 1
    return counts


def short_description(declaration, limit=400):
    """First docstring sentence; otherwise the declaration name with its formal statement.
    Never invented prose: an undocumented declaration is described by what it states."""
    doc = " ".join((declaration.get("docstring") or "").split())
    doc = re.split(r"(?<=[.!?])\s+(?=[A-Z])", doc)[0] if doc else ""
    doc = re.sub(r"`", "", doc)
    if not doc:
        doc = declaration["name"] + ": " + " ".join(declaration.get("type", "").split())
    return doc[:limit]


def select_foundational(declarations, limit, min_dependents=1):
    """Script proxy for 'foundational' until the gods decide: declarations that at least
    min_dependents other exported results rely on, or that mathlib documents; ranked by how many
    results depend on them (documented first on ties). Many central theorems carry no docstring
    (Matrix.det_mul, for one), so documentation alone is not the criterion. Deterministic and
    recorded in module.source.selection."""
    counts = dependents(declarations)
    eligible = [
        d
        for d in declarations
        if counts[d["name"]] >= max(1, min_dependents) or (d.get("docstring") or "").strip()
    ]
    eligible.sort(
        key=lambda d: (-counts[d["name"]], not (d.get("docstring") or "").strip(), d["name"])
    )
    return eligible[:limit]


def script_mapping(declarations, spec, module_id):
    groups = groups_for(spec, module_id)
    by_msc = {g["msc"]: g for g in groups}
    mapping = {
        "groups": groups,
        "declarations": {},
        "method": "script: path-prefix placement with mathlib docstrings; not gods-curated",
    }
    for d in declarations:
        group = by_msc.get(place(spec, d["module"]))
        if not group or group["depth"] != 3:
            group = by_msc[spec["default"]]
        mapping["declarations"][d["name"]] = {
            "home_group": group["id"],
            "description": short_description(d),
            "kind": KIND.get(d.get("kind"), "theorem"),
            "name": d["name"],
            "placement": "script",
        }
    return mapping


def build_operation(store, config, digest, island, budget):
    """Durable, budgeted gods operation; the provider layer admits only gods/embeddings for it."""
    if not math.isfinite(budget) or not 0 < budget < min(100, config.live_budget):
        raise ValueError("Build cap must be positive and below the global cap")
    ident = hashlib.sha256(
        json.dumps({"digest": digest, "island": island, "budget": budget}, sort_keys=True).encode()
    ).hexdigest()
    operation = {
        "id": "build_" + ident,
        "kind": "module_build",
        "island": island,
        "budget_usd": budget,
        "fixture": False,
    }
    store.insert("operations", operation)
    return store.get("operations", operation["id"])


def curate(providers, declarations, spec, module_id, operation, batch=40):
    """The gods refine the script mapping. Returns (mapping, pending_review gap-fillers)."""
    mapping = script_mapping(declarations, spec, module_id)
    groups = mapping["groups"]
    by_msc = {g["msc"]: g for g in groups}
    described = providers.call(
        "gods",
        {
            "task": "Write one short description for each MSC group of this island, as it will be used to match new concepts to their home group and to measure content similarity. Describe the mathematics the group holds; do not invent results. Return descriptions: {msc: description}.",
            "island": spec["name"],
            "groups": [{"msc": g["msc"], "name": g["name"], "depth": g["depth"]} for g in groups],
        },
        operation,
        "gods:groups",
    )
    for g in groups:
        text = (described.get("descriptions") or {}).get(g["msc"])
        if isinstance(text, str) and text.strip():
            g["description"] = text.strip()[:400]
    decisions = {}
    for i in range(0, len(declarations), batch):
        chunk = declarations[i : i + batch]
        result = providers.call(
            "gods",
            {
                "task": "You curate a base module of existing mathematics from mathlib declarations. For each declaration decide: foundational (boolean: a result or definition that belongs in a textbook-level map of the field), home_group (exactly one depth-3 MSC code from groups, the deepest that fits), description (one short sentence grounded in the docstring and formal statement; never add content), name (short human-readable name), duplicate_of (another declaration name in this batch when this one restates it, else null). Return decisions: {declaration_name: {foundational, home_group, description, name, duplicate_of}}.",
                "groups": [
                    {"msc": g["msc"], "name": g["name"]} for g in groups if g["depth"] == 3
                ],
                "declarations": [
                    {
                        "name": d["name"],
                        "kind": d.get("kind"),
                        "module": d["module"],
                        "type": d["type"][:2000],
                        "docstring": (d.get("docstring") or "")[:2000],
                        "script_home_group": by_msc_code(mapping, d["name"]),
                    }
                    for d in chunk
                ],
            },
            operation,
            "gods:batch:" + str(i // batch),
        )
        found = result.get("decisions")
        if isinstance(found, dict):
            decisions.update(found)
    kept = {}
    for name, entry in mapping["declarations"].items():
        decision = decisions.get(name)
        if not isinstance(decision, dict):
            kept[name] = entry  # Undecided declarations keep their recorded script placement.
            continue
        if decision.get("foundational") is False or decision.get("duplicate_of"):
            continue
        group = by_msc.get(str(decision.get("home_group")))
        if group and group["depth"] == 3:
            entry["home_group"] = group["id"]
            entry["placement"] = "gods"
        if isinstance(decision.get("description"), str) and decision["description"].strip():
            entry["description"] = decision["description"].strip()[:400]
        if isinstance(decision.get("name"), str) and decision["name"].strip():
            entry["name"] = decision["name"].strip()[:120]
        kept[name] = entry
    mapping["declarations"] = kept
    mapping["method"] = "gods-curated over script placement"
    gaps = providers.call(
        "gods",
        {
            "task": "List standard textbook definitions or results of this island that are missing from the declarations and would be foundational. Each needs a real published source (textbook or paper) with its exact location, the statement, a short description, kind and the depth-3 MSC home group. Return candidates: [{name, statement, description, kind, home_group, source: {url, location}}]. Return an empty list rather than guess; a human reviewer checks every candidate before import.",
            "island": spec["name"],
            "groups": [{"msc": g["msc"], "name": g["name"]} for g in groups if g["depth"] == 3],
            "present": sorted(kept)[:2000],
        },
        operation,
        "gods:gaps",
    )
    pending = [
        dict(c, reviewed=False, review_note="Model-proposed; requires human source review before import")
        for c in (gaps.get("candidates") or [])[:50]
        if isinstance(c, dict)
    ]
    return mapping, pending


def by_msc_code(mapping, name):
    entry = mapping["declarations"].get(name)
    return entry["home_group"].rsplit(":", 1)[-1] if entry else None


def source_url(declaration, mathlib_version):
    module = declaration.get("module", "")
    path = module.replace(".", "/") + ".lean"
    line = declaration.get("line")
    return MATHLIB_BLOB + mathlib_version + "/" + path + ("#L" + str(line) if line else "")


def build_bundle(declarations, mapping, module_id, version, mathlib_version, islands, source, pending=None):
    """Declaration export + mapping -> importable module bundle.

    Concepts keep the exact formal statement with all hypotheses. Each declaration's proof
    dependencies form one dependency hyperedge into it (premises partial after pruning, as the
    overview notes). Dependency edges are compiler metadata only. Import can never mint verified
    edges; verification happens only through the audited local sandbox.
    """
    groups = mapping["groups"]
    home = {g["id"]: g for g in groups}
    counts = dependents(declarations)
    ids, concepts = {}, []
    for d in declarations:
        m = mapping["declarations"].get(d["name"])
        if not m:
            continue
        if m["home_group"] not in home:
            raise ValueError("Unmapped home group")
        ident = module_id + ":" + hashlib.sha256(d["name"].encode()).hexdigest()[:20]
        ids[d["name"]] = ident
        home[m["home_group"]]["concept_count"] = home[m["home_group"]].get("concept_count", 0) + 1
        concepts.append(
            {
                "id": ident,
                "name": m.get("name", d["name"]),
                "statement": d["type"],
                "formal_statement": d["type"],
                "description": m["description"],
                "kind": m.get("kind", "theorem"),
                "home_group": m["home_group"],
                "island": home[m["home_group"]]["island"],
                "status": "Established",
                "integrated": True,
                "source": {
                    "declaration": d["name"],
                    "module": d.get("module"),
                    "url": d.get("source_url") or source_url(d, mathlib_version),
                    "mathlib_version": mathlib_version,
                    "docstring": (d.get("docstring") or "")[:2000] or None,
                    "placement": m.get("placement", "script"),
                    "note": "Exact exported declaration. Import is NOT a local compiler or axiom audit.",
                },
            }
        )
    edges = []
    for d in declarations:
        if d["name"] not in ids:
            continue
        deps = sorted(
            {ids[n] for n in d.get("dependencies", []) if n in ids and n != d["name"]},
            key=lambda ident: (counts[next(k for k, v in ids.items() if v == ident)], ident),
        )
        total = len(deps)
        if total > MAX_PREMISES:
            deps = deps[:MAX_PREMISES]  # most specific dependencies (fewest dependents) first
        if deps:
            edges.append(
                {
                    "id": ids[d["name"]] + ":deps",
                    "premises": deps,
                    "conclusion": ids[d["name"]],
                    "directed": True,
                    "type": "dependency",
                    "tier": "intuitive",
                    "argument": "Compiler dependency metadata only; no implication claimed. Dependencies may be partial. Exact formal statement retains all hypotheses.",
                    "evidence": [
                        {
                            "source": source,
                            "location": d["name"],
                            "mathlib_version": mathlib_version,
                            "dependencies_total": total,
                            "truncated": total > MAX_PREMISES,
                        }
                    ],
                }
            )
    return {
        "module": {
            "id": module_id,
            "version": version,
            "mathlib_version": mathlib_version,
            "islands": islands,
            "name": module_id,
            "source": source,
            "fixture": False,
            "method": mapping.get("method"),
            "coverage": "Mathlib declarations selected by recorded criteria; dependency metadata only, no inference edges",
        },
        "groups": groups,
        "concepts": concepts,
        "edges": edges,
        "pending_review": pending or [],
    }


def bridge_bundle(bundles, exports, module_id, version, mathlib_version, source):
    """Cross-island dependency edges from the same export data, kept in a bridge module that
    requires both island modules (overview, Base graph: 'edges between two islands')."""
    by_name = {}
    for bundle in bundles:
        for c in bundle["concepts"]:
            by_name[c["source"]["declaration"]] = (bundle["module"]["id"], c["id"])
    all_decls = {d["name"]: d for export in exports for d in export["declarations"]}
    counts = dependents(list(all_decls.values()))
    edges = []
    for name, (module, ident) in sorted(by_name.items()):
        d = all_decls.get(name)
        if not d:
            continue
        deps = sorted({dep for dep in d.get("dependencies", []) if dep in by_name and dep != name})
        if not any(by_name[dep][0] != module for dep in deps):
            continue
        premises = [by_name[dep][1] for dep in sorted(deps, key=lambda n: (counts.get(n, 0), n))]
        total = len(premises)
        edges.append(
            {
                "id": module_id + ":" + hashlib.sha256(name.encode()).hexdigest()[:20],
                "premises": premises[:MAX_PREMISES],
                "conclusion": ident,
                "directed": True,
                "type": "dependency",
                "tier": "intuitive",
                "argument": "Cross-field compiler dependency metadata only; no implication claimed.",
                "evidence": [
                    {
                        "source": source,
                        "location": name,
                        "mathlib_version": mathlib_version,
                        "dependencies_total": total,
                        "truncated": total > MAX_PREMISES,
                    }
                ],
            }
        )
    islands = sorted({i for b in bundles for i in b["module"]["islands"]})
    return {
        "module": {
            "id": module_id,
            "version": version,
            "mathlib_version": mathlib_version,
            "islands": islands,
            "requires": [b["module"]["id"] for b in bundles],
            "name": module_id,
            "source": source,
            "fixture": False,
            "coverage": "Cross-field dependency metadata between the required island modules; no inference edges",
        },
        "groups": [],
        "concepts": [],
        "edges": edges,
    }


# ---- In-app basis-group builds (UI spec: "Needs building", progress on the scroll) ----

BUILD_STAGES = [
    "Reading the pinned mathlib export",
    "Choosing foundational results",
    "Placing concepts in their MSC groups",
    "Writing the dependency links",
    "Embedding descriptions",
    "Inking the island onto the map",
]


def vectorize(bundle, providers, operation, batch=96, dimensions=1024):
    """Live builds embed concept and group descriptions once, when the module is built."""
    items = bundle["concepts"] + bundle["groups"]
    for i in range(0, len(items), batch):
        chunk = items[i : i + batch]
        texts = [n["name"] + "\n" + n.get("statement", n.get("description", n["name"])) for n in chunk]
        vectors = providers.call("embeddings", {"texts": texts}, operation, "build-vectors:" + str(i // batch))["embeddings"]
        if len(vectors) != len(chunk) or any(len(v) != dimensions for v in vectors):
            raise ValueError("Invalid embedding response during module build")
        for node, vector in zip(chunk, vectors):
            node["embedding"] = vector
    bundle["module"]["embedding"] = {"dimensions": dimensions, "provider": providers.public().get("embeddings")}
    return bundle


def run_build(store, config, providers, job, spec_dir, limit=800):
    """Build one island module from the configured export. Fixture mode (and live mode without a
    configured gods role) builds the script-mapped module at zero cost and says so; live mode with
    the gods role curates within the job's budget and embeds descriptions. Updates the durable
    job record after every stage; any failure leaves the catalog unchanged."""
    from pathlib import Path
    from metis.base import import_module

    def progress(stage, **extra):
        store.patch("builds", job["id"], stage=BUILD_STAGES[stage], stage_index=stage,
                    percent=int(100 * stage / len(BUILD_STAGES)), **extra)

    try:
        island = job["island"]
        progress(0, status="building")
        spec = json.loads((Path(spec_dir) / (island + ".json")).read_text())
        export = json.loads(Path(config.mathlib_export).read_text())
        prefixes = tuple(spec["module_prefixes"])
        declarations = [
            d for d in export["declarations"]
            if any(d["module"] == p or d["module"].startswith(p + ".") for p in prefixes)
        ]
        if not declarations:
            raise ValueError("The export holds no declarations for " + island)
        progress(1)
        selected = select_foundational(declarations, limit)
        live = config.mode == "live" and config.allow_live
        curated = live and "gods" in providers.roles and job.get("budget_usd", 0) > 0
        digest = hashlib.sha256(json.dumps([export["mathlib"], island, limit, curated], sort_keys=True).encode()).hexdigest()
        module_id = "%s-mathlib@%s-%s" % (island, export["mathlib"][:8], "gods" if curated else "script")
        existing = store.get("modules", module_id)
        if existing and existing.get("status") == "ready":
            store.patch("builds", job["id"], status="ready", percent=100, module_id=module_id, stage="Already built")
            return
        operation = build_operation(store, config, digest, island, job["budget_usd"]) if live and job.get("budget_usd", 0) > 0 else None
        progress(2)
        pending = []
        if curated:
            mapping, pending = curate(providers, selected, spec, module_id, operation)
        else:
            mapping = script_mapping(selected, spec, module_id)
        progress(3)
        source = {
            "url": "https://github.com/leanprover-community/mathlib4/tree/" + export["mathlib"],
            "mathlib": export["mathlib"],
            "lean": export.get("lean"),
            "selection": {"criteria": "declarations other exported results depend on, or documented by mathlib; top %d by dependents" % limit,
                          "candidates": len(declarations), "selected": len(selected)},
            "built_in_app": True,
        }
        bundle = build_bundle(selected, mapping, module_id, export["mathlib"][:8] + ("-gods" if curated else "-script"),
                              export["mathlib"], [island], source, pending)
        progress(4)
        if live:
            if not operation:
                raise ValueError("A live build needs a positive budget for the embeddings (and the gods)")
            vectorize(bundle, providers, operation)
        progress(5)
        pending_review = bundle.pop("pending_review", [])
        if store.mongo is None:
            with store.transaction():
                import_module(store, bundle)
        else:
            import_module(store, bundle)
        store.patch("builds", job["id"], status="ready", percent=100, module_id=module_id,
                    method=mapping["method"], pending_review=pending_review, stage="Ready")
    except Exception as exc:
        store.patch("builds", job["id"], status="failed", error=type(exc).__name__ + ": " + str(exc)[:300])
