import json
import socket
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from metis.store import Store, now
from metis.config import Config
from metis.providers import Providers, BudgetExceeded, ProviderUnavailable
from metis.ingestion import resolve_public, UnsafeURL, arxiv_url
from metis.formal import verify
from metis.base import import_module


def test_atomic_reservations_and_leases(app):
    s = app.state.store
    with ThreadPoolExecutor(max_workers=12) as pool:
        reserved = list(pool.map(lambda _: s.reserve("test", 1, 0.1), range(40)))
    assert sum(reserved) == 10
    assert s.get("budgets", "test")["reserved"] == pytest.approx(1)
    for _ in range(10):
        s.settle("test", 0.1, 0.1)
    assert s.get("budgets", "test")["spent"] == pytest.approx(1)
    s.insert("jobs", {"id": "job", "status": "queued", "available_at": 0})
    first = s.claim("one", lease=-1)
    assert first
    recovered = s.claim("two")
    assert recovered["owner"] == "two"
    assert s.owned_patch(first, status="done") is None
    assert s.owned_patch(recovered, status="done")["status"] == "done"


def live_providers(app, monkeypatch, budget=1):
    s = app.state.store
    cfg = Config(mode="live", allow_live=True, live_budget=budget)
    p = Providers(s, cfg)
    p.roles = {
        "penelope": {
            "provider": "openai",
            "model": "test",
            "key_env": "TEST_KEY",
            "max_cost_usd": 0.2,
            "input_usd_per_million": 1,
            "output_usd_per_million": 1,
        }
    }
    monkeypatch.setenv("TEST_KEY", "never-return-me")
    s.put("journeys", {"id": "j", "settings": {"budget_usd": budget}})
    return p, {"id": "r", "journey_id": "j", "budget_usd": budget}


def test_provider_zero_budget_missing_keys_and_unknown_prices(app, monkeypatch):
    p, r = live_providers(app, monkeypatch, budget=0)
    p._request = Mock(side_effect=AssertionError("network must not be called"))
    with pytest.raises(BudgetExceeded):
        p.call("penelope", {}, r, "k")
    monkeypatch.delenv("TEST_KEY")
    with pytest.raises(ProviderUnavailable, match="credential"):
        p.call("penelope", {}, r, "k")
    monkeypatch.setenv("TEST_KEY", "secret")
    p.roles["penelope"]["max_cost_usd"] = 0
    with pytest.raises(ProviderUnavailable, match="maximum"):
        p.call("penelope", {}, r, "k")
    assert not app.state.store.all("calls")
    p._request.assert_not_called()


def test_provider_idempotency_and_ambiguous_charge(app, monkeypatch):
    p, r = live_providers(app, monkeypatch)
    p._request = Mock(return_value={"verdict": "pass"})
    assert p.call("penelope", {"e": "x"}, r, "a") == p.call(
        "penelope", {"e": "x"}, r, "a"
    )
    assert p._request.call_count == 1
    assert app.state.store.get("budgets", "global")["spent"] == pytest.approx(0.2)
    p._request = Mock(side_effect=TimeoutError("ambiguous"))
    with pytest.raises(ProviderUnavailable, match="TimeoutError"):
        p.call("penelope", {}, r, "b")
    with pytest.raises(ProviderUnavailable, match="Prior call"):
        p.call("penelope", {}, r, "b")
    assert app.state.store.get("budgets", "global")["spent"] == pytest.approx(0.4)
    assert "never-return-me" not in json.dumps(app.state.store.all("calls"))


def test_reservations_roll_back_when_run_cap_fails(app, monkeypatch):
    p, r = live_providers(app, monkeypatch)
    r["budget_usd"] = 0
    with pytest.raises(BudgetExceeded):
        p.call("penelope", {}, r, "x")
    for account in ("global", "journey:j"):
        assert app.state.store.get("budgets", account)["reserved"] == pytest.approx(0)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:pass@example.com",
        "http://localhost:8080",
        "gopher://example.com",
        "http://127.0.0.1",
        "http://[::1]",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1",
        "http://100.100.100.200",
    ],
)
def test_ssrf_rejects_internal_destinations(url):
    with pytest.raises((UnsafeURL, ValueError)):
        resolve_public(url)


def test_dns_mixed_and_rebinding_pin(monkeypatch):
    def addr(ip):
        return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [addr("8.8.8.8"), addr("10.1.1.1")]
    )
    with pytest.raises(UnsafeURL):
        resolve_public("https://example.org/paper")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [addr("8.8.8.8")])
    u, ip = resolve_public("https://example.org/paper")
    assert ip == "8.8.8.8" and u.hostname == "example.org"


def test_arxiv_validation():
    assert arxiv_url("arXiv:2401.12345v2") == "https://arxiv.org/pdf/2401.12345v2"
    with pytest.raises(ValueError):
        arxiv_url("../etc/passwd")


