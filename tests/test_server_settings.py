"""Settings the user changes in the app instead of a command prompt: server mode, live switch,
MongoDB details, a supervised restart, and the in-app installer."""
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metis import installer
from metis.api import create_app
from metis.config import Config, read_settings, write_settings

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ("127.0.0.1", 50000)  # the test client is not loopback by default; settings writes require it


def make_config(tmp_path, **extra):
    return Config(mode="fixture", sqlite_path=str(tmp_path / "a.sqlite"), import_corpus=False,
                  provider_file=str(tmp_path / "p.json"), keys_file=str(tmp_path / "k.json"),
                  settings_file=str(tmp_path / "server.json"), **extra)


@pytest.fixture(autouse=True)
def private_install_log(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "LOG", tmp_path / "install.log")


def test_settings_layering_env_over_file_over_default(tmp_path, monkeypatch):
    for env in ("METIS_MODE", "MONGODB_URI", "MONGODB_DATABASE", "METIS_ALLOW_LIVE", "METIS_LIVE_BUDGET_USD", "METIS_IMPORT_CORPUS"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("METIS_SETTINGS_FILE", str(tmp_path / "server.json"))
    monkeypatch.setenv("METIS_KEYS_FILE", str(tmp_path / "k.json"))
    cfg = Config.current()
    assert cfg.mode == "fixture" and cfg.sources["mode"] == "default" and cfg.sources["mongo_uri"] == "default"
    data = write_settings(str(tmp_path / "server.json"), {"mode": "live", "live_budget": 12.5, "allow_live": True, "mongo_db": "metis-test"})
    assert data["mode"] == "live" and stat.S_IMODE(os.stat(tmp_path / "server.json").st_mode) == 0o600
    write_settings(str(tmp_path / "server.json"), {"import_corpus": False})
    assert read_settings(str(tmp_path / "server.json"))["mode"] == "live", "writes merge, not replace"
    from metis.secrets import KeyStore
    KeyStore(str(tmp_path / "k.json")).set("MONGODB_URI", "mongodb://user:pw@db.example/metis")
    cfg = Config.current()
    assert cfg.mode == "live" and cfg.live_budget == 12.5 and cfg.allow_live is True and cfg.mongo_db == "metis-test"
    assert cfg.import_corpus is False and cfg.mongo_uri == "mongodb://user:pw@db.example/metis"
    assert cfg.sources == {"mode": "file", "mongo_db": "file", "allow_live": "file", "live_budget": "file", "import_corpus": "file", "mongo_uri": "file"}
    monkeypatch.setenv("METIS_MODE", "fixture")
    monkeypatch.setenv("MONGODB_URI", "mongodb://env.example/x")
    cfg = Config.current()
    assert cfg.mode == "fixture" and cfg.sources["mode"] == "env" and cfg.mongo_uri == "mongodb://env.example/x" and cfg.sources["mongo_uri"] == "env"
    described = cfg.describe()
    assert described["mongo_uri"] == {"value": True, "source": "env"} and "mongodb" not in json.dumps(described)
    assert read_settings(str(tmp_path / "missing.json")) == {}
    (tmp_path / "bad.json").write_text("[1,2]", encoding="utf-8")
    assert read_settings(str(tmp_path / "bad.json")) == {}
    assert Config().sources == {}, "the plain constructor reads only the environment"


def test_server_settings_endpoints_save_validate_and_gate(tmp_path, monkeypatch):
    for env in ("METIS_MODE", "MONGODB_URI", "METIS_ALLOW_LIVE", "METIS_LIVE_BUDGET_USD"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("METIS_SETTINGS_FILE", str(tmp_path / "server.json"))
    monkeypatch.setenv("METIS_KEYS_FILE", str(tmp_path / "k.json"))
    app = create_app(make_config(tmp_path), False)
    with TestClient(app, client=LOCAL) as client:
        s = client.get("/api/server").json()
        assert s["running"]["mode"]["value"] == "fixture" and s["restart_required"] == [] and s["supervised"] is False and s["store"] == "sqlite"
        r = client.put("/api/server", json={"mode": "live", "live_budget": 5, "mongo_db": "metis"})
        assert r.status_code == 400 and "connection string" in r.json()["detail"], "live without a URI is refused"
        r = client.put("/api/server", json={"mongo_uri": "http://nope"})
        assert r.status_code == 400
        r = client.put("/api/server", json={"mongo_uri": "mongodb://u:secret@host.example/metis", "mode": "live", "allow_live": True, "live_budget": 5})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["saved"]["mode"]["value"] == "live" and s["saved"]["mongo_uri"] == {"value": True, "source": "file"}
        assert sorted(s["restart_required"]) == ["allow_live", "live_budget", "mode", "mongo_uri"]
        assert "secret" not in r.text and "secret" not in client.get("/api/server").text
        assert read_settings(str(tmp_path / "server.json")) == {"mode": "live", "allow_live": True, "live_budget": 5.0, "mongo_db": "metis"}
        for bad in ({"mode": "demo"}, {"live_budget": -1}, {"live_budget": "x"}, {"mongo_db": "bad name!"}):
            assert client.put("/api/server", json=bad).status_code in (400, 422), bad
        r = client.post("/api/server/test-mongo", json={"mongo_uri": "mongodb://127.0.0.1:1/?connectTimeoutMS=500&serverSelectionTimeoutMS=500"})
        assert r.status_code == 200 and r.json()["ok"] is False and "secret" not in r.text
        assert client.post("/api/server/test-mongo", json={"mongo_uri": "ftp://x"}).json()["ok"] is False
        r = client.post("/api/server/restart")
        assert r.status_code == 200 and r.json() == {"restarting": False, "supervised": False, "detail": r.json()["detail"]}
        assert "python -m metis" in r.json()["detail"]
        assert client.put("/api/server", json={"mongo_uri": None, "mode": "fixture"}).status_code == 200
        assert client.get("/api/server").json()["saved"]["mongo_uri"]["value"] is False
    # Not from this machine and no token: refused.
    with TestClient(app, client=("203.0.113.9", 4000)) as remote:
        assert remote.put("/api/server", json={"mode": "fixture"}).status_code == 403
        assert remote.post("/api/server/restart").status_code == 403
        assert remote.post("/api/install", json={}).status_code == 403
        assert remote.get("/api/server").status_code == 200


def test_supervisor_builds_fixture_app_when_saved_live_settings_fail(tmp_path, monkeypatch):
    from metis import server

    for env in ("METIS_MODE", "MONGODB_URI", "METIS_ALLOW_LIVE"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("METIS_SETTINGS_FILE", str(tmp_path / "server.json"))
    monkeypatch.setenv("METIS_KEYS_FILE", str(tmp_path / "k.json"))
    monkeypatch.setenv("METIS_SQLITE_PATH", str(tmp_path / "s.sqlite"))
    monkeypatch.setenv("METIS_IMPORT_CORPUS", "false")
    monkeypatch.setenv("METIS_PROVIDERS_FILE", str(tmp_path / "p.json"))
    write_settings(str(tmp_path / "server.json"), {"mode": "live"})
    app = server.build_app()
    assert app.state.config.mode == "fixture" and "connection string" in app.state.startup_error
    with TestClient(app) as client:
        st = client.get("/api/status").json()
        assert st["fixture"] and "connection string" in st["startup_error"] and st["supervised"] is True
        assert client.get("/api/overview").json()["startup_error"]
    assert server.request_restart() is False, "nothing is being served"

    class FakeServer:
        should_exit = False

    server.STATE["server"] = FakeServer()
    try:
        assert server.request_restart() is True and server.STATE["server"].should_exit is True and server.STATE["restart"] is True
    finally:
        server.STATE["server"] = None


def test_restart_endpoint_refuses_while_work_is_running(tmp_path):
    app = create_app(make_config(tmp_path), False)
    app.state.request_restart = lambda: True
    with TestClient(app, client=LOCAL) as client:
        assert client.post("/api/server/restart").json() == {"restarting": True, "supervised": True}
        stop = threading.Event()
        t = threading.Thread(target=stop.wait)
        t.start()
        app.state.build_threads.append(t)
        try:
            assert client.post("/api/server/restart").status_code == 409
        finally:
            stop.set()
            t.join()
        app.state.store.put("runs", {"id": "r", "journey_id": "j", "status": "running", "checkpoint": 1})
        assert client.post("/api/server/restart").status_code == 409


def test_installer_status_reports_tools_steps_and_groups(tmp_path, monkeypatch):
    app = create_app(make_config(tmp_path), False)
    with TestClient(app) as client:
        s = client.get("/api/install").json()
        assert set(s) >= {"platform", "disk_free_gb", "estimate", "tools", "steps", "groups", "job", "running", "mathlib"}
        assert s["tools"]["git"]["label"] == "Git" and "hint" in s["tools"]["lake"] and s["estimate"]["disk_gb"] == 8
        assert s["mathlib"] == json.loads((ROOT / "deploy/lean/pins.json").read_text(encoding="utf-8"))["mathlib"]
    monkeypatch.setattr(installer.shutil, "which", lambda name, path=None: None)
    assert not installer.tools()["git"]["found"] and not installer.tools()["lake"]["found"]
    monkeypatch.setattr(installer, "machine", lambda: ("Plan9", "mips"))
    assert installer.tools()["lake"]["auto"] is False and "lean-lang.org" in installer.tools()["lake"]["hint"]


def test_install_job_runs_steps_skips_done_work_and_records_progress(tmp_path, monkeypatch):
    """The step functions are stubbed: this checks the job machinery, not mathlib."""
    app = create_app(make_config(tmp_path), False)
    store = app.state.store
    monkeypatch.setattr(installer, "tools", lambda: {"git": {"found": True, "path": "/usr/bin/git", "label": "Git"}, "lake": {"found": True, "path": "/x/lake", "label": "Lean"}})
    monkeypatch.setattr(installer, "steps_done", lambda: {"mathlib": True, "export": False, "export_declarations": None, "msc": True, "index": False, "index_groups": 0})
    commands = []

    def fake_run(self, args, cwd=None):
        commands.append([str(a) for a in args])
        self.say("ran " + Path(str(args[-1])).name)

    monkeypatch.setattr(installer.Job, "run", fake_run)
    monkeypatch.setattr("metis.exportindex.load_index", lambda path: {"mathlib": installer.PINS["mathlib"], "islands": [{"id": "general-topology", "name": "General topology"}, {"id": "probability", "name": "Probability"}]})
    built = []

    def fake_build(store_, cfg, providers, job, spec_dir):
        built.append(job["island"])
        store_.patch("builds", job["id"], status="ready", module_id=job["island"] + "-mathlib@x-script")

    monkeypatch.setattr("metis.gods.run_build", fake_build)
    monkeypatch.setattr("metis.gods.module_id_for", lambda island, mathlib, curated=False: island + "-mathlib@x-script")
    store.put("modules", {"id": "probability-mathlib@x-script", "status": "ready", "islands": ["probability"], "version": "x", "source": "s"})
    with TestClient(app, client=LOCAL) as client:
        r = client.post("/api/install", json={"prebuild": True})
        assert r.status_code == 202
        job = installer.current_job()
        job.thread.join(timeout=30)
        s = client.get("/api/install").json()
    assert job.status == "done" and job.percent == 100, job.error
    statuses = {st["key"]: st["status"] for st in job.steps}
    assert statuses == {"tools": "done", "mathlib": "skipped", "export": "done", "msc": "skipped", "index": "done", "build": "done"}
    assert [c[-1].split("/")[-1] for c in commands[:1]] == ["mathlib-full.jsonl"] and any("scripts.index_export" in c for c in commands)
    assert built == ["general-topology"], "already-built groups are skipped"
    assert job.steps[-1]["detail"] == "1 built now, 1 were already there"
    assert s["job"]["status"] == "done" and s["running"] is False and any("== Finished." in l["text"] for l in s["job"]["log"])
    assert store.get("installs", job.id)["status"] == "done", "state survives a reload"
    assert "== Finished." in installer.LOG.read_text(encoding="utf-8")
    with TestClient(app, client=LOCAL) as client:
        assert client.post("/api/install", json={}).status_code == 202, "a finished job does not block the next"
        installer.current_job().thread.join(timeout=30)


def test_install_job_fails_clearly_without_tools_and_can_be_cancelled(tmp_path, monkeypatch):
    app = create_app(make_config(tmp_path), False)
    monkeypatch.setattr(installer, "tools", lambda: {"git": {"found": False, "label": "Git", "path": None}, "lake": {"found": True, "label": "Lean", "path": "/x"}})
    job = installer.start(app.state.store, app.state.config, "install", {}, background=False)
    assert job.status == "failed" and "Missing: Git" in job.error and job.steps[0]["status"] == "failed"
    monkeypatch.setattr(installer, "tools", lambda: {"git": {"found": True, "label": "Git", "path": "/g"}, "lake": {"found": True, "label": "Lean", "path": "/x"}})
    monkeypatch.setattr(installer, "steps_done", lambda: {"mathlib": False, "export": False, "export_declarations": None, "msc": False, "index": False, "index_groups": 0})
    started = threading.Event()

    def slow_run(self, args, cwd=None):
        started.set()
        for _ in range(200):
            self.check_cancel()
            time.sleep(0.02)

    monkeypatch.setattr(installer.Job, "run", slow_run)
    job = installer.start(app.state.store, app.state.config, "install", {})
    assert started.wait(5)
    with pytest.raises(ValueError, match="already running"):
        installer.start(app.state.store, app.state.config, "install", {})
    assert installer.cancel() is True
    job.thread.join(timeout=10)
    assert job.status == "cancelled" and job.steps[-1]["status"] == "cancelled" and installer.cancel() is False
    assert app.state.store.get("installs", job.id)["status"] == "cancelled"


def test_tool_env_prefers_the_projects_own_elan_and_git(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "ELAN_HOME", tmp_path / "elan")
    monkeypatch.setattr(installer, "GIT_HOME", tmp_path / "git")
    env = installer.tool_env()
    assert env["PYTHONUTF8"] == "1" and str(tmp_path / "elan") not in env["PATH"]
    (tmp_path / "elan" / "bin").mkdir(parents=True)
    env = installer.tool_env()
    assert env["PATH"].startswith(str(tmp_path / "elan" / "bin")) and env["ELAN_HOME"] == str(tmp_path / "elan")
    monkeypatch.setattr(installer, "WINDOWS", True)
    (tmp_path / "git" / "cmd").mkdir(parents=True)
    assert str(tmp_path / "git" / "cmd") in installer.tool_env()["PATH"]


def test_cli_installer_and_launchers_use_the_shared_module():
    cli = (ROOT / "scripts/install_basis_groups.py").read_text(encoding="utf-8")
    assert "from metis import installer" in cli and "--install-elan" in cli and "--install-git" in cli
    assert "-m metis" in (ROOT / "run.bat").read_text(encoding="utf-8")
    assert "python -m metis" in (ROOT / "run.sh").read_text(encoding="utf-8")
    assert os.access(ROOT / "run.sh", os.X_OK)
    main = (ROOT / "metis/__main__.py").read_text(encoding="utf-8")
    assert "serve(" in main and "--no-browser" in main
