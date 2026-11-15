#!/usr/bin/env python3
"""Validate offline by default; explicitly vectorize/import using a durable setup budget operation.
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


def vectorize(bundle, vectors, providers, run, dimensions=1024, attempt=0):
    result = copy.deepcopy(bundle)
    nodes = result['concepts'] + result.get('groups', [])
    if not nodes:
        return result  # Relation-only bridge: nothing to embed, no paid provider call.
    texts = [n['name'] + '\n' + n.get('statement', n.get('description', n['name'])) for n in nodes]
    digest = hashlib.sha256(json.dumps([texts, dimensions, providers.public().get('embeddings')], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    base_key = 'base-module:' + bundle['module']['id'] + ':' + digest
    key = base_key if attempt == 0 else base_key + ':attempt' + str(attempt)
    for previous in range(attempt):
        candidate = base_key if previous == 0 else base_key + ':attempt' + str(previous)
        ident = hashlib.sha256((run['id'] + ':' + candidate).encode()).hexdigest()
        saved = providers.store.get('calls', ident)
        if saved and saved['status'] == 'complete':
            key = candidate
            break
    response = vectors.embed(texts, run, providers, key)
    embeddings = response['embeddings']
    if len(embeddings) != len(texts):
        raise ValueError('Embedding count mismatch')
    for node, vector in zip(nodes, embeddings):
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


def validate(bundle, prerequisites=()):
    # Run the real importer against an ephemeral store, without touching deployment data.
    from tempfile import TemporaryDirectory
    from metis.config import Config
    from metis.store import Store
    with TemporaryDirectory() as directory:
        store = Store(Config(mode="fixture", sqlite_path=str(Path(directory) / 'validation.sqlite')))
        try:
            for prerequisite in prerequisites:
                import_module(store, copy.deepcopy(prerequisite))
            import_module(store, copy.deepcopy(bundle))
        finally:
            store.mongo.client.close() if store.mongo is not None else store.sql.close()


def setup_operation(store, bundle, providers, budget):
    if not math.isfinite(budget) or not 0 < budget < min(100, store.config.live_budget):
        raise ValueError('Setup cap must be positive and below the global cap')
    identity = {'bundle': bundle, 'provider': providers.public().get('embeddings'), 'budget': budget}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    operation = {'id': 'setup_' + digest, 'kind': 'module_setup',
                 'module_id': bundle['module']['id'], 'budget_usd': budget, 'fixture': False}
    store.insert('operations', operation)
    return store.get('operations', operation['id'])


def prepare(store, bundle, providers, budget, attempt=0):
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 0 <= attempt <= 10:
        raise ValueError("Setup attempt must be an integer from 0 to 10")
    old = store.get('modules', bundle['module']['id'])
    source_hash = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    if old and old.get('status') == 'ready':
        if old.get('source_bundle_sha256') != source_hash:
            raise ValueError('Published module differs; publish a new version')
        return old
    operation = setup_operation(store, bundle, providers, budget)
    from metis.providers import AtlasVectors
    prepared = vectorize(bundle, AtlasVectors(store), providers, operation, attempt=attempt)
    prepared['module']['source_bundle_sha256'] = source_hash
    prepared['module']['setup_operation_id'] = operation['id']
    published = import_module(store, prepared)
    return published


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--prerequisite', action='append', default=[], help='Bundle path for OFFLINE validation only, in prerequisite order; execute still requires published pins')
    parser.add_argument('--setup-budget', type=float, default=1)
    parser.add_argument('--setup-attempt', type=int, default=0, help='Explicit new billed attempt after an ambiguous failure')
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    validate(bundle, [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.prerequisite])
    if not args.execute:
        print(json.dumps({'module': bundle['module']['id'], 'paid_calls': 0, 'action': 'validated only'}))
        return
    from metis.config import Config
    from metis.store import Store
    from metis.providers import Providers
    config = Config().validate()
    if config.mode != 'live' or not config.allow_live or not 0 < config.live_budget <= 100:
        parser.error('Explicit live mode and global budget in (0,100] required')
    store = Store(config)
    try:
        published = prepare(store, bundle, Providers(store, config), args.setup_budget, args.setup_attempt)
        print(json.dumps({'module': published['id'], 'status': published['status']}))
    finally:
        store.mongo.client.close() if store.mongo is not None else store.sql.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'error', 'error_type': type(exc).__name__, 'message': 'Preparation stopped; no exception body logged'}))
        raise SystemExit(1) from None
