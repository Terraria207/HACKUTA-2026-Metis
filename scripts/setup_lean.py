#!/usr/bin/env python3
"""Prepare the exact mathlib checkout and cached oleans. Run in a managed terminal.
Requires git and elan/lake on PATH. Downloads upstream code/cache, no model API calls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'deploy/lean/pins.json').read_text(encoding="utf-8"))


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    if not project.exists():
        run('git', 'clone', '--no-checkout', 'https://github.com/leanprover-community/mathlib4.git', str(project))
        run('git', 'checkout', '--detach', PINS['mathlib'], cwd=project)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip()
    if actual != PINS['mathlib']:
        raise SystemExit('Refusing a different existing mathlib checkout')
    if (project / 'lean-toolchain').read_text(encoding="utf-8").strip() != PINS['lean']:
        raise SystemExit('Lean toolchain mismatch')
    manifest = project / 'lake-manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != PINS['manifest_sha256']:
        raise SystemExit('Mathlib dependency manifest mismatch')
    run('lake', 'exe', 'cache', 'get', cwd=project)
    run('lake', 'env', 'lean', str(ROOT / 'deploy/lean/Acceptance.lean'), cwd=project)
    (project / 'METIS_MATHLIB_VERSION').write_text(PINS['mathlib'] + '\n', encoding="utf-8")
    print('Prepared and compiler-checked:', project)


if __name__ == '__main__':
    main()
