"""Install basis groups from inside the app, with no command prompt.

The same steps as scripts/install_basis_groups.py, run as a background job the Settings screen
can start, watch and cancel: check the tools, download the pinned mathlib and its compiled
cache, export every mathematical declaration, fetch the MSC 2020 table, split the export into
basis groups, and build them into the database. Missing tools can be installed into the
project's own .lean/ directory (elan on every platform, a portable Git on Windows) so nothing
outside the project is touched. One job runs at a time; its log goes to .lean/install.log and
its state survives a page reload. No model, API key or account is involved.
"""

import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from collections import deque
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN = ROOT / ".lean"
ELAN_HOME = LEAN / "elan"
GIT_HOME = LEAN / "git"
TOOLS = LEAN / "tools"
PROJECT = LEAN / "mathlib"
EXPORT = LEAN / "exports" / "mathlib-full.jsonl"
MSC = LEAN / "msc" / "msc2020.json"
INDEX = LEAN / "exports" / "index"
LOG = LEAN / "install.log"
PINS = json.loads((ROOT / "deploy/lean/pins.json").read_text(encoding="utf-8"))
WINDOWS = os.name == "nt"
ELAN_BASE = "https://github.com/leanprover/elan/releases/latest/download/"
ELAN_ARCHIVES = {
    ("Windows", "AMD64"): "elan-x86_64-pc-windows-msvc.zip",
    ("Linux", "x86_64"): "elan-x86_64-unknown-linux-gnu.tar.gz",
    ("Linux", "aarch64"): "elan-aarch64-unknown-linux-gnu.tar.gz",
    ("Darwin", "arm64"): "elan-aarch64-apple-darwin.tar.gz",
    ("Darwin", "x86_64"): "elan-x86_64-apple-darwin.tar.gz",
}
MINGIT_URL = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"
ESTIMATE = {"download_gb": 5.5, "disk_gb": 8, "memory_gb": 8, "minutes": "15 to 40 minutes, mostly the download"}
# Share of the progress bar each step takes.
WEIGHTS = {"tools": 2, "mathlib": 40, "export": 26, "msc": 1, "index": 2, "build": 29}


def tool_env():
    """Environment for subprocesses: the project's own elan and Git first on PATH."""
    env = os.environ.copy()
    paths = []
    if (ELAN_HOME / "bin").is_dir():
        paths.append(str(ELAN_HOME / "bin"))
        env["ELAN_HOME"] = str(ELAN_HOME)
    if WINDOWS and (GIT_HOME / "cmd").is_dir():
        paths.append(str(GIT_HOME / "cmd"))
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def which(name):
    return shutil.which(name, path=tool_env()["PATH"])


def machine():
    return (platform.system(), platform.machine())


def tools():
    git, lake = which("git"), which("lake")
    managed = lambda path, home: bool(path) and Path(path).resolve().is_relative_to(home.resolve()) if home.exists() else False
    return {
        "git": {
            "found": bool(git), "path": git, "managed": managed(git, GIT_HOME),
            "auto": WINDOWS, "label": "Git",
            "hint": "Windows: the Install button puts a portable Git under .lean/git. Or install Git for Windows (winget install Git.Git) and restart the server."
            if WINDOWS else "Install git with your package manager (apt install git, brew install git) and restart the server.",
        },
        "lake": {
            "found": bool(lake), "path": lake, "managed": managed(lake, ELAN_HOME),
            "auto": machine() in ELAN_ARCHIVES, "label": "Lean (elan and lake)",
            "hint": "The Install button puts elan, the Lean installer, under .lean/elan; the pinned Lean toolchain downloads on first use (about 300 MB)."
            if machine() in ELAN_ARCHIVES else "No elan download is known for %s %s: install it from https://lean-lang.org/install and restart the server." % machine(),
        },
    }


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def steps_done():
    """What is already on disk, so a rerun skips it."""
    marker = PROJECT / "METIS_MATHLIB_VERSION"
    meta = read_json(str(EXPORT) + ".meta.json") or {}
    index = read_json(INDEX / "index.json") or {}
    return {
        "mathlib": marker.is_file() and marker.read_text(encoding="utf-8").strip() == PINS["mathlib"],
        "export": EXPORT.is_file() and meta.get("mathlib") == PINS["mathlib"],
        "export_declarations": meta.get("declarations"),
        "msc": MSC.is_file(),
        "index": index.get("mathlib") == PINS["mathlib"],
        "index_groups": len(index.get("islands", [])) if index else 0,
    }


