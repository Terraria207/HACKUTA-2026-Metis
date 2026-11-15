#!/usr/bin/env python3
"""Install every basis group from mathlib, in one command (Windows, macOS, Linux).

  python scripts/install_basis_groups.py

Steps, each skipped when already done (run it again after an interruption):
  1. check the tools: Python 3.12+, git, and lake from elan (the Lean installer)
  2. download the pinned mathlib and its compiled cache, and compile a small acceptance file
  3. export every mathematical declaration of mathlib (about six minutes)
  4. fetch the official MSC 2020 table from msc2020.org
  5. place every declaration in the MSC tree and split it into basis groups
  6. build all of them into the app's database, so New Journey shows them as Ready

Afterwards start the server as usual; it finds the index in .lean/exports/index by itself.
No model, API key or account is used. Needs about 8 GB of free disk and 8 GB of memory.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PINS = json.loads((ROOT / "deploy/lean/pins.json").read_text(encoding="utf-8"))
LEAN = ROOT / ".lean"
PROJECT = LEAN / "mathlib"
EXPORT = LEAN / "exports" / "mathlib-full.jsonl"
MSC = LEAN / "msc" / "msc2020.json"
INDEX = LEAN / "exports" / "index"


def step(number, title):
    print("\n[%d/6] %s" % (number, title), flush=True)


def run(*args):
    print("      $ " + " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def find_lake():
    lake = shutil.which("lake")
    if lake:
        return lake
    home = Path(os.environ.get("ELAN_HOME", Path.home() / ".elan")) / "bin"
    for name in ("lake.exe", "lake"):
        if (home / name).is_file():
            os.environ["PATH"] = str(home) + os.pathsep + os.environ.get("PATH", "")
            return str(home / name)
    return None


def check_tools():
    problems = []
    if sys.version_info < (3, 12):
        problems.append("Python 3.12 or newer is required (this is %d.%d)." % sys.version_info[:2])
    if not shutil.which("git"):
        problems.append("git is not on PATH. Windows: winget install Git.Git, then open a new terminal.")
    if not find_lake():
        problems.append("lake (from elan, the Lean installer) is not on PATH. Windows, in PowerShell:\n"
                        "        curl.exe -O --location https://elan.lean-lang.org/elan-init.ps1\n"
                        "        powershell -ExecutionPolicy Bypass -File elan-init.ps1\n"
                        "      then open a new terminal. macOS/Linux: see https://lean-lang.org/install")
    free = shutil.disk_usage(ROOT).free / 2**30
    done = (PROJECT / "METIS_MATHLIB_VERSION").is_file()
    if free < (2 if done else 8):
        problems.append("Only %.1f GB free on this drive; about %d GB is needed." % (free, 2 if done else 8))
    if os.name == "nt" and len(str(PROJECT)) > 60:
        print("      Note: the project path is long (%s). If Lean later reports a path that is too long, move\n"
              "      the repository somewhere short such as C:\\metis, or enable Windows long paths." % PROJECT)
    if problems:
        raise SystemExit("\nCannot continue:\n  - " + "\n  - ".join(problems))
    print("      Python %d.%d, git and lake found; %.0f GB free." % (sys.version_info[:2] + (free,)))


def prebuild():
    """Build every basis group into the database the server uses (fixture mode: script builds)."""
    from metis.base import import_corpus, seed
    from metis.config import Config
    from metis.exportindex import load_index
    from metis.gods import module_id_for, run_build
    from metis.providers import Providers
    from metis.store import Store, uid, now

    config = Config(mathlib_export=str(INDEX)).validate()
    if config.mode != "fixture":
        print("      Live mode: groups are built (and curated by the gods) when a journey first uses them,\n"
              "      within that journey's build budget. Nothing is pre-built here.")
        return
    store = Store(config)
    seed(store)
    if config.import_corpus:
        import_corpus(store)
    index = load_index(str(INDEX))
    providers = Providers(store, config)
    built = 0
    for n, entry in enumerate(index["islands"], 1):
        module = module_id_for(entry["id"], index["mathlib"])
        if (store.get("modules", module) or {}).get("status") == "ready":
            continue
        job = {"id": uid("build_"), "island": entry["id"], "status": "queued", "percent": 0, "stage": "", "budget_usd": 0, "created": now()}
        store.put("builds", job)
        run_build(store, config, providers, job, ROOT / "deploy" / "msc")
        result = store.get("builds", job["id"])
        if result["status"] != "ready":
            raise SystemExit("Building %s failed: %s" % (entry["name"], result.get("error")))
        built += 1
        print("      %2d/%d  %-55s ready" % (n, len(index["islands"]), entry["name"][:55]), flush=True)
    print("      %d built now, %d already there. Database: %s" % (built, len(index["islands"]) - built, config.sqlite_path))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-prebuild", action="store_true", help="Stop after the index; groups are then built on first use")
    args = parser.parse_args()
    started = time.time()
    os.chdir(ROOT)

    step(1, "Checking tools")
    check_tools()

    step(2, "Pinned mathlib %s and its compiled cache" % PINS["mathlib"][:8])
    if (PROJECT / "METIS_MATHLIB_VERSION").is_file() and (PROJECT / "METIS_MATHLIB_VERSION").read_text(encoding="utf-8").strip() == PINS["mathlib"]:
        print("      Already prepared.")
    else:
        print("      Downloads about 5 GB the first time; this is the slow step.")
        run(sys.executable, ROOT / "scripts/setup_lean.py", PROJECT)

    step(3, "Exporting every mathematical declaration")
    meta = Path(str(EXPORT) + ".meta.json")
    if EXPORT.is_file() and meta.is_file() and json.loads(meta.read_text(encoding="utf-8")).get("mathlib") == PINS["mathlib"]:
        print("      Already exported (%s declarations)." % json.loads(meta.read_text(encoding="utf-8"))["declarations"])
    else:
        run(sys.executable, ROOT / "scripts/extract_mathlib.py", "--project", PROJECT, "--output", EXPORT)

    step(4, "MSC 2020 table")
    if MSC.is_file():
        print("      Already downloaded.")
    else:
        run(sys.executable, ROOT / "scripts/fetch_msc.py", "--output", MSC)

    step(5, "Splitting the export into basis groups")
    run(sys.executable, "-m", "scripts.index_export", "--export", EXPORT, "--msc", MSC, "--output", INDEX)

    step(6, "Building every basis group")
    if args.no_prebuild:
        print("      Skipped (--no-prebuild): each group is built the first time a journey uses it.")
    else:
        prebuild()

    print("\nDone in %d min. Start the server as usual:" % round((time.time() - started) / 60))
    python = r".venv\Scripts\python" if os.name == "nt" else ".venv/bin/python"
    print("  %s -m uvicorn metis.main:app --host 127.0.0.1 --port 8000 --workers 1" % python)
    print("New Journey now lists every basis group as Ready.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit("\nA step failed (%s). Fix the message above and run this script again; "
                         "finished steps are skipped." % " ".join(str(a) for a in exc.cmd[:3]))
