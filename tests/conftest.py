import pytest
from fastapi.testclient import TestClient
from metis.config import Config
from metis.api import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        Config(
            mode="fixture",
            sqlite_path=str(tmp_path / "test.sqlite"),
            live_budget=0,
            allow_live=False,
            import_corpus=False,  # tests import bundles explicitly; see test_base_exploration
            provider_file=str(tmp_path / "providers.json"),
            keys_file=str(tmp_path / "keys.json"),
        ),
        False,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def journey(client):
    r = client.post(
        "/api/journeys",
        json={
            "name": "Spectral journey",
            "islands": ["linear-algebra", "graph-theory", "probability"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def complete(app, limit=30):
    worker = app.state.worker
    for _ in range(limit):
        job = app.state.store.claim(worker.owner)
        if not job:
            return
        worker.work(job)
    raise AssertionError("Worker did not drain bounded queue")
