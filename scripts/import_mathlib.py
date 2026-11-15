#!/usr/bin/env python3
"""Convert a declaration/dependency export + reviewed MSC mapping to a module bundle.
Thin wrapper over metis.gods.build_bundle (the "by script" half of the base graph); see
scripts/build_module.py for the complete island/bridge build with selection and curation.
Export schema: [{name, kind, module, line, type, docstring, dependencies:[name], source_url}].
MSC map schema: {groups:[...], declarations:{name:{home_group,description,kind,name}}}.
This importer never promotes compiler dependencies into natural-language implications.
"""

import argparse
import json
from pathlib import Path

from metis.gods import build_bundle


def build(declarations, mapping, module_id, version, mathlib_version, islands, source):
    return build_bundle(declarations, mapping, module_id, version, mathlib_version, islands, source)


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
