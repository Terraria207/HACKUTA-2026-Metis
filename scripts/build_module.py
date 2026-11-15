#!/usr/bin/env python3
"""Build an island or bridge base module from a pinned mathlib declaration export.

  python -m scripts.build_module island EXPORT.json --spec deploy/msc/<island>.json \
      --id <island>-mathlib@<version> --version <version> --limit 600 --output corpus/<file>.json
  python -m scripts.build_module bridge --bundles A.json B.json --exports a.json b.json \
      --id <a>-<b>-bridge@<version> --version <version> --output corpus/<file>.json

The default path is offline and deterministic: the "by script" half of the overview's base graph
(MSC tree, declarations, dependencies, path-prefix placement, docstring descriptions), labeled as
script-mapped. --execute runs the gods role through a durable, budgeted module_build operation and
labels the result gods-curated; gap-fillers it proposes go to pending_review for a human.
Every bundle is validated with the real importer against a scratch store before it is written.
"""
import argparse
import hashlib
import json
from pathlib import Path

from metis.gods import (
    bridge_bundle,
    build_bundle,
    build_operation,
    curate,
    script_mapping,
    select_foundational,
)
from scripts.prepare_module import validate


def load(path):
    return json.loads(Path(path).read_text())


def island(args):
    export, spec = load(args.export), load(args.spec)
    prefixes = tuple(spec["module_prefixes"])
    declarations = [
        d for d in export["declarations"]
        if any(d["module"] == p or d["module"].startswith(p + ".") for p in prefixes)
    ]
    selected = select_foundational(declarations, args.limit, args.min_dependents)
    source = {
        "url": "https://github.com/leanprover-community/mathlib4/tree/" + export["mathlib"],
        "mathlib": export["mathlib"],
        "lean": export.get("lean"),
        "export_sha256": hashlib.sha256(json.dumps(export, sort_keys=True).encode()).hexdigest(),
        "selection": {
            "criteria": "declarations with >= %d exported dependents, or documented by mathlib; top %d ranked by dependents (documented first on ties)"
            % (max(1, args.min_dependents), args.limit),
            "candidates": len(declarations),
            "selected": len(selected),
        },
        "msc_spec": args.spec,
    }
    pending = []
    if args.execute:
        from metis.config import Config
        from metis.store import Store
        from metis.providers import Providers

        config = Config().validate()
        if config.mode != "live" or not config.allow_live or not 0 < config.live_budget <= 100:
            raise SystemExit("Explicit live mode and global budget in (0,100] required for the gods")
        store = Store(config)
        try:
            providers = Providers(store, config)
            operation = build_operation(store, config, source["export_sha256"], spec["island"], args.budget)
            mapping, pending = curate(providers, selected, spec, args.id, operation)
        finally:
            store.mongo.client.close() if store.mongo is not None else store.sql.close()
    else:
        mapping = script_mapping(selected, spec, args.id)
    bundle = build_bundle(selected, mapping, args.id, args.version, export["mathlib"], [spec["island"]], source, pending)
    validate(bundle)
    Path(args.output).write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({
        "module": args.id, "method": mapping["method"], "concepts": len(bundle["concepts"]),
        "edges": len(bundle["edges"]), "pending_review": len(pending), "output": args.output,
    }))


def bridge(args):
    bundles = [load(p) for p in args.bundles]
    exports = [load(p) for p in args.exports]
    versions = {b["module"]["mathlib_version"] for b in bundles} | {e["mathlib"] for e in exports}
    if len(versions) != 1:
        raise SystemExit("All bundles and exports must share one mathlib version")
    source = {
        "url": "https://github.com/leanprover-community/mathlib4/tree/" + next(iter(versions)),
        "mathlib": next(iter(versions)),
        "requires": [b["module"]["id"] for b in bundles],
    }
    bundle = bridge_bundle(bundles, exports, args.id, args.version, next(iter(versions)), source)
    validate(bundle, bundles)
    Path(args.output).write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"module": args.id, "edges": len(bundle["edges"]), "output": args.output}))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("island")
    a.add_argument("export")
    a.add_argument("--spec", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--version", required=True)
    a.add_argument("--limit", type=int, default=600)
    a.add_argument("--min-dependents", type=int, default=1)
    a.add_argument("--output", required=True)
    a.add_argument("--execute", action="store_true", help="Run the gods role (live mode, budgeted)")
    a.add_argument("--budget", type=float, default=5.0)
    a.set_defaults(func=island)
    b = sub.add_parser("bridge")
    b.add_argument("--bundles", nargs=2, required=True)
    b.add_argument("--exports", nargs="+", required=True)
    b.add_argument("--id", required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--output", required=True)
    b.set_defaults(func=bridge)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