# ---------------------------------------------------------------- jobs

LOCK = threading.Lock()
CURRENT = {"job": None}


class Cancelled(Exception):
    pass


class Job:
    def __init__(self, store, kind, options, echo=False):
        from metis.store import uid, now

        self.store, self.kind, self.options, self.echo = store, kind, options, echo
        self.id = uid("install_")
        self.status, self.error = "running", None
        self.steps = []
        self.step = None
        self.percent = 0
        self.started, self.finished = now(), None
        self.log = deque(maxlen=80)
        self.cancel = False
        self.proc = None
        self.thread = None
        self.lock = threading.Lock()
        self.save()

    def to_dict(self):
        return {
            "id": self.id, "kind": self.kind, "options": self.options, "status": self.status, "error": self.error,
            "steps": self.steps, "step": self.step, "percent": self.percent, "started": self.started,
            "finished": self.finished, "log": list(self.log),
        }

    def save(self):
        try:
            self.store.put("installs", self.to_dict())
        except Exception:
            pass  # the in-memory state is what the UI reads; persistence is best effort

    def say(self, line):
        from metis.store import now

        line = line.rstrip()
        if not line:
            return
        with self.lock:
            self.log.append({"time": now(), "text": line[:400]})
        if self.echo:
            print(line, flush=True)
        try:
            LEAN.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + line + "\n")
        except OSError:
            pass

    def begin(self, key, name):
        self.check_cancel()
        self.step = key
        self.steps.append({"key": key, "name": name, "status": "running", "detail": ""})
        self.say("== " + name)
        self.save()

    def done(self, detail="", skipped=False):
        self.steps[-1].update(status="skipped" if skipped else "done", detail=detail)
        self.percent = min(99, sum(WEIGHTS.get(s["key"], 0) for s in self.steps if s["status"] in ("done", "skipped")) * 100 // sum(WEIGHTS.values()))
        if detail:
            self.say("   " + detail)
        self.save()

    def progress(self, fraction, detail=""):
        """Progress within the current step (0..1)."""
        finished = sum(WEIGHTS.get(s["key"], 0) for s in self.steps[:-1] if s["status"] in ("done", "skipped"))
        self.percent = min(99, int((finished + WEIGHTS.get(self.step, 0) * max(0, min(1, fraction))) * 100 / sum(WEIGHTS.values())))
        if detail:
            self.steps[-1]["detail"] = detail
        self.save()

    def check_cancel(self):
        if self.cancel:
            raise Cancelled()

    def run(self, args, cwd=None):
        """Run a command, streaming its output into the log; raises on failure or cancel."""
        self.check_cancel()
        self.say("$ " + " ".join(str(a) for a in args))
        self.proc = subprocess.Popen(
            [str(a) for a in args], cwd=str(cwd or ROOT), env=tool_env(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        try:
            for line in self.proc.stdout:
                self.say(line.split("\r")[-1])
                if self.cancel:
                    self.proc.terminate()
            code = self.proc.wait()
        finally:
            self.proc = None
        self.check_cancel()
        if code != 0:
            label = next((Path(str(a)).name for a in args if str(a).endswith(".py")), None) or " ".join(str(a) for a in args[1:3])
            raise RuntimeError("%s exited with code %d; see the log above" % (label, code))

    def finish(self, status, error=None):
        from metis.store import now

        self.status, self.error, self.finished = status, error, now()
        if self.steps and self.steps[-1]["status"] == "running":
            self.steps[-1]["status"] = "failed" if status == "failed" else "cancelled"
        if status == "done":
            self.percent = 100
        self.say({"done": "== Finished.", "failed": "== Failed: " + str(error), "cancelled": "== Cancelled."}[status])
        self.save()


def current_job():
    return CURRENT["job"]


def running():
    job = CURRENT["job"]
    return job is not None and job.status == "running"


def start(store, config, kind="install", options=None, background=True, echo=False):
    """Start a job; `kind` is "install" or "tool" (options {"tool": "elan" | "git"})."""
    with LOCK:
        if running():
            raise ValueError("An installation is already running")
        job = Job(store, kind, options or {}, echo=echo)
        CURRENT["job"] = job
    target = (lambda: _run_tool(job)) if kind == "tool" else (lambda: _run_install(job, config))

    def wrapped():
        try:
            target()
            job.finish("done")
        except Cancelled:
            job.finish("cancelled")
        except Exception as exc:
            job.finish("failed", type(exc).__name__ + ": " + str(exc)[:400])

    if background:
        job.thread = threading.Thread(target=wrapped, daemon=True)
        job.thread.start()
    else:
        wrapped()
    return job


def cancel():
    job = CURRENT["job"]
    if not job or job.status != "running":
        return False
    job.cancel = True
    proc = job.proc
    if proc:
        try:
            proc.terminate()
        except OSError:
            pass
    return True


# ---------------------------------------------------------------- tool installs

def download(job, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    job.say("Downloading " + url)
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        while True:
            job.check_cancel()
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                job.progress(got / total, "%d of %d MB" % (got >> 20, total >> 20))
    job.say("Saved %s (%d MB)" % (dest.name, dest.stat().st_size >> 20))


def install_elan(job):
    key = machine()
    if key not in ELAN_ARCHIVES:
        raise RuntimeError("No elan download is known for %s %s" % key)
    archive = TOOLS / ELAN_ARCHIVES[key]
    download(job, ELAN_BASE + ELAN_ARCHIVES[key], archive)
    TOOLS.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extract("elan-init.exe", TOOLS)
        init = TOOLS / "elan-init.exe"
    else:
        with tarfile.open(archive) as t:
            member = t.getmember("elan-init")
            t.extract(member, TOOLS, filter="data")
        init = TOOLS / "elan-init"
        init.chmod(init.stat().st_mode | stat.S_IXUSR)
    ELAN_HOME.mkdir(parents=True, exist_ok=True)
    env = tool_env()
    env["ELAN_HOME"] = str(ELAN_HOME)
    job.say("$ elan-init -y --no-modify-path --default-toolchain none   (ELAN_HOME=%s)" % ELAN_HOME)
    result = subprocess.run([str(init), "-y", "--no-modify-path", "--default-toolchain", "none"], env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    for line in (result.stdout + result.stderr).splitlines():
        job.say(line)
    if result.returncode != 0 or not which("lake"):
        raise RuntimeError("elan-init did not produce a working lake")
    job.say("lake is now at " + which("lake") + ". The pinned Lean toolchain downloads the first time it runs.")


def install_git(job):
    if not WINDOWS:
        raise RuntimeError("Automatic Git installation is only offered on Windows; use your package manager")
    archive = TOOLS / "MinGit.zip"
    download(job, MINGIT_URL, archive)
    GIT_HOME.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(GIT_HOME)
    if not which("git"):
        raise RuntimeError("The portable Git did not produce a working git.exe")
    job.say("git is now at " + which("git"))


def _run_tool(job):
    tool = job.options.get("tool")
    job.begin("tools", "Install " + ("elan (Lean)" if tool == "elan" else "portable Git"))
    {"elan": install_elan, "git": install_git}[tool](job)
    job.done("installed under " + str(LEAN))


# ---------------------------------------------------------------- the install

def _run_install(job, config):
    from metis.base import seed, import_corpus
    from metis.exportindex import load_index
    from metis.gods import module_id_for, run_build
    from metis.providers import Providers
    from metis.store import uid, now

    python = sys.executable
    job.begin("tools", "Checking the tools")
    status = tools()
    missing = [t["label"] for t in status.values() if not t["found"]]
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing) + ". Install them from this screen first.")
    free = shutil.disk_usage(ROOT).free / 2**30
    done = steps_done()
    if free < (2 if done["mathlib"] else ESTIMATE["disk_gb"]):
        raise RuntimeError("Only %.1f GB free on this drive; about %d GB is needed" % (free, ESTIMATE["disk_gb"]))
    job.done("git %s; lake %s; %.0f GB free" % (status["git"]["path"], status["lake"]["path"], free))

    job.begin("mathlib", "Pinned mathlib %s and its compiled cache" % PINS["mathlib"][:8])
    if done["mathlib"]:
        job.done("already prepared", skipped=True)
    else:
        job.say("About 5 GB downloads the first time; this is the slow step.")
        job.run([python, ROOT / "scripts/setup_lean.py", PROJECT])
        job.done("prepared and compiler-checked")

    job.begin("export", "Exporting every mathematical declaration")
    if done["export"]:
        job.done("already exported (%s declarations)" % done["export_declarations"], skipped=True)
    else:
        job.run([python, ROOT / "scripts/extract_mathlib.py", "--project", PROJECT, "--output", EXPORT])
        job.done("%s declarations" % (steps_done()["export_declarations"] or "?"))

    job.begin("msc", "MSC 2020 table")
    if done["msc"]:
        job.done("already downloaded", skipped=True)
    else:
        job.run([python, ROOT / "scripts/fetch_msc.py", "--output", MSC])
        job.done("fetched from msc2020.org")

    job.begin("index", "Splitting the export into basis groups")
    job.run([python, "-m", "scripts.index_export", "--export", EXPORT, "--msc", MSC, "--output", INDEX])
    index = load_index(str(INDEX))
    job.done("%d basis groups" % len(index["islands"]))

    job.begin("build", "Building every basis group")
    if not job.options.get("prebuild", True):
        job.done("skipped: each group is built the first time a journey uses it", skipped=True)
        return
    cfg = replace(config, mathlib_export=str(INDEX))
    store = job.store
    if cfg.mode != "fixture":
        job.done("live mode: groups are built, within a budget, when a journey first uses them", skipped=True)
        return
    seed(store)
    if cfg.import_corpus:
        import_corpus(store)
    providers = Providers(store, cfg)
    islands = index["islands"]
    built = 0
    for n, entry in enumerate(islands, 1):
        job.check_cancel()
        module = module_id_for(entry["id"], index["mathlib"])
        if (store.get("modules", module) or {}).get("status") == "ready":
            job.progress(n / len(islands), "%d of %d" % (n, len(islands)))
            continue
        build = {"id": uid("build_"), "island": entry["id"], "status": "queued", "percent": 0, "stage": "", "budget_usd": 0, "created": now()}
        store.put("builds", build)
        run_build(store, cfg, providers, build, ROOT / "deploy" / "msc")
        result = store.get("builds", build["id"])
        if result["status"] != "ready":
            raise RuntimeError("Building %s failed: %s" % (entry["name"], result.get("error")))
        built += 1
        job.say("%2d/%d  %s" % (n, len(islands), entry["name"]))
        job.progress(n / len(islands), "%d of %d" % (n, len(islands)))
    job.done("%d built now, %d were already there" % (built, len(islands) - built))


def status(store, config):
    """Everything the Settings screen shows: tools, what is on disk, groups built, the job."""
    from metis.exportindex import load_index
    from metis.gods import module_id_for

    done = steps_done()
    index = load_index(str(INDEX)) if done["index"] else None
    ready = 0
    if index:
        # Same count as the harbour board: a group is ready when any ready module covers exactly it,
        # whether built from mathlib here or imported from the reviewed corpus.
        covered = {tuple(m["islands"]) for m in store.all("modules", status="ready") if len(m.get("islands") or []) == 1}
        ready = sum(1 for e in index["islands"] if (e["id"],) in covered)
        built = sum(1 for e in index["islands"] if (store.get("modules", module_id_for(e["id"], index["mathlib"])) or {}).get("status") == "ready")
    job = CURRENT["job"]
    if job is None:
        saved = sorted(store.all("installs"), key=lambda j: j.get("started", 0))
        last = saved[-1] if saved else None
    else:
        last = job.to_dict()
    return {
        "platform": "%s %s" % machine(),
        "root": str(ROOT),
        "disk_free_gb": round(shutil.disk_usage(ROOT).free / 2**30, 1),
        "estimate": ESTIMATE,
        "tools": tools(),
        "steps": done,
        "groups": {"total": len(index["islands"]) if index else None, "ready": ready, "built": built if index else 0},
        "mathlib": PINS["mathlib"],
        "export_in_use": config.mathlib_export == str(INDEX) or os.path.abspath(config.mathlib_export) == str(INDEX),
        "job": last,
        "running": running(),
        "log_file": str(LOG),
    }
