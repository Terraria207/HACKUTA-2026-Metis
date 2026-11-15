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
        # Blobless clone: full commit history but only the file contents of the pinned commit
        # (about 110 MB instead of 500 MB). The -c options are stored in the clone's own config:
        # Windows paths in mathlib exceed 260 characters, and Git for Windows would otherwise
        # rewrite line endings, which changes lake-manifest.json and fails the check below.
        run('git', 'clone', '-c', 'core.longpaths=true', '-c', 'core.autocrlf=false', '--filter=blob:none',
            '--no-checkout', 'https://github.com/leanprover-community/mathlib4.git', str(project))
        run('git', 'checkout', '--detach', PINS['mathlib'], cwd=project)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip()
    if actual != PINS['mathlib']:
        raise SystemExit('Refusing a different existing mathlib checkout')
    if (project / 'lean-toolchain').read_text(encoding="utf-8").strip() != PINS['lean']:
        raise SystemExit('Lean toolchain mismatch')
    manifest = project / 'lake-manifest.json'
    # Compare with LF line endings, so a checkout made with Windows line endings still matches.
    if hashlib.sha256(manifest.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != PINS['manifest_sha256']:
        raise SystemExit('Mathlib dependency manifest mismatch')
    if (project / 'METIS_MATHLIB_VERSION').is_file():
        (project / 'METIS_MATHLIB_VERSION').unlink()  # rewritten only after the checks below pass
    run('lake', 'exe', 'cache', 'get', cwd=project)
    run('lake', 'env', 'lean', str(ROOT / 'deploy/lean/Acceptance.lean'), cwd=project)
    (project / 'METIS_MATHLIB_VERSION').write_text(PINS['mathlib'] + '\n', encoding="utf-8")
    print('Prepared and compiler-checked:', project)


if __name__ == '__main__':
    main()
