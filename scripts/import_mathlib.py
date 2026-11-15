#!/usr/bin/env python3
"""Convert a declaration/dependency JSON export + reviewed MSC mapping to a module.
This importer never promotes compiler dependencies into natural-language implications.
Export schema: [{name, type, dependencies:[name], source_url}].
MSC map schema: {groups:[...], declarations:{name:{home_group,description,kind,name}}}.
All hypotheses stay in exact formal type text. Pin export/mathlib commit separately.
"""

import argparse
import hashlib
import json
from pathlib import Path


def build(declarations, mapping, module_id, version, mathlib_version, islands, source):
    groups = mapping["groups"]
    home = {g["id"]: g for g in groups}
    concepts = []
    ids = {}
    for d in declarations:
        m = mapping["declarations"].get(d["name"])
        if not m:
            continue
        if m["home_group"] not in home:
            raise ValueError("Unmapped home group")
        ident = module_id + ":" + hashlib.sha256(d["name"].encode()).hexdigest()[:20]
        ids[d["name"]] = ident
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
                    "url": d.get("source_url", source),
                    "mathlib_version": mathlib_version,
                    "note": "Exact exported declaration. Import is NOT a local compiler or axiom audit.",
                },
            }
        )
    edges = []
    for d in declarations:
        if d["name"] not in ids:
            continue
        deps = sorted(
            ids[n] for n in d.get("dependencies", []) if n in ids and n != d["name"]
        )
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
        },
        "groups": groups,
        "concepts": concepts,
        "edges": edges,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("declarations")
    p.add_argument("mapping")
    p.add_argument("--id", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--mathlib-version", required=True)
    p.add_argument("--islands", nargs="+", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    bundle = build(
        json.loads(Path(a.declarations).read_text()),
        json.loads(Path(a.mapping).read_text()),
        a.id,
        a.version,
        a.mathlib_version,
        a.islands,
        a.source,
    )
    Path(a.output).write_text(json.dumps(bundle, indent=2))


if __name__ == "__main__":
    main()
