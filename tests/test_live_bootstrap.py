import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from metis.base import import_module
from metis.providers import Providers, ProviderUnavailable, BudgetExceeded
from scripts.prepare_module import prepare, setup_operation
from scripts.private_env import load_private_env
from scripts.live_acceptance import validate_plan, verify_indexes


def bundle():
    return json.loads(Path('corpus/number-theory.json').read_text())


def setup_provider(app, monkeypatch):
    config = app.state.store.config
    config.live_budget, config.allow_live = 100, True
    p = Providers(app.state.store, config)
    config.mode = 'live'  # existing offline store: never connect to Atlas in these tests
    p.roles = {'embeddings': {'provider': 'openai', 'model': 'offline-test',
        'key_env': 'TEST_EMBEDDING_KEY', 'max_cost_usd': .2,
        'input_usd_per_million': 0, 'output_usd_per_million': 0}}
    monkeypatch.setenv('TEST_EMBEDDING_KEY', 'not-a-real-credential')
    p._request = Mock(side_effect=lambda spec, secret, payload, grounded:
        {'embeddings': [[1.0] + [0.0] * 1023 for _ in payload['texts']]})
    return p


def test_first_module_setup_retry_and_global_account(app, monkeypatch):
    s = app.state.store
    p = setup_provider(app, monkeypatch)
    data = bundle()
    original = copy.deepcopy(data)
    result = prepare(s, data, p, 1)
    assert result['status'] == 'ready'
    assert prepare(s, data, p, 1) == result
    assert p._request.call_count == 1
    assert data == original
    assert not s.all('journeys') and not s.all('runs')
    operation = s.all('operations')[0]
    assert operation['kind'] == 'module_setup'
    assert s.get('budgets', 'global')['spent'] == pytest.approx(.2)
    assert s.get('budgets', 'setup:' + operation['id'])['spent'] == pytest.approx(.2)
    for collection in ('concepts', 'groups'):
        docs = s.all(collection, layer='module:' + result['id'])
        assert docs and all(len(n['embedding']) == 1024 for n in docs)
        with pytest.raises(ValueError, match='immutable'):
            s.patch(collection, docs[0]['id'], name='overwrite')
    with pytest.raises(ValueError, match='immutable'):
        s.delete('modules', result['id'])
    data['concepts'][0]['statement'] += ' altered'
    with pytest.raises(ValueError, match='differs'):
        prepare(s, data, p, 1)


def test_setup_failure_is_charged_and_not_automatically_rebilled(app, monkeypatch):
    s = app.state.store
    p = setup_provider(app, monkeypatch)
    p._request = Mock(side_effect=RuntimeError('secret URI and headers must not escape'))
    for _ in range(2):
        with pytest.raises(ProviderUnavailable) as caught:
            prepare(s, bundle(), p, 1)
        assert 'secret URI' not in str(caught.value)
    assert p._request.call_count == 1
    assert s.get('budgets', 'global')['spent'] == pytest.approx(.2)
    assert not s.get('modules', bundle()['module']['id'])


def test_setup_caps_and_durable_identity(app, monkeypatch):
    s = app.state.store
    p = setup_provider(app, monkeypatch)
    run = setup_operation(s, bundle(), p, .1)
    with pytest.raises(BudgetExceeded):
        p.call('embeddings', {'texts': ['x']}, run, 'cap')
    assert not p._request.called
    assert s.get('budgets', 'global')['reserved'] == 0
    with pytest.raises(ProviderUnavailable, match='durable'):
        p.call('embeddings', {'texts': ['x']}, dict(run, budget_usd=99), 'tampered')
    with pytest.raises(ValueError):
        setup_operation(s, bundle(), p, 100)


def test_interrupted_publication_resumes_identical_bundle(app, monkeypatch):
    s = app.state.store
    data = bundle()
    original = s.put
    def fail(collection, doc):
        if collection == 'concepts':
            raise OSError('simulated crash')
        return original(collection, doc)
    monkeypatch.setattr(s, 'put', fail)
    with pytest.raises(OSError):
        import_module(s, copy.deepcopy(data))
    assert s.get('modules', data['module']['id'])['status'] == 'building'
    monkeypatch.setattr(s, 'put', original)
    assert import_module(s, copy.deepcopy(data))['status'] == 'ready'
    with pytest.raises(ValueError, match='already exists'):
        import_module(s, copy.deepcopy(data))


