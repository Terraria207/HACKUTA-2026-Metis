"""Crash, trust and restart regressions found during independent review."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from conftest import complete
from test_api import paper, run
from test_durability_security import live_providers
from metis.graph import graph, score, Settings
from metis.store import Store


def test_review_saved_before_edge_write_is_replayed(app, client, journey, monkeypatch):
    r = run(client, journey, paper(client, journey))
    w, s = app.state.worker, app.state.store
    w.stage0(r)
    e = w.run_edges(r)[0]
    s.patch("edges", e["id"], review_status="pending", tier="verified")
    monkeypatch.setattr(
        w, "review", Mock(side_effect=AssertionError("review already saved"))
    )
    w.stage3(r)
    assert s.get("edges", e["id"])["review_status"] == "passed"
    assert s.get("edges", e["id"])["tier"] == "intuitive"


def test_recovery_does_not_unlock_newer_active_run(app, client, journey):
    p = paper(client, journey)
    old = run(client, journey, p)
    complete(app)
    active = run(client, journey, p, "second")
    app.state.worker.recover()
    assert (
        app.state.store.get("locks", "active:" + journey["id"])["run_id"]
        == active["id"]
    )
    app.state.store.release_run_lock(journey["id"], old["id"])
    assert (
        app.state.store.get("locks", "active:" + journey["id"])["run_id"]
        == active["id"]
    )


def test_manual_retry_reuses_completed_calls_including_earlier_retry(app, monkeypatch):
    p, r = live_providers(app, monkeypatch, budget=3)
    w = app.state.worker
    w.providers = p
    p._request = Mock(return_value={"result": "saved"})
    assert w.call("penelope", {}, r, "success") == {"result": "saved"}
    w.call("penelope", {}, dict(r, attempt=1), "success")
    assert p._request.call_count == 1
    p._request.side_effect = TimeoutError("ambiguous")
    with pytest.raises(TimeoutError):
        w.call("penelope", {}, r, "partial")
    p._request.side_effect = None
    w.call("penelope", {}, dict(r, attempt=1), "partial")
    w.call("penelope", {}, dict(r, attempt=2), "partial")
    assert p._request.call_count == 3
    assert app.state.store.get("budgets", "global")["spent"] == pytest.approx(0.6)


def test_budget_atomic_across_independent_store_connections(app):
    stores = [Store(app.state.store.config) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda i: stores[i % 8].reserve("shared", 1, 0.1), range(40))
        )
    assert sum(results) == 10
    assert stores[0].get("budgets", "shared")["reserved"] == pytest.approx(1)


def test_invalid_endpoint_disappears_from_reports_exports_discovery(
    app, client, journey
):
    r = run(client, journey, paper(client, journey))
    complete(app)
    s = app.state.store
    report = s.get("reports", r["id"])
    e = s.get("edges", report["ranked"][0])
    s.patch("edges", e["id"], existing="Not found")
    s.patch("reports", r["id"], potentially_new=[e["id"]])
    assert client.get("/api/discoveries").json()
    client.post(
        f"/api/journeys/{journey['id']}/feedback",
        json={"target_id": e["conclusion"], "target_type": "concept", "mark": "wrong"},
    )
    data = client.get(f"/api/journeys/{journey['id']}/runs/{r['id']}/report").json()
    assert e["id"] not in [x["id"] for x in data["ranked"]]
    assert client.get("/api/discoveries").json() == []
    exported = client.get(
        f"/api/journeys/{journey['id']}/runs/{r['id']}/export/json"
    ).json()
    assert e["id"] not in [x["id"] for x in exported["report"]["ranked"]]


def test_score_does_not_use_integration_created_only_by_candidate():
    nodes = {
        n: dict(
            id=n,
            ancestors=["a", "b", "c"],
            status="Established",
            embedding=[1, 0],
            integrated=True,
        )
        for n in "AB"
    }
    e = dict(
        id="e",
        premises=["A"],
        conclusion="B",
        directed=True,
        type="implies",
        tier="cited",
        review_status="passed",
    )
    result = score(e, nodes, [e], Settings().model_dump())
    assert result["pairs"][0]["tree_only"]
    assert result["value"] == 0


def test_literature_cannot_downgrade_machine_proof_or_assert_unvalidated_existing(
    app, client, journey, monkeypatch
):
    r = run(client, journey, paper(client, journey))
    complete(app)
    w, s = app.state.worker, app.state.store
    e = w.run_edges(r)[0]
    r["fixture"] = False
    result = dict(
        found=True,
        sources=[dict(url="https://example.org", location="1", excerpt="result")],
        _search_complete=True,
        _grounding={"groundingChunks": [{"web": {"uri": "https://example.org"}}]},
    )
    monkeypatch.setattr(w, "call", lambda *a, **kw: result)
    monkeypatch.setattr(w, "review", lambda *a: (True, "cited", {}, {}))
    s.patch("edges", e["id"], tier="verified")
    w.stage5(r)
    assert s.get("edges", e["id"])["tier"] == "verified"
    monkeypatch.setattr(w, "review", lambda *a: (True, "intuitive", {}, {}))
    w.stage5(r)
    assert s.get("edges", e["id"])["existing"] == "Unchecked"


def test_msc_import_is_bounded_deduplicated_and_preserves_placement(
    app, client, journey
):
    p = paper(client, journey)
    other = client.post(
        "/api/journeys", json={"name": "Other", "islands": journey["islands"]}
    ).json()
    url = f"/api/journeys/{other['id']}/papers/bulk"
    response = client.post(url, json={"msc_category": p["msc"][:2], "limit": 1})
    assert response.status_code == 201
    copied = response.json()[0]["paper"]
    assert copied["msc"] == p["msc"] and copied["source"]["paper_id"] == p["id"]
    assert client.post(url, json={"msc_category": p["msc"]}).json() == []
    assert client.post(url, json={"msc_category": "15 OR all:*"}).status_code == 400
    assert client.post(url, json={"msc_category": "15", "limit": 21}).status_code == 400
    assert not app.state.store.all("calls")


def test_definition_typecheck_is_not_theorem_verification(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from metis.config import Config
    from metis.formal import verify_definition

    (tmp_path / "lean-toolchain").write_text("pinned-toolchain")
    (tmp_path / "lake-manifest.json").write_text("{}")
    (tmp_path / "METIS_MATHLIB_VERSION").write_text("v")
    c = Config(lean_image="trusted@sha256:" + "a" * 64, lean_project=str(tmp_path))
    monkeypatch.setattr("metis.formal.shutil.which", lambda _: "docker")

    def fake(cmd, **kw):
        if "run" in cmd:
            kw["stdout"].write(b"'metis_result' does not depend on any axioms\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("metis.formal.subprocess.run", fake)
    result = verify_definition(c, "Nat", "0", "v", True)
    assert result["status"] == "typechecked" and result["type_checked"]
    assert not result["machine_verified"]
    assert not verify_definition(c, "Nat", "0", "v", False)["type_checked"]
    assert not verify_definition(c, "Nat", "by sorry", "v", True)["type_checked"]


@pytest.mark.parametrize("bad_stage", ["literature", "edge_cases"])
def test_concept_uncertainty_cannot_pass_blind_acceptance(
    app, client, journey, monkeypatch, bad_stage
):
    from metis.concepts import consider

    r = run(client, journey, paper(client, journey))
    r["fixture"] = False
    w, s = app.state.worker, app.state.store
    g = graph(s, journey)
    group = next(g for g in g["groups"] if g["depth"] == 3)
    pattern = {
        "id": "pattern",
        "runs": [],
        "status": "awaiting independent concept proposal and blind testing",
    }
    s.put("memory", pattern)

    def call(role, payload, run, key, **kwargs):
        if role == "odysseus":
            return {
                "candidate": dict(
                    name="Candidate",
                    statement="A proposed definition",
                    description="A candidate",
                    kind="definition",
                    home_group=group["id"],
                )
            }
        if role == "penelope":
            return dict(well_defined=True, not_trivial=True, not_duplicate=True)
        if role == "tiresias":
            return dict(
                _search_complete=True, found=bad_stage == "literature", sources=[]
            )
        if role.startswith("crew"):
            node_id = payload["candidate"]["id"]
            return (
                dict(
                    counterexample_found=False,
                    proposals=[
                        dict(
                            premises=[g["concepts"][0]["id"]],
                            conclusion=node_id,
                            directed=True,
                            type="related",
                            tier="intuitive",
                            argument="Mock support",
                            evidence=[],
                        )
                    ],
                )
                if role != "crew3"
                else {}
            )
        raise AssertionError(role)

    monkeypatch.setattr(w, "call", call)
    monkeypatch.setattr(w, "review", lambda *a: (True, "intuitive", {}, {}))
    created = consider(w, r, [pattern])
    assert created
    assert s.get("concepts", created[0])["status"] == "Proposed"


def test_download_total_deadline_stops_slow_trickle(monkeypatch):
    from metis.ingestion import fetch
    from types import SimpleNamespace

    monkeypatch.setattr(
        "metis.ingestion.resolve_public",
        lambda u: (
            SimpleNamespace(
                scheme="http",
                hostname="example.org",
                port=None,
                netloc="example.org",
                path="/",
                query="",
            ),
            "8.8.8.8",
        ),
    )
    times = iter([0, 1, 41])
    monkeypatch.setattr("metis.ingestion.time.monotonic", lambda: next(times))

    class Response:
        status = 200

        def getheader(self, key, default=""):
            return default

        def read1(self, n):
            return b"x"

    class Connection:
        def __init__(self, *a, **kw):
            pass

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("metis.ingestion.http.client.HTTPConnection", Connection)
    with pytest.raises(ValueError, match="deadline"):
        fetch("http://example.org/")


def test_lost_lease_cannot_start_or_publish_provider_call(app, client, journey):
    from metis.pipeline import Interrupted

    r = run(client, journey, paper(client, journey))
    w, s = app.state.worker, app.state.store
    job = s.claim(w.owner)
    r["_job"] = job
    w.providers.call = Mock()
    s.patch("jobs", job["id"], owner="replacement")
    with pytest.raises(Interrupted, match="lease"):
        w.call("penelope", {}, r, "before")
    w.providers.call.assert_not_called()
    s.patch("jobs", job["id"], owner=job["owner"])

    def late(*args):
        s.patch("jobs", job["id"], owner="replacement")
        return {"result": "late"}

    w.providers.call = late
    with pytest.raises(Interrupted, match="lease"):
        w.call("penelope", {}, r, "after")


def test_module_import_rejects_fabricated_ancestry_before_writing(app):
    from metis.base import import_module

    s = app.state.store
    root = s.all("groups")[0]
    bundle = dict(
        module=dict(
            id="invalid@1",
            version="1",
            source="curator",
            islands=[root["island"]],
            requires=[root["layer"].removeprefix("module:")],
        ),
        groups=[
            dict(
                id="fake",
                depth=3,
                island=root["island"],
                parent=root["id"],
                ancestors=["invented", "path", "fake"],
            )
        ],
    )
    with pytest.raises(ValueError, match="ancestry"):
        import_module(s, bundle)
    assert s.get("groups", "fake") is None
    assert s.get("modules", "invalid@1") is None


def test_chunked_upload_rejected_before_multipart_parsing(client):

    def chunks():
        for _ in range(15):
            yield b"x" * (1024 * 1024)

    response = client.post(
        "/api/journeys", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert client.get("/api/journeys").json() == []
    assert (
        client.post(
            "/api/journeys", content=b"{}", headers={"Content-Length": "invalid"}
        ).status_code
        == 400
    )


def test_candidate_cannot_integrate_an_entire_disconnected_component():
    nodes = {
        n: dict(
            id=n,
            ancestors=["a", "b", "c"],
            status="Established",
            embedding=[1, 0],
            integrated=True,
        )
        for n in "ABCD"
    }

    def e(ident, a, b):
        return dict(
            id=ident,
            premises=[a],
            conclusion=b,
            directed=True,
            type="implies",
            tier="cited",
            review_status="passed",
        )

    candidate = e("candidate", "A", "B")
    result = score(
        candidate,
        nodes,
        [candidate, e("bc", "B", "C"), e("ad", "A", "D")],
        Settings().model_dump(),
        anchors={"A", "D"},
    )
    assert result["pairs"][0]["tree_only"]
    assert result["value"] == 0


def test_failed_feedback_for_cancelled_run_can_be_budgeted_and_retried(
    app, client, journey
):
    r = run(client, journey, paper(client, journey))
    complete(app)
    s = app.state.store
    e = app.state.worker.run_edges(r)[0]
    f = client.post(
        f"/api/journeys/{journey['id']}/feedback",
        json={"target_id": e["id"], "mark": "wrong"},
    ).json()
    s.patch("runs", r["id"], status="cancelled")
    complete(app)
    assert s.get("rechecks", f["id"])["status"] == "complete"
    # Retry a failed operation through the durable queue, with its own explicit cap.
    s.patch("rechecks", f["id"], status="failed")
    result = client.post(
        f"/api/journeys/{journey['id']}/rechecks/{f['id']}", json={"budget_usd": 0.5}
    )
    assert result.status_code == 200
    assert result.json()["status"] == "queued" and result.json()["budget_usd"] == 0.5
    complete(app)
    assert s.get("rechecks", f["id"])["status"] == "complete"


def test_base_rereview_downgrade_is_effective_without_mutating_module(
    app, client, journey
):
    from metis.graph import adjacency

    s = app.state.store
    a, b = graph(s, journey)["concepts"][:2]
    base = dict(
        id="base-review",
        layer=a["layer"],
        premises=[a["id"]],
        conclusion=b["id"],
        directed=True,
        type="implies",
        tier="cited",
        review_status="passed",
        argument="Base claim",
        evidence=[],
        existing="Existing",
    )
    s.put("edges", base)
    client.post(
        f"/api/journeys/{journey['id']}/feedback",
        json={"target_id": base["id"], "mark": "wrong"},
    )
    complete(app)
    effective = graph(s, journey)
    reviewed = next(e for e in effective["edges"] if e["id"] == base["id"])
    assert reviewed["tier"] == "intuitive" and not reviewed.get("invalidated")
    assert s.get("edges", base["id"]) == base
    assert not adjacency(
        {n["id"]: n for n in effective["concepts"]}, effective["edges"]
    )[a["id"]]
