"""Read literal KEY=value records. No shell, substitution, expansion or value logging."""
import argparse
import os
from pathlib import Path
import re
import subprocess


def load_private_env(path, environ=None):
    target = os.environ if environ is None else environ
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        if not match:
            raise ValueError(f'Invalid env record at line {number}')
        key, value = match.groups()
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Invalid quoted env record at line {number}')
            value = value[1:-1]
        elif any(c.isspace() for c in value):
            raise ValueError(f'Unquoted whitespace at line {number}')
        if key in values:
            raise ValueError(f'Duplicate env key at line {number}')
        values[key] = value
    target.update(values)
    return len(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('env_file')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        load_private_env(args.env_file)
        if not args.command:
            parser.error('Supply an argv command; env values are never printed')
        return subprocess.call(args.command, shell=False)
    except Exception as exc:
        print('Private environment load/launch failed: ' + type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
