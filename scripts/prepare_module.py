#!/usr/bin/env python3
"""Validate offline by default; explicitly vectorize/import using an existing budgeted run.
Run as python -m scripts.prepare_module corpus/number-theory.json.
No provider config or credentials are read in the default offline path.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from metis.base import import_module


def vectorize(bundle, vectors, providers, run, dimensions=1024):
    result = copy.deepcopy(bundle)
    texts = [n['name'] + '\n' + n['statement'] for n in result['concepts']]
    digest = hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()
    response = vectors.embed(texts, run, providers, 'base-module:' + bundle['module']['id'] + ':' + digest)
    embeddings = response['embeddings']
    if len(embeddings) != len(texts):
        raise ValueError('Embedding count mismatch')
    for node, vector in zip(result['concepts'], embeddings):
        if (not isinstance(vector, list) or len(vector) != dimensions
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in vector)
                or not any(vector)):
            raise ValueError('Invalid embedding dimensions or values')
        node['embedding'] = vector
    result['module']['embedding'] = {
        'dimensions': dimensions, 'text_sha256': digest,
        'provider': providers.public().get('embeddings'),
    }
    return result


def validate(bundle):
    # Run the real importer against an ephemeral store, without touching deployment data.
    from tempfile import TemporaryDirectory
    from metis.config import Config
    from metis.store import Store
    with TemporaryDirectory() as directory:
        store = Store(Config(mode="fixture", sqlite_path=str(Path(directory) / 'validation.sqlite')))
        try:
            import_module(store, copy.deepcopy(bundle))
        finally:
            store.mongo.client.close() if store.mongo is not None else store.sql.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--execute', action='store_true', help='Enable billed embedding and database import')
    parser.add_argument('--run-id', help='Existing approved live run supplies journey/run budget accounts')
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle).read_text())
    validate(bundle)
    if not args.execute:
        print(json.dumps({'module': bundle['module']['id'], 'concepts': len(bundle['concepts']),
                          'paid_calls': 0, 'action': 'validated only; no import or embedding'}))
        return
    if not args.run_id:
        parser.error('--execute requires --run-id (existing budgeted live run)')
    from metis.config import Config
    from metis.store import Store
    from metis.providers import Providers, AtlasVectors
    config = Config().validate()
    if config.mode != 'live' or not config.allow_live or config.live_budget <= 0:
        parser.error('Explicit live mode, enabled providers and positive global budget required')
    store = Store(config)
    try:
        if store.get('modules', bundle['module']['id']):
            raise ValueError('Module version already exists')
        run = store.get('runs', args.run_id)
        if not run or not store.get('journeys', run['journey_id']):
            raise ValueError('Existing run and journey budget accounts required')
        prepared = vectorize(bundle, AtlasVectors(store), Providers(store, config), run)
        print(json.dumps(import_module(store, prepared), indent=2))
    finally:
        store.mongo.client.close() if store.mongo is not None else store.sql.close()


if __name__ == '__main__':
    main()
