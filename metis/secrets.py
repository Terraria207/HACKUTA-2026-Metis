"""API keys and connection strings entered in the Settings screen.

A private 0600 server file, never returned by any API. A server environment variable of the same
name always wins over a stored value.
"""

import json
import os
import re

from metis.store import now


class KeyStore:
    """API keys entered in Settings: a private 0600 server file, never returned by any API.
    A server environment variable of the same name always wins over a stored key."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                self.data = {}

    def get(self, name):
        return os.getenv(name) or (self.data.get(name) or {}).get("value") or None

    def status(self, name):
        entry = self.data.get(name) or {}
        return {
            "set": bool(self.get(name)),
            "source": "environment" if os.getenv(name) else "stored" if entry.get("value") else None,
            "test": entry.get("test"),
        }

    def _write(self):
        if not self.path:
            raise ValueError("No key file configured (METIS_KEYS_FILE)")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temp = self.path + ".tmp"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(temp, self.path)

    def set(self, name, value):
        import re

        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", name or ""):
            raise ValueError("Invalid key name")
        if value in (None, ""):
            self.data.pop(name, None)
        else:
            if not isinstance(value, str) or not 8 <= len(value) <= 500 or not value.isprintable() or " " in value:
                raise ValueError("A key is 8 to 500 printable characters without spaces")
            self.data[name] = {"value": value, "saved": now()}
        self._write()

    def mark(self, name, ok, detail):
        entry = self.data.setdefault(name, {})
        entry["test"] = {"ok": bool(ok), "time": now(), "detail": str(detail)[:300]}
        self._write()
