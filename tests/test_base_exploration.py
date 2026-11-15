import copy
import json
from pathlib import Path
import pytest
from metis.base import import_module
from metis.graph import graph, proof_closure, score, Settings
from scripts.prepare_module import validate


def bundle(name):
    return json.loads(Path('corpus/' + name + '.json').read_text(encoding="utf-8"))


def test_all_starters_validate_offline_and_have_real_relations(app):
    store = app.state.store
    old = bundle('number-theory')
    import_module(store, old)
    for field in ('linear-algebra', 'graph-theory', 'probability', 'number-theory'):
        b = bundle(field + '-starter')
        validate(b, [old] if field == 'number-theory' else [])
        assert 10 <= len(b['concepts']) <= 20
        assert len(b['edges']) >= 6
        assert all('embedding' not in n and n['source']['location'] for n in b['concepts'])
        assert all(e['tier'] == 'cited' and e['evidence'][0]['reviewed'] for e in b['edges'])
        import_module(store, b)
    bridge = bundle('markov-bridge')
    validate(bridge, [bundle('linear-algebra-starter'), bundle('probability-starter')])
    import_module(store, bridge)
    assert not store.all('calls')
    assert store.get('modules', old['module']['id'])['id'] == old['module']['id']


def test_catalog_distinguishes_deployment_inventory(client, app):
    fields = client.get('/api/catalog').json()['fields']
    nt = next(f for f in fields if f['id'] == 'number-theory')
    assert not nt['ready'] and nt['modules'] == []
    import_module(app.state.store, bundle('number-theory'))
    nt = next(f for f in client.get('/api/catalog').json()['fields'] if f['id'] == 'number-theory')
    m = nt['modules'][0]
    assert nt['ready'] and m['counts']['concepts'] == 6 and m['counts']['edges'] == 0
    assert not m['fixture'] and m['version'] and m['source'] and m['coverage']


def test_explicit_addition_preserves_pins_and_snapshots(client, app, journey):
    from test_api import paper, run
    from conftest import complete
    store = app.state.store
    p = paper(client, journey)
    r = run(client, journey, p)
    path = f"/api/journeys/{journey['id']}/modules"
    import_module(store, bundle('number-theory'))
    mid = bundle('number-theory')['module']['id']
    assert client.post(path, json={'modules': [mid]}).status_code == 409
    snapshot = copy.deepcopy(store.get('snapshots', r['id']))
    complete(app)
    added = client.post(path, json={'modules': [mid]})
    assert added.status_code == 200, added.text
    j = added.json()
    assert j['modules'] == journey['modules'] + [mid]
    assert j['module_history'][0]['before'] == journey['modules']
    assert store.get('snapshots', r['id']) == snapshot
    assert client.post(path, json={'modules': [mid]}).status_code == 400
    assert client.post(path, json={'modules': []}).status_code == 400
    import_module(store, bundle('linear-algebra-starter'))
    assert client.post(path, json={'modules': [bundle('linear-algebra-starter')['module']['id']]}).status_code == 400
    assert store.get('journeys', j['id'])['modules'] == j['modules']
    import_module(store, bundle('number-theory-starter'))
    assert client.post(path, json={'modules': [bundle('number-theory-starter')['module']['id']]}).status_code == 200


def test_exact_prerequisites_and_live_fixture_rejection(app):
    from metis.base import validate_selection
    store = app.state.store
    for f in ('linear-algebra', 'probability'):
        import_module(store, bundle(f + '-starter'))
    import_module(store, bundle('markov-bridge'))
    mids = [bundle(f)['module']['id'] for f in ('linear-algebra-starter', 'probability-starter', 'markov-bridge')]
    validate_selection(store, mids, ['linear-algebra', 'probability'], True)
    with pytest.raises(ValueError):
        validate_selection(store, mids[1:], ['linear-algebra', 'probability'], True)
    with pytest.raises(ValueError):
        validate_selection(store, ['linear-algebra@fixture-1'], ['linear-algebra'], True)


def test_graph_inventory_and_non_evidence_filters(client, app, journey):
    store = app.state.store
    g = graph(store, journey)
    a,b = g['concepts'][:2]
    e = dict(id='rejected-demo', layer='journey:' + journey['id'], premises=[a['id']], conclusion=b['id'],
             directed=True, type='implies', tier='cited', argument='Rejected test', review_status='rejected', existing='Unchecked')
    store.put('edges', e)
    path = f"/api/journeys/{journey['id']}/graph"
    default = client.get(path).json()
    assert default['edges'] == [] and default['inventory']['rejected'] == 1
    assert default['inventory']['accepted'] == 0
    assert client.get(path + '?include_rejected=true').json()['edges'][0]['id'] == e['id']
    assert client.get(path + '?layer=module&include_rejected=true').json()['edges'] == []
    nodes = {n['id']: n for n in g['concepts']}
    assert b['id'] not in proof_closure([a['id']], nodes, [e])
    assert score(e, nodes, [e], Settings().model_dump())['value'] is None
    store.patch('edges', e['id'], review_status='pending')
    assert client.get(path).json()['edges'] == []
    assert client.get(path + '?include_proposed=true').json()['edges']


def test_relation_only_bridge_never_embeds():
    from scripts.prepare_module import vectorize
    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError('Relation-only module must not call a provider')
    b = bundle('markov-bridge')
    assert vectorize(b, NoCalls(), NoCalls(), {}) == b


def test_curated_hyperedges_require_all_conditions_and_bridge_is_descriptive(app):
    store = app.state.store
    la = bundle('linear-algebra-starter')
    import_module(store, la)
    mid = la['module']['id']
    nodes = {n['id']: n for n in graph(store, {'id':'test', 'modules':[mid]})['concepts']}
    edges = store.all('edges', layer='module:' + mid)
    assert mid+':basis' not in proof_closure([mid+':independent'], nodes, edges)
    assert mid+':basis' in proof_closure([mid+':independent',mid+':spanning'], nodes, edges)
    assert mid+':dimension' not in proof_closure([mid+':basis'], nodes, edges)
    assert bundle('markov-bridge')['edges'][0]['type'] == 'defined_from'
