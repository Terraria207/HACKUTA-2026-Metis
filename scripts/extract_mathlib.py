#!/usr/bin/env python3
"""Run the Lean declaration export inside the pinned mathlib project and write an export file.

  python scripts/extract_mathlib.py --project /abs/mathlib --prefixes Mathlib.LinearAlgebra \
      --output .lean/exports/linear-algebra.json

Requires the project prepared by scripts/setup_lean.py (METIS_MATHLIB_VERSION present) and lake on
PATH. Importing all of Mathlib takes minutes and several GB of memory. No model or network is used.
The export records the mathlib commit, the Lean toolchain and a GitHub source URL per declaration.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / "deploy/lean/pins.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--prefixes", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    marker = project / "METIS_MATHLIB_VERSION"
    if not marker.is_file() or marker.read_text().strip() != PINS["mathlib"]:
        raise SystemExit("Prepared pinned mathlib project required (run scripts/setup_lean.py)")
    toolchain = (project / "lean-toolchain").read_text().strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    jsonl = args.output.with_suffix(".jsonl")
    subprocess.run(
        ["lake", "env", "lean", "--run", str(ROOT / "deploy/lean/Extract.lean"), str(jsonl), *args.prefixes],
        cwd=project, check=True, env=dict(os.environ, LEAN_ABORT_ON_PANIC="1"),
    )
    declarations = []
    with open(jsonl) as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                path = d["module"].replace(".", "/") + ".lean"
                d["source_url"] = (
                    "https://github.com/leanprover-community/mathlib4/blob/" + PINS["mathlib"] + "/" + path
                    + ("#L%d" % d["line"] if d.get("line") else "")
                )
                declarations.append(d)
    declarations.sort(key=lambda d: d["name"])
    export = {
        "mathlib": PINS["mathlib"],
        "lean": toolchain,
        "prefixes": args.prefixes,
        "declarations": declarations,
        "note": "Declaration/dependency export from the pinned mathlib; not a proof audit.",
    }
    args.output.write_text(json.dumps(export, ensure_ascii=False))
    print(json.dumps({"declarations": len(declarations), "output": str(args.output)}))


if __name__ == "__main__":
    main()