def test_env_is_literal_atomic_and_never_executes(tmp_path):
    marker = tmp_path / 'executed'
    env = tmp_path / 'private.env'
    env.write_text(f"export TOKEN='$(touch {marker})'\nURI=mongodb://example/a#fragment\n")
    target = {}
    assert load_private_env(env, target) == 2
    assert target['TOKEN'] == f'$(touch {marker})'
    assert target['URI'].endswith('#fragment') and not marker.exists()
    env.write_text('TOKEN=ok\nsource malicious\n')
    target = {}
    with pytest.raises(ValueError):
        load_private_env(env, target)
    assert not target


def test_index_preflight_checks_both_dimensions_and_filter():
    from types import SimpleNamespace
    definition = json.loads(Path('deploy/atlas-vector-index.json').read_text())
    collection = Mock()
    collection.list_search_indexes.return_value = [{'queryable': True, 'latestDefinition': definition}]
    store = SimpleNamespace(mongo={'concepts': collection, 'groups': collection})
    assert set(verify_indexes(store)) == {'concepts', 'groups'}
    assert collection.list_search_indexes.call_count == 2
    definition['fields'][0]['numDimensions'] = 3
    with pytest.raises(ValueError, match='definition mismatch'):
        verify_indexes(store)


def test_plan_rejects_overspend_and_missing_explicit_prices(tmp_path):
    plan = {'global_budget_usd': 101, 'setup_budget_usd': 1,
            'run_budget_usd': 5, 'timeout_seconds': 300}
    with pytest.raises(ValueError, match='100'):
        validate_plan(plan)
    plan['global_budget_usd'] = 100
    path = tmp_path / 'providers.json'
    plan['providers_file'] = str(path)
    path.write_text('{}')
    with pytest.raises(ValueError, match='every pipeline role'):
        validate_plan(plan)


def test_openai_embedding_adapter_uses_embedding_endpoint(monkeypatch, app):
    p = Providers(app.state.store, app.state.store.config)
    response = Mock()
    response.json.return_value = {'data': [{'index': 1, 'embedding': [0, 1]}, {'index': 0, 'embedding': [1, 0]}]}
    client = Mock()
    client.post.return_value = response
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('metis.providers.httpx.Client', Mock(return_value=context))
    result = p._request({'provider': 'openai', 'model': 'offline'}, 'fake', {'texts': ['a', 'b']}, False)
    assert result['embeddings'] == [[1, 0], [0, 1]]
    assert client.post.call_args.args[0] == 'https://api.openai.com/v1/embeddings'
    assert client.post.call_args.kwargs['json']['dimensions'] == 1024


def test_explicit_setup_retry_stays_in_same_account(app, monkeypatch):
    s = app.state.store
    p = setup_provider(app, monkeypatch)
    success = p._request.side_effect
    p._request.side_effect = TimeoutError('ambiguous')
    with pytest.raises(ProviderUnavailable):
        prepare(s, bundle(), p, 1)
    p._request.side_effect = success
    assert prepare(s, bundle(), p, 1, attempt=1)['status'] == 'ready'
    assert len(s.all('operations')) == 1
    assert len(s.all('calls')) == 2
    assert s.get('budgets', 'global')['spent'] == pytest.approx(.4)
    assert s.get('budgets', 'setup:' + s.all('operations')[0]['id'])['spent'] == pytest.approx(.4)


def test_offline_cli_never_loads_private_env_or_executes(tmp_path, monkeypatch, capsys):
    from scripts import live_acceptance
    from metis.providers import ROLES
    providers = {role: {'provider': 'openai', 'model': 'offline-test',
                 'key_env': 'MISSING_TEST_KEY', 'max_cost_usd': .2,
                 'input_usd_per_million': 0, 'output_usd_per_million': 0}
                 for role in ROLES}
    providers['tiresias'].update(provider='gemini', request_overhead_usd=0)
    specs = tmp_path / 'providers.json'
    specs.write_text(json.dumps(providers))
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'global_budget_usd': 100, 'setup_budget_usd': 1,
        'run_budget_usd': 5, 'timeout_seconds': 300, 'providers_file': str(specs),
        'bundle': 'corpus/number-theory.json'}))
    monkeypatch.setattr('sys.argv', ['live_acceptance', 'acceptance', '--config', str(plan),
                                  '--env-file', '/must/not/read'])
    monkeypatch.setattr(live_acceptance, 'execute', Mock(side_effect=AssertionError('live execution forbidden')))
    assert live_acceptance.main() == 0
    assert json.loads(capsys.readouterr().out)['paid_calls'] == 0
    assert not live_acceptance.execute.called


