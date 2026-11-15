#!/usr/bin/env python3
"""Place a mathlib declaration export in the MSC 2020 tree and split it into basis groups.

  python scripts/fetch_msc.py --output .lean/msc/msc2020.json
  python -m scripts.index_export --export .lean/exports/mathlib-full.jsonl \
      --msc .lean/msc/msc2020.json --output .lean/exports/index

Point METIS_MATHLIB_EXPORT at the output directory: the New Journey picker then offers every
basis group the data holds, and a missing one is built on demand. No model is involved.
"""
import argparse
import hashlib
import json
from pathlib import Path

from metis.exportindex import build_index, load_rules

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", type=Path, required=True, help="JSONL from deploy/lean/Extract.lean")
    parser.add_argument("--msc", type=Path, required=True, help="JSON from scripts/fetch_msc.py")
    parser.add_argument("--paths", type=Path, default=ROOT / "deploy/msc/mathlib-paths.txt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mathlib", default=json.loads((ROOT / "deploy/lean/pins.json").read_text())["mathlib"])
    parser.add_argument("--lean", default=json.loads((ROOT / "deploy/lean/pins.json").read_text())["lean"])
    args = parser.parse_args()
    msc = json.loads(args.msc.read_text())
    rules = load_rules(args.paths)
    with open(args.export) as lines:
        index = build_index(lines, msc, rules, str(args.output), args.mathlib, args.lean,
                            hashlib.sha256(args.paths.read_bytes()).hexdigest())
    print(json.dumps({"basis_groups": len(index["islands"]), **index["totals"], "output": str(args.output)}, indent=1))


if __name__ == "__main__":
    main()
