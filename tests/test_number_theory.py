import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from metis.base import import_module
from scripts.prepare_module import validate, vectorize

ROOT = Path(__file__).resolve().parents[1]


def bundle():
    return json.loads((ROOT / 'corpus/number-theory.json').read_text(encoding="utf-8"))


def test_source_backed_module_and_journey(client, app):
    data = bundle()
    validate(data)
    assert len(data['concepts']) == 6
    assert not data['edges']
    assert not data['module']['fixture']
    assert all(n['source']['location'] and n['source']['url'].startswith('https://') for n in data['concepts'])
    conditional = next(n for n in data['concepts'] if n['kind'] == 'theorem')
    assert len(conditional['hypotheses']) == 3
    assert 'divergent' in conditional['statement'] and 'bounded' in conditional['statement']
    assert not any(n.get('machine_verified') or n.get('embedding') for n in data['concepts'])
    response = client.post('/api/modules/import', json=data)
    assert response.status_code == 201, response.text
    response = client.post('/api/journeys', json={'name': 'Conditional Collatz', 'islands': ['number-theory']})
    assert response.status_code == 201, response.text
    assert response.json()['modules'] == [data['module']['id']]
    groups = app.state.store.all('groups', layer='module:' + data['module']['id'])
    assert {'11B83', '11D61'} <= {g['msc'] for g in groups}
    with pytest.raises(ValueError, match='already exists'):
        import_module(app.state.store, copy.deepcopy(data))


def test_no_fabricated_number_theory_fixture(client, app):
    response = client.post('/api/journeys', json={'name': 'Missing corpus', 'islands': ['number-theory']})
    assert response.status_code == 400
    assert not any(m['islands'] == ['number-theory'] for m in app.state.store.all('modules'))


def test_vectorization_uses_budgeted_adapter_without_mutating_source():
    data = bundle()
    vectors, providers = Mock(), Mock()
    providers.public.return_value = {'embeddings': {'provider': 'test', 'model': 'offline'}}
    vectors.embed.return_value = {'embeddings': [[1.0, 0.0]] * (len(data['concepts']) + len(data['groups']))}
    run = {'id': 'existing-budgeted-run'}
    result = vectorize(data, vectors, providers, run, dimensions=2)
    vectors.embed.assert_called_once()
    args = vectors.embed.call_args.args
    assert args[1] is run and args[2] is providers
    assert args[3].startswith('base-module:' + data['module']['id'])
    assert all(len(n['embedding']) == 2 for n in result['concepts'] + result['groups'])
    assert all('embedding' not in n for n in data['concepts'])
    vectors.embed.return_value = {'embeddings': [[float('nan'), 0]] * (len(data['concepts']) + len(data['groups']))}
    with pytest.raises(ValueError, match='Invalid embedding'):
        vectorize(data, vectors, providers, run, dimensions=2)
    vectors.embed.return_value = {'embeddings': []}
    with pytest.raises(ValueError, match='count mismatch'):
        vectorize(data, vectors, providers, run, dimensions=2)


def test_lean_dependency_pins():
    pins = json.loads((ROOT / 'deploy/lean/pins.json').read_text(encoding="utf-8"))
    manifest = (ROOT / 'deploy/lean/mathlib-manifest.json').read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == pins['manifest_sha256']
    assert pins['lean'] == 'leanprover/lean4:v4.19.0'
    assert len(pins['mathlib']) == 40
    assert all(len(p['rev']) == 40 for p in json.loads(manifest)['packages'])
