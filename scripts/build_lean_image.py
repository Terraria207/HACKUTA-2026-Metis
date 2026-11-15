#!/usr/bin/env python3
"""Package the already prepared Lean toolchain; emit a local immutable image ID.
The project/cache remains the read-only METIS_LEAN_PROJECT mount. Use a base
image by digest with compatible Linux/glibc; e.g. the same distro as the builder.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-image', required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--tag', default='metis-lean:4.19.0')
    args = parser.parse_args()
    if not re.fullmatch(r'.+@sha256:[a-f0-9]{64}', args.base_image):
        parser.error('Base image must be pinned by sha256 digest')
    pins = json.loads((ROOT / 'deploy/lean/pins.json').read_text())
    if (args.project / 'METIS_MATHLIB_VERSION').read_text().strip() != pins['mathlib']:
        parser.error('Run setup_lean.py first')
    lean = Path(subprocess.check_output(['lake', 'env', 'which', 'lean'], cwd=args.project, text=True).strip()).resolve()
    version = subprocess.check_output([str(lean), '--version'], text=True)
    if 'version 4.19.0 ' not in version:
        parser.error('Unexpected Lean toolchain')
    with tempfile.TemporaryDirectory(prefix='metis-image-') as directory:
        context = Path(directory)
        shutil.copytree(lean.parent.parent, context / 'toolchain', symlinks=True)
        shutil.copy(ROOT / 'deploy/lean/Dockerfile', context / 'Dockerfile')
        subprocess.run(['docker', 'build', '--build-arg', 'LEAN_BASE_IMAGE=' + args.base_image,
                        '-t', args.tag, str(context)], check=True)
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.tag], text=True).strip()
    # Docker accepts name@sha256:<image config digest> only for registry manifests,
    # so publish to a controlled registry and resolve RepoDigests for runtime use.
    print('Built local image:', image_id)
    print('Publish to your controlled registry; configure METIS_LEAN_IMAGE with its RepoDigest.')


if __name__ == '__main__':
    main()