def test_deadline_pauses_before_another_call(app, monkeypatch):
    from metis.pipeline import Interrupted
    s = app.state.store
    s.put('runs', {'id': 'deadline-test', 'journey_id': 'none', 'status': 'running', 'deadline_at': 1})
    provider = Mock()
    app.state.worker.providers = provider
    with pytest.raises(Interrupted, match='deadline'):
        app.state.worker.call('crew0', {}, s.get('runs', 'deadline-test'), 'never')
    assert not provider.call.called
    assert s.get('runs', 'deadline-test')['status'] == 'paused'


def test_no_accepted_findings_never_invokes_summary_model(app, client, journey, monkeypatch):
    from test_api import paper, run
    r = run(client, journey, paper(client, journey))
    s = app.state.store
    s.patch('runs', r['id'], fixture=False)
    w = app.state.worker
    monkeypatch.setattr(w, 'call', Mock(side_effect=AssertionError('No summary call for empty findings')))
    monkeypatch.setattr('metis.concepts.consider', Mock(return_value=[]))
    w.stage6(s.get('runs', r['id']))
    report = s.get('reports', r['id'])
    assert not report['ranked'] and not report['potentially_new']
    assert 'No accepted exploration findings' in report['summary']


def test_acceptance_cli_drives_actual_seven_stages_with_mocked_network(tmp_path, monkeypatch):
    from metis.config import Config
    from metis.store import Store
    from metis.providers import ROLES
    from scripts.live_acceptance import execute
    database = str(tmp_path / 'acceptance.sqlite')
    def offline_store(config):
        return Store(Config(mode='fixture', sqlite_path=database, live_budget=100))
    monkeypatch.setattr('metis.store.Store', offline_store)
    monkeypatch.setattr('metis.api.Store', offline_store)
    monkeypatch.setattr('scripts.live_acceptance.verify_indexes', lambda store: {'concepts': 'queryable', 'groups': 'queryable'})
    monkeypatch.setattr('metis.ingestion.pdf_text', lambda raw: 'Conditional Collatz and S-units acceptance paper with no proposed discoveries.')
    monkeypatch.setenv('MONGODB_URI', 'not-used-by-mocked-store')
    monkeypatch.setenv('OFFLINE_TEST_KEY', 'fake-never-sent')
    specs = {role: {'provider': 'openai', 'model': role, 'key_env': 'OFFLINE_TEST_KEY',
            'max_cost_usd': .01, 'input_usd_per_million': 0, 'output_usd_per_million': 0}
            for role in ROLES}
    specs['tiresias'].update(provider='gemini', request_overhead_usd=0)
    provider_path = tmp_path / 'providers.json'
    provider_path.write_text(json.dumps(specs))
    def request(self, spec, secret, payload, grounded):
        if spec['model'] == 'embeddings':
            return {'embeddings': [[1.] + [0.] * 1023 for _ in payload['texts']]}
        if spec['model'] == 'decomposer':
            return {'concepts': [], 'edges': [], 'msc_codes': []}
        assert spec['model'].startswith('crew')
        return {'proposals': []}
    monkeypatch.setattr(Providers, '_request', request)
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(b'%PDF-offline-boundary-test')
    plan = {'global_budget_usd': 100, 'setup_budget_usd': 1, 'run_budget_usd': 5,
            'timeout_seconds': 30, 'providers_file': str(provider_path),
            'bundle': 'corpus/number-theory.json', 'pdf': str(pdf),
            'home_group': bundle()['groups'][2]['id']}
    events = []
    assert execute(plan, 'acceptance', events.append) == 0
    result = events[-1]
    assert result['checkpoint'] == 7 and result['status'] == 'complete'
    assert not result['report']['ranked'] and not result['report']['fixture']
    assert not result['discovery_claimed']
    assert any(e['phase'] == 'started' and e['run_id'] for e in events)
    verification = Store(Config(mode='fixture', sqlite_path=database))
    try:
        stages = [t['step'] for t in sorted(verification.all('trace', run_id=result['run_id']), key=lambda t: t['time'])
                  if t['summary'].startswith('Stage started:')]
        assert stages == list(range(7))
        assert verification.get('reports', result['run_id'])['summary'].startswith('No accepted exploration findings')
    finally:
        verification.sql.close()
