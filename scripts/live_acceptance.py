"""Offline by default. --execute enables live preflight or bounded paid acceptance.
All models and prices must be supplied in a parent-owned provider JSON file.
"""
import argparse
import json
import math
import os
from pathlib import Path
import time


def validate_plan(plan):
    for key in ('global_budget_usd', 'setup_budget_usd', 'run_budget_usd', 'timeout_seconds'):
        value = plan[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid positive bound: ' + key)
    if not plan['global_budget_usd'] <= 100:
        raise ValueError('Global cap exceeds authorized $100')
    if not max(plan['setup_budget_usd'], plan['run_budget_usd']) < plan['global_budget_usd']:
        raise ValueError('Setup and run caps must be smaller than global cap')
    if plan['timeout_seconds'] > 3600:
        raise ValueError('Acceptance deadline exceeds one hour')
    from metis.api import RoleSpec
    from metis.providers import ROLES
    specs = json.loads(Path(plan['providers_file']).read_text(encoding="utf-8"))
    if set(specs) != set(ROLES):
        raise ValueError('Explicit provider specification required for every pipeline role')
    for role, raw in specs.items():
        spec = RoleSpec.model_validate(raw)
        if spec.max_cost_usd <= 0 or spec.input_usd_per_million is None or spec.output_usd_per_million is None:
            raise ValueError('Explicit prices and positive maximum charge required for ' + role)
        if role == 'embeddings' and spec.provider not in ('openai', 'voyage'):
            raise ValueError('Embeddings require OpenAI or Voyage')
        if role == 'tiresias' and (spec.provider != 'gemini' or spec.request_overhead_usd is None):
            raise ValueError('Literature requires Gemini with explicit search overhead')
    return specs


def verify_indexes(store):
    result = {}
    for collection in ('concepts', 'groups'):
        name = os.getenv('METIS_ATLAS_' + collection.upper() + '_INDEX', 'metis_' + collection)
        indexes = list(store.mongo[collection].list_search_indexes(name))
        if not indexes or not indexes[0].get('queryable'):
            raise ValueError('Vector index not queryable: ' + collection)
        definition = indexes[0].get('latestDefinition', {})
        fields = definition.get('fields', [])
        if not any(f.get('type') == 'vector' and f.get('path') == 'embedding' and f.get('numDimensions') == 1024 and f.get('similarity') == 'cosine' for f in fields):
            raise ValueError('Vector index definition mismatch: ' + collection)
        if not any(f.get('type') == 'filter' and f.get('path') == 'layer' for f in fields):
            raise ValueError('Vector layer filter missing: ' + collection)
        result[collection] = 'queryable'
    return result


def execute(plan, action, emit):
    from metis.config import Config
    from metis.store import Store
    from metis.providers import Providers
    config = Config(mode='live', mongo_uri=os.getenv('MONGODB_URI', ''),
                    mongo_db=os.getenv('MONGODB_DATABASE', 'metis'),
                    live_budget=plan['global_budget_usd'], provider_file=plan['providers_file'],
                    allow_live=True, api_token=os.getenv('METIS_API_TOKEN', ''),
                    lean_image=os.getenv('METIS_LEAN_IMAGE', ''),
                    lean_project=os.getenv('METIS_LEAN_PROJECT', '')).validate()
    store = Store(config)
    try:
        specs = validate_plan(plan)
        missing = [role for role, spec in specs.items() if not os.getenv(spec['key_env'])]
        if missing:
            raise ValueError('Missing credentials for roles: ' + ','.join(missing))
        indexes = verify_indexes(store)
        emit({'phase': 'preflight', 'indexes': indexes, 'paid_calls': 0,
              'global_budget_usd': config.live_budget})
        if action == 'preflight':
            return 0
        pdf = Path(plan['pdf'])
        if not pdf.is_file() or not 0 < pdf.stat().st_size <= 12 * 1024 * 1024:
            raise ValueError('A bounded local PDF file is required')
        with pdf.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('Local input must be PDF')
        from scripts.prepare_module import prepare
        bundle = json.loads(Path(plan['bundle']).read_text(encoding="utf-8"))
        if not any(g['id'] == plan['home_group'] and g['depth'] == 3 for g in bundle['groups']):
            raise ValueError('Home group must be a module subtopic')
        module = prepare(store, bundle, Providers(store, config), plan['setup_budget_usd'], plan.get('setup_attempt', 0))
        emit({'phase': 'module', 'module_id': module['id'], 'status': module['status'],
              'setup_operation_id': module.get('setup_operation_id')})
    finally:
        store.mongo.client.close() if store.mongo is not None else store.sql.close()
    # Exercise the same application endpoints and durable seven-stage worker as the UI.
    from metis.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(config, start_worker=False)
    worker = app.state.worker
    store = app.state.store
    deadline = time.monotonic() + plan['timeout_seconds']
    headers = {'Authorization': 'Bearer ' + config.api_token} if config.api_token else {}
    def request(client, method, path, **kwargs):
        response = getattr(client, method)(path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError('Application request failed with status ' + str(response.status_code))
        return response.json()
    try:
        with TestClient(app, headers=headers) as client:
            settings = {'k': 2, 'p': 1, 'integration_depth': 0, 'proof_attempts': 0,
                        'budget_usd': plan['run_budget_usd']}
            settings.update(plan.get('settings', {}))
            # Caller can tune breadth, but cannot widen the financial bound or bypass exploration.
            settings['budget_usd'] = plan['run_budget_usd']
            j = request(client, 'post', '/api/journeys', json={
                'name': plan.get('name', 'Bounded live acceptance'), 'islands': module['islands'],
                'modules': [module['id']], 'settings': settings})
            jid = j['id']
            emit({'phase': 'journey', 'journey_id': jid})
            with open(plan['pdf'], 'rb') as pdf:
                p = request(client, 'post', f'/api/journeys/{jid}/papers/pdf',
                            data={'title': plan.get('title', 'Live acceptance paper'),
                                  'home_group': plan['home_group']},
                            files={'file': ('paper.pdf', pdf, 'application/pdf')})
            run = request(client, 'post', f'/api/journeys/{jid}/runs',
                          json={'paper_id': p['id'], 'budget_usd': plan['run_budget_usd'], 'ingest_only': False})
            rid = run['id']
            store.patch('runs', rid, deadline_at=time.time() + max(0, deadline - time.monotonic()))
            emit({'phase': 'started', 'journey_id': jid, 'paper_id': p['id'], 'run_id': rid})
            while time.monotonic() < deadline:
                run = store.get('runs', rid)
                if run['status'] in ('complete', 'failed', 'paused', 'cancelled'):
                    break
                job = store.claim(worker.owner)
                if job:
                    worker.work(job)
                else:
                    time.sleep(.1)
            else:
                store.transition_run(rid, ('queued', 'running'), status='paused', pause_reason='acceptance_deadline')
                store.patch('journeys', jid, status='paused')
            run = store.get('runs', rid)
            report = store.get('reports', rid)
            emit({'phase': 'result', 'journey_id': jid, 'run_id': rid,
                  'status': run['status'], 'checkpoint': run['checkpoint'],
                  'sanitized_error': 'Run stopped; inspect durable status/trace' if run.get('error') else None,
                  'report': {k: report[k] for k in ('ranked', 'potentially_new', 'rediscoveries', 'unchecked', 'fixture')} if report else None,
                  'discovery_claimed': False,
                  'budget': store.get('budgets', 'global')})
            return 0 if run['status'] == 'complete' and run['checkpoint'] == 7 and report else 2
    finally:
        worker.close()
        store.mongo.client.close() if store.mongo is not None else store.sql.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'acceptance'))
    parser.add_argument('--config', required=True, help='Parent-owned JSON plan with explicit provider file and prices')
    parser.add_argument('--env-file', help='Private literal env file; never executed as shell')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    emit = lambda value: print(json.dumps(value), flush=True)
    try:
        plan = json.loads(Path(args.config).read_text(encoding="utf-8"))
        validate_plan(plan)
        from scripts.prepare_module import validate
        validate(json.loads(Path(plan['bundle']).read_text(encoding="utf-8")))
        if not args.execute:
            emit({'action': args.action, 'execute': False, 'paid_calls': 0, 'status': 'offline plan validated'})
            return 0
        if args.env_file:
            from scripts.private_env import load_private_env
            load_private_env(args.env_file)
        return execute(plan, args.action, emit)
    except Exception as exc:
        # Exception strings can include Mongo URIs, HTTP headers or provider response text.
        emit({'status': 'error', 'error_type': type(exc).__name__,
              'message': 'Acceptance stopped; inspect configuration and durable run status. No exception body logged.'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
