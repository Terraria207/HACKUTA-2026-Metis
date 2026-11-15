#!/usr/bin/env python3
"""Run the Lean declaration export inside the pinned mathlib project.

  # every mathematical area of mathlib (about six minutes, a few GB of memory, ~130 MB)
  python scripts/extract_mathlib.py --project /abs/mathlib --output .lean/exports/mathlib-full.jsonl
  # then place it in the MSC tree and split it into basis groups
  python -m scripts.index_export --export .lean/exports/mathlib-full.jsonl --msc .lean/msc/msc2020.json --output .lean/exports/index

  # or only some areas, as one JSON file for a single hand-written basis-group spec
  python scripts/extract_mathlib.py --project /abs/mathlib --prefixes Mathlib.LinearAlgebra --output la.json

Requires the project prepared by scripts/setup_lean.py (METIS_MATHLIB_VERSION present) and lake on
PATH. No model or network is used. A .jsonl output is written as it is produced, one declaration
per line, with a .meta.json beside it; a .json output is the older single-file form.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / "deploy/lean/pins.json").read_text())
# The mathematical areas of mathlib. Tactic, Util, Lean, Std, Mathport, Testing, Init and
# Deprecated are tooling or legacy, not mathematics, and are never exported.
MATH_AREAS = [
    "Algebra", "AlgebraicGeometry", "AlgebraicTopology", "Analysis", "CategoryTheory", "Combinatorics",
    "Computability", "Condensed", "Control", "Data", "Dynamics", "FieldTheory", "Geometry", "GroupTheory",
    "InformationTheory", "LinearAlgebra", "Logic", "MeasureTheory", "ModelTheory", "NumberTheory", "Order",
    "Probability", "RepresentationTheory", "RingTheory", "SetTheory", "Topology",
]


def source_url(declaration):
    path = declaration["module"].replace(".", "/") + ".lean"
    return ("https://github.com/leanprover-community/mathlib4/blob/" + PINS["mathlib"] + "/" + path
            + ("#L%d" % declaration["line"] if declaration.get("line") else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--prefixes", nargs="+", default=["Mathlib." + a for a in MATH_AREAS],
                        help="Module prefixes to export (default: every mathematical area)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    marker = project / "METIS_MATHLIB_VERSION"
    if not marker.is_file() or marker.read_text().strip() != PINS["mathlib"]:
        raise SystemExit("Prepared pinned mathlib project required (run scripts/setup_lean.py)")
    toolchain = (project / "lean-toolchain").read_text().strip()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    jsonl = output if output.suffix == ".jsonl" else output.with_suffix(".jsonl")
    subprocess.run(
        ["lake", "env", "lean", "--run", str(ROOT / "deploy/lean/Extract.lean"), str(jsonl), *args.prefixes],
        cwd=project, check=True, env=dict(os.environ, LEAN_ABORT_ON_PANIC="1"),
    )
    meta = {"mathlib": PINS["mathlib"], "lean": toolchain, "prefixes": args.prefixes,
            "note": "Declaration/dependency export from the pinned mathlib; not a proof audit."}
    if output.suffix == ".jsonl":
        with open(jsonl) as f:
            count = sum(1 for line in f if line.strip())
        Path(str(jsonl) + ".meta.json").write_text(json.dumps(dict(meta, declarations=count), indent=1))
    else:
        declarations = []
        with open(jsonl) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    d["source_url"] = source_url(d)
                    declarations.append(d)
        declarations.sort(key=lambda d: d["name"])
        count = len(declarations)
        output.write_text(json.dumps(dict(meta, declarations=declarations), ensure_ascii=False))
    print(json.dumps({"declarations": count, "output": str(output)}))


if __name__ == "__main__":
    main()
