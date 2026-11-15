#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from metis.api import create_app
from metis.base import import_module

p = argparse.ArgumentParser()
p.add_argument("bundle")
a = p.parse_args()
app = create_app(start_worker=False)

print(
    json.dumps(
        import_module(app.state.store, json.loads(Path(a.bundle).read_text(encoding="utf-8"))), indent=2
    )
)
