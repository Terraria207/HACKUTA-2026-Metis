#!/usr/bin/env python3
"""Install every basis group from mathlib, in one command (Windows, macOS, Linux).

  python scripts/install_basis_groups.py

The same job the Settings screen runs (Settings › Basis groups), printed to the terminal:
  1. check the tools: git, and lake from elan (the Lean installer)
  2. download the pinned mathlib and its compiled cache, and compile a small acceptance file
  3. export every mathematical declaration of mathlib (about six minutes)
  4. fetch the official MSC 2020 table from msc2020.org
  5. place every declaration in the MSC tree and split it into basis groups
  6. build all of them into the app's database, so New Journey shows them as Ready

Each step is skipped when already done, so rerun it after an interruption. Missing tools:
--install-elan puts elan under .lean/elan; --install-git (Windows) puts a portable Git under
.lean/git. No model, API key or account is used. Needs about 8 GB of free disk and 8 GB of memory.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-prebuild", action="store_true", help="Stop after the index; groups are then built on first use")
    parser.add_argument("--install-elan", action="store_true", help="Install elan (Lean) under .lean/elan first")
    parser.add_argument("--install-git", action="store_true", help="Windows: install a portable Git under .lean/git first")
    args = parser.parse_args()
    os.chdir(ROOT)
    from metis import installer
    from metis.config import Config
    from metis.store import Store

    config = Config.current().validate()
    store = Store(config)
    for flag, tool in ((args.install_git, "git"), (args.install_elan, "elan")):
        if flag:
            job = installer.start(store, config, "tool", {"tool": tool}, background=False, echo=True)
            if job.status != "done":
                raise SystemExit("Installing %s failed: %s" % (tool, job.error))
    status = installer.tools()
    missing = [t for t in status.values() if not t["found"]]
    if missing:
        raise SystemExit("\nCannot continue. " + " ".join(t["hint"] for t in missing))
    job = installer.start(store, config, "install", {"prebuild": not args.no_prebuild}, background=False, echo=True)
    if job.status != "done":
        raise SystemExit("\nStopped: %s\nFix the message above and run this script again; finished steps are skipped." % job.error)
    python = r".venv\Scripts\python" if os.name == "nt" else ".venv/bin/python"
    print("\nDone. Start the server as usual (%s -m metis) and New Journey lists every basis group." % python)


if __name__ == "__main__":
    main()