def test_formal_fails_closed_without_alignment_or_sandbox():
    c = Config(lean_image="", lean_project="")
    assert verify(c, "True", "by trivial", "v", False)["status"] == "rejected"
    result = verify(c, "True", "by trivial", "v", True)
    assert result["status"] == "unavailable" and result["machine_verified"] is False


@pytest.mark.parametrize(
    "proof",
    [
        "by sorry",
        "by admit",
        "by exact True.intro\naxiom bad : False",
        "by run_tac do pure ()",
        'by dbg_trace "fake audit"',
    ],
)
def test_formal_rejects_untrusted_syntax(tmp_path, monkeypatch, proof):
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.19.0", encoding="utf-8")
    (tmp_path / "lake-manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "METIS_MATHLIB_VERSION").write_text("pinned", encoding="utf-8")
    c = Config(lean_image="test@sha256:" + "a" * 64, lean_project=str(tmp_path))
    monkeypatch.setattr("metis.formal.shutil.which", lambda s: "/usr/bin/docker")
    result = verify(c, "True", proof, "pinned", True)
    assert result["status"] == "rejected" and result["machine_verified"] is False


def test_store_survives_reopen(tmp_path):
    cfg = Config(mode="fixture", sqlite_path=str(tmp_path / "persist.sqlite"))
    Store(cfg).put("journeys", {"id": "j", "name": "Persistent"})
    assert Store(cfg).get("journeys", "j")["name"] == "Persistent"


def test_base_import_rejects_unverified_and_immutable(app):
    s = app.state.store
    bundle = {
        "module": {
            "id": "new@1",
            "version": "1",
            "source": "Reviewed export",
            "islands": ["linear-algebra"],
        },
        "groups": [
            {
                "id": "new:g",
                "name": "group",
                "msc": "15",
                "depth": 1,
                "ancestors": ["new:g"],
                "parent": None,
                "island": "linear-algebra",
            }
        ],
        "concepts": [
            {
                "id": "new:a",
                "home_group": "new:g",
                "source": {"url": "https://example.org"},
                "statement": "A",
                "description": "A",
                "name": "A",
                "kind": "theorem",
            },
            {
                "id": "new:b",
                "home_group": "new:g",
                "source": {"url": "https://example.org"},
                "statement": "B",
                "description": "B",
                "name": "B",
                "kind": "theorem",
            },
        ],
        "edges": [
            {
                "id": "new:e",
                "premises": ["new:a"],
                "conclusion": "new:b",
                "directed": True,
                "type": "implies",
                "tier": "verified",
                "argument": "not audited",
                "evidence": [],
            }
        ],
    }
    with pytest.raises(ValueError, match="mint verified"):
        import_module(s, bundle)
    bundle["edges"][0]["type"] = "dependency"
    result = import_module(s, bundle)
    assert result["status"] == "ready" and s.get("edges", "new:e")["inference"] is False
    with pytest.raises(ValueError, match="already exists"):
        import_module(s, bundle)


def test_recovery_after_checkpoint_job_gap(app, client, journey):
    from test_api import paper, run
    from conftest import complete

    p = paper(client, journey)
    r = run(client, journey, p)
    worker = app.state.worker
    s = app.state.store
    job = s.claim(worker.owner)
    worker.stage0(r)
    # Simulate process death after stage work/job completion but before checkpoint update.
    s.owned_patch(job, status="done")
    worker.recover()
    complete(app)
    assert s.get("runs", r["id"])["status"] == "complete"
    assert len(s.all("extractions")) == 1


def test_pause_prevents_next_live_call_and_cancel_wins(
    app, client, journey, monkeypatch
):
    from test_api import paper, run
    from metis.pipeline import Interrupted

    p = paper(client, journey)
    r = run(client, journey, p)
    w = app.state.worker
    s = app.state.store
    s.patch("runs", r["id"], status="paused")
    w.providers.call = Mock()
    with pytest.raises(Interrupted):
        w.call("penelope", {}, r, "call")
    w.providers.call.assert_not_called()
    s.patch("runs", r["id"], status="running")

    def late(*a, **kw):
        s.patch("runs", r["id"], status="cancelled")
        return {"ok": True}

    w.providers.call = late
    with pytest.raises(Interrupted):
        w.call("penelope", {}, r, "call")
    assert s.get("runs", r["id"])["status"] == "cancelled"


def test_wrong_feedback_runs_from_durable_queue(app, client, journey):
    from test_api import paper, run
    from conftest import complete

    p = paper(client, journey)
    r = run(client, journey, p)
    complete(app)
    e = app.state.worker.run_edges(r)[0]
    f = client.post(
        f"/api/journeys/{journey['id']}/feedback",
        json={"target_id": e["id"], "mark": "wrong"},
    ).json()
    complete(app)
    assert app.state.store.get("rechecks", f["id"])["status"] == "complete"


def test_base_support_is_overlay_not_mutation(app, client, journey):
    from test_api import paper, run
    from metis.graph import graph, EdgeInput, duplicate_key

    p = paper(client, journey)
    r = run(client, journey, p)
    s = app.state.store
    w = app.state.worker
    nodes = graph(s, journey)["concepts"]
    a, b = nodes[:2]
    e = {
        "premises": [a["id"]],
        "conclusion": b["id"],
        "directed": True,
        "type": "related",
        "tier": "cited",
        "argument": "Base association",
        "evidence": [{"source": "manual", "location": "1", "reviewed": True}],
    }
    base = dict(
        e,
        id="base:test",
        layer=a["layer"],
        review_status="passed",
        existing="Existing",
        duplicate_key=duplicate_key(e),
        support_count=1,
    )
    s.put("edges", base)
    saved = w.save_edge(r, e, "Crew", {"perspective": "test"}, "one")
    assert saved["base_edge_id"] == base["id"]
    assert s.get("edges", base["id"]) == base
    visible = graph(s, journey)["edges"]
    assert len([v for v in visible if v["duplicate_key"] == base["duplicate_key"]]) == 1
    assert visible[0]["journey_overlay"] == saved["id"]


def test_redirect_revalidates_destination(monkeypatch):
    from metis.ingestion import fetch

    def addr(host, *args, **kwargs):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1" if host == "127.0.0.1" else "8.8.8.8", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", addr)

    class Redirect:
        status = 302

        def getheader(self, name, default=None):
            return "http://127.0.0.1/private" if name == "Location" else default

    class Conn:
        def __init__(self, *args):
            pass

        def request(self, *args, **kw):
            pass

        def getresponse(self):
            return Redirect()

        def close(self):
            pass

    monkeypatch.setattr("metis.ingestion.PinnedHTTPS", Conn)
    with pytest.raises(UnsafeURL):
        fetch("https://public.example/paper")


