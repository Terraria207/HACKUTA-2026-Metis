import io
import json
from concurrent.futures import ThreadPoolExecutor
from reportlab.pdfgen import canvas
from conftest import complete


def paper(client, j, title="Fixture paper"):
    gid = client.get(f"/api/journeys/{j['id']}/graph").json()["groups"][-1]["id"]
    r = client.post(
        f"/api/journeys/{j['id']}/papers",
        json={"title": title, "kind": "fixture", "home_group": gid},
    )
    assert r.status_code == 201, r.text
    return r.json()


def run(client, j, p, key="test"):
    r = client.post(
        f"/api/journeys/{j['id']}/runs",
        json={"paper_id": p["id"]},
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_full_pipeline_exports_and_reopen(client, app, journey):
    j = journey["id"]
    p = paper(client, journey)
    r = run(client, journey, p)
    complete(app)
    done = client.get(f"/api/journeys/{j}/runs/{r['id']}").json()
    assert done["checkpoint"] == 7 and done["status"] == "complete", done
    report = client.get(f"/api/journeys/{j}/runs/{r['id']}/report").json()
    assert report["fixture"] and not report["potentially_new"]
    assert report["unchecked"] and "not discoveries" in report["summary"]
    for fmt, kind in [
        ("json", b'"report"'),
        ("md", b"FIXTURE SIMULATION"),
        ("pdf", b"%PDF"),
    ]:
        export = client.get(f"/api/journeys/{j}/runs/{r['id']}/export/{fmt}")
        assert export.status_code == 200 and kind in export.content
    traces = client.get(f"/api/journeys/{j}/trace").json()
    assert {t["step"] for t in traces} == set(range(7))
    assert not app.state.store.all("calls")
    assert client.get("/api/discoveries").json() == []
    old = client.get(f"/api/journeys/{j}/graph?run_id={r['id']}&before=true").json()
    after = client.get(f"/api/journeys/{j}/graph").json()
    assert len(after["concepts"]) > len(old["concepts"])
    assert len(client.get(f"/api/journeys/{j}/runs").json()) == 1


def test_journey_isolation_and_cached_extraction(client, app, journey):
    p = paper(client, journey)
    r = run(client, journey, p)
    complete(app)
    other = client.post(
        "/api/journeys", json={"name": "Other", "islands": journey["islands"]}
    ).json()
    q = paper(client, other)
    s = run(client, other, q)
    complete(app)
    assert len(app.state.store.all("extractions")) == 1
    a = client.get(f"/api/journeys/{journey['id']}/graph").json()
    b = client.get(f"/api/journeys/{other['id']}/graph").json()
    own = {n["id"] for n in a["concepts"] if n["layer"].startswith("journey:")}
    assert not own.intersection(n["id"] for n in b["concepts"])
    assert client.get(f"/api/journeys/{other['id']}/runs/{r['id']}").status_code == 404
    assert (
        client.get(
            f"/api/journeys/{other['id']}/details/concept/{next(iter(own))}"
        ).status_code
        == 404
    )
    assert app.state.store.all("modules") == app.state.store.all(
        "modules", status="ready"
    )


def test_pause_resume_cancel_retry(client, app, journey):
    p = paper(client, journey)
    r = run(client, journey, p)
    base = f"/api/journeys/{journey['id']}/runs/{r['id']}"
    assert client.post(base + "/pause").json()["status"] == "paused"
    complete(app)
    assert client.get(base).json()["checkpoint"] == 0
    assert client.post(base + "/resume").status_code == 200
    complete(app)
    assert client.get(base).json()["status"] == "complete"
    r = run(client, journey, p, "next")
    base = f"/api/journeys/{journey['id']}/runs/{r['id']}"
    client.post(base + "/cancel")
    complete(app)
    assert client.get(base).json()["status"] == "cancelled"
    assert client.post(base + "/resume").status_code == 409


def test_idempotent_start_and_checkpoint_replay(client, app, journey):
    p = paper(client, journey)
    r = run(client, journey, p)
    assert run(client, journey, p)["id"] == r["id"]
    worker = app.state.worker
    job = app.state.store.claim(worker.owner)
    worker.stage0(r)
    initial = app.state.store.all("support")
    worker.stage0(r)
    assert app.state.store.all("support") == initial
    worker.work(job)
    complete(app)
    total = len(app.state.store.all("support"))
    worker.stage2(app.state.store.get("runs", r["id"]))
    assert len(app.state.store.all("support")) == total


def test_feedback_invalidates_and_independent_rereview(client, app, journey):
    p = paper(client, journey)
    r = run(client, journey, p)
    complete(app)
    j = journey["id"]
    e = app.state.worker.run_edges(r)[0]
    f = client.post(
        f"/api/journeys/{j}/feedback", json={"target_id": e["id"], "mark": "wrong"}
    ).json()
    assert app.state.store.get("edges", e["id"])["invalidated"]
    q = client.get(f"/api/journeys/{j}/rechecks").json()
    assert q[0]["status"] == "queued"
    res = client.post(f"/api/journeys/{j}/rechecks/{f['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "queued"
    complete(app)
    assert app.state.store.get("rechecks", f["id"])["status"] == "complete"
    assert not app.state.store.get("edges", e["id"])["invalidated"]


def test_placement_upload_and_reject_bad_input(client, journey):
    gid = client.get(f"/api/journeys/{journey['id']}/graph").json()["groups"][-1]["id"]
    base = f"/api/journeys/{journey['id']}/papers"
    assert (
        client.post(
            base,
            json={"title": "bad", "kind": "text", "value": "short", "home_group": gid},
        ).status_code
        == 400
    )
    assert (
        client.post(
            base,
            json={
                "title": "bad",
                "kind": "url",
                "value": "http://127.0.0.1/",
                "home_group": gid,
            },
        ).status_code
        == 400
    )
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(
        50, 700, "A mathematical paper with enough text to extract for a fixture test."
    )
    c.save()
    r = client.post(
        base + "/pdf",
        data={"title": "PDF paper", "home_group": gid},
        files={"file": ("paper.pdf", buf.getvalue(), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"]["kind"] == "pdf"
    assert (
        client.post(
            base + "/pdf",
            data={"title": "PDF", "home_group": gid},
            files={"file": ("x.pdf", b"wrong", "application/pdf")},
        ).status_code
        == 400
    )


def test_invalid_settings_and_csrf(client, journey):
    assert (
        client.put(
            f"/api/journeys/{journey['id']}/settings", json={"d_max": 0}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/journeys",
            headers={"Origin": "https://evil.test"},
            json={"name": "x", "islands": ["probability"]},
        ).status_code
        == 403
    )
    assert (
        client.get("/")
        .headers["content-security-policy"]
        .startswith("default-src 'self'")
    )
    assert client.get("/static/app.js").status_code == 200


def test_live_fail_closed(tmp_path):
    import pytest
    from metis.config import Config
    from metis.api import create_app

    with pytest.raises(RuntimeError, match="MONGODB_URI"):
        create_app(Config(mode="live", mongo_uri=""), False)


def test_api_token(tmp_path):
    from fastapi.testclient import TestClient
    from metis.api import create_app
    from metis.config import Config

    c = TestClient(
        create_app(
            Config(
                mode="fixture",
                sqlite_path=str(tmp_path / "auth.sqlite"),
                api_token="secret",
            ),
            False,
        )
    )
    assert c.get("/api/status").status_code == 401
    assert (
        c.get("/api/status", headers={"Authorization": "Bearer secret"}).status_code
        == 200
    )


def test_corpus_only_search_and_suggestions(client, app, journey):
    j = journey["id"]
    p = paper(client, journey)
    assert client.get(f"/api/journeys/{j}/suggestions").json()[0]["id"] == p["id"]
    r = client.post(
        f"/api/journeys/{j}/runs", json={"paper_id": p["id"], "ingest_only": True}
    ).json()
    complete(app)
    assert app.state.store.get("runs", r["id"])["status"] == "complete"
    assert not app.state.store.get("runs", r["id"])["targets"]
    assert app.state.store.get("papers", p["id"])["concept_ids"]
    result = client.post(
        f"/api/journeys/{j}/search/semantic", json={"query": "spectral"}
    ).json()
    assert result["fixture"] and "lexical" in result["notice"] and result["results"]
    assert not app.state.store.all("calls")
