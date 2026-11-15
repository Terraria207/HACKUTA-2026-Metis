"""Run Metis under a small supervisor so the Settings screen can apply a mode change by
restarting the server in place, and so a bad live configuration never leaves the user without
a server: if the saved settings cannot start (MongoDB unreachable, for example), the server
comes up in fixture mode and reports why.

  python -m metis              # serve on 127.0.0.1:8000 and open the browser
  python -m metis --no-browser --port 8001
"""

import threading
import webbrowser

import uvicorn

from metis.api import create_app
from metis.config import Config

STATE = {"server": None, "restart": False}


def request_restart():
    """Stop the running server so the supervisor loop starts a new one with the saved settings."""
    server = STATE.get("server")
    if server is None:
        return False
    STATE["restart"] = True
    server.should_exit = True
    return True


def short_reason(text):
    """pymongo errors carry a whole topology dump; keep the part a person can act on."""
    for marker in (" (configured timeouts", ", Timeout:", ", Topology Description"):
        if marker in text:
            text = text.split(marker)[0]
    return text.strip()[:240]


def build_app():
    """The app for the saved settings, or a fixture-mode app that explains why they failed."""
    try:
        app, error = create_app(Config.current()), None
    except Exception as exc:  # the saved live settings are wrong: stay reachable and say so
        error = type(exc).__name__ + ": " + short_reason(str(exc))
        fallback = Config.current()
        fallback.mode, fallback.allow_live, fallback.mongo_uri = "fixture", False, ""
        fallback.sources["mode"] = "fallback"
        app = create_app(fallback)
    app.state.startup_error = error
    app.state.request_restart = request_restart
    return app


def serve(host="127.0.0.1", port=8000, open_browser=True):
    while True:
        app = build_app()
        if app.state.startup_error:
            print("Could not start with the saved settings: " + app.state.startup_error)
            print("Running in fixture mode instead. Fix the settings in Settings › Mode and apply again.")
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
        STATE["server"], STATE["restart"] = server, False
        if open_browser:
            threading.Timer(1.5, webbrowser.open, args=("http://%s:%d/" % (host, port),)).start()
            open_browser = False
        server.run()
        if not STATE["restart"]:
            break
        print("Restarting with the saved settings...")