def test_unretrieved_citation_cannot_become_cited(app, client, journey, monkeypatch):
    from test_api import paper, run
    from metis.graph import graph

    p = paper(client, journey)
    r = run(client, journey, p)
    r["fixture"] = False
    w = app.state.worker
    ns = graph(app.state.store, journey)["concepts"]
    a, b = ns[:2]
    edge = {
        "id": "claim",
        "premises": [a["id"]],
        "conclusion": b["id"],
        "directed": True,
        "type": "implies",
        "tier": "cited",
        "argument": "A claim",
        "evidence": [
            {
                "source": "unavailable reference",
                "location": "Theorem 1",
                "excerpt": "A long supposed quotation without a retrievable source.",
            }
        ],
    }

    def call(role, *args, **kw):
        return (
            {
                "hypotheses_match": True,
                "premises_necessary": True,
                "counterexample_found": False,
                "reason": "mock",
            }
            if role == "hypothesis"
            else {
                "verdict": "pass",
                "reason": "mock",
                "well_defined": True,
                "not_trivial": True,
                "not_duplicate": True,
                "citation_valid": True,
            }
        )

    monkeypatch.setattr(w, "call", call)
    passed, tier, _, _ = w.review(r, edge, {n["id"]: n for n in ns}, "citation-policy")
    assert passed and tier == "intuitive"


@pytest.mark.parametrize(
    "axioms,verified",
    [
        ("propext, Classical.choice, Quot.sound", True),
        ("badAxiom", False),
        ("sorryAx", False),
    ],
)
def test_mocked_lean_audit_and_sandbox_arguments(
    tmp_path, monkeypatch, axioms, verified
):
    from types import SimpleNamespace

    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.19.0", encoding="utf-8")
    (tmp_path / "lake-manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "METIS_MATHLIB_VERSION").write_text("pinned", encoding="utf-8")
    config = Config(lean_image="trusted@sha256:" + "a" * 64, lean_project=str(tmp_path))
    monkeypatch.setattr("metis.formal.shutil.which", lambda _: "docker")
    commands = []

    def fake(cmd, **kw):
        commands.append(cmd)
        if "run" in cmd:
            kw["stdout"].write(
                ("'metis_result' depends on axioms: [" + axioms + "]\n").encode()
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("metis.formal.subprocess.run", fake)
    result = verify(config, "True", "by trivial", "pinned", True)
    assert result["machine_verified"] is verified
    assert (
        "--network=none" in commands[0]
        and "--read-only" in commands[0]
        and "--pull=never" in commands[0]
    )
    assert commands[-1][:3] == ["docker", "rm", "-f"]


def test_terminal_status_is_atomic_across_checkpoint_and_errors(app):
    store = app.state.store
    store.put("runs", {"id": "race", "status": "cancelled", "checkpoint": 2})
    assert store.advance_run("race", 2)["status"] == "cancelled"
    assert store.transition_run("race", ("running", "queued"), status="failed") is None
    assert store.transition_run("race", ("paused", "failed"), status="queued") is None
    assert store.get("runs", "race")["status"] == "cancelled"
    store.put("runs", {"id": "pause", "status": "paused", "checkpoint": 6})
    result = store.advance_run("pause", 6)
    assert result["status"] == "paused" and result["checkpoint"] == 7
