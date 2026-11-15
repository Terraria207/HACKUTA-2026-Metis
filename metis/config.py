"""Server configuration.

Three layers, highest first: environment variables (an operator's explicit choice), the settings
file the Settings screen writes (.metis/server.json by default), and the defaults below. Secrets
are not in that file: the MongoDB connection string lives in the private key store beside the
API keys. `Config()` reads the environment only, which keeps tests independent of a developer's
saved settings; the server starts from `Config.current()`.
"""

import json
import math
import os
from dataclasses import dataclass, field

# Settings the Settings screen may save, with the environment variable that overrides each.
SAVED = {
    "mode": "METIS_MODE",
    "mongo_db": "MONGODB_DATABASE",
    "allow_live": "METIS_ALLOW_LIVE",
    "live_budget": "METIS_LIVE_BUDGET_USD",
    "import_corpus": "METIS_IMPORT_CORPUS",
}


def read_settings(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(path, values):
    """Merge `values` into the settings file atomically (0600)."""
    data = dict(read_settings(path), **values)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = path + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(temp, path)
    return data


def coerce(key, value):
    if key in ("allow_live", "import_corpus"):
        return value if isinstance(value, bool) else str(value).lower() == "true"
    if key == "live_budget":
        return float(value)
    return str(value)


def env(name, default=""):
    return lambda: os.getenv(name, default)


def env_bool(name, default):
    return lambda: os.getenv(name, default).lower() == "true"


@dataclass
class Config:
    # Defaults are read from the environment when a Config is built, not when this module is
    # imported, so a launcher or a test may set them first.
    mode: str = field(default_factory=env("METIS_MODE", "fixture"))
    mongo_uri: str = field(default_factory=env("MONGODB_URI"))
    mongo_db: str = field(default_factory=env("MONGODB_DATABASE", "metis"))
    sqlite_path: str = field(default_factory=env("METIS_SQLITE_PATH", ".metis/fixture.sqlite"))
    api_token: str = field(default_factory=env("METIS_API_TOKEN"))
    live_budget: float = field(default_factory=lambda: float(os.getenv("METIS_LIVE_BUDGET_USD", "0")))
    # Role configuration, API keys and server settings entered in the Settings screen live in
    # private server files (0600, under the git-ignored .metis/ directory by default).
    provider_file: str = field(default_factory=env("METIS_PROVIDERS_FILE", ".metis/providers.json"))
    keys_file: str = field(default_factory=env("METIS_KEYS_FILE", ".metis/keys.json"))
    settings_file: str = field(default_factory=env("METIS_SETTINGS_FILE", ".metis/server.json"))
    # Declaration export used to build basis groups in-app: the index the installer writes
    # (Settings › Basis groups, or scripts/install_basis_groups.py). Ignored when absent.
    mathlib_export: str = field(default_factory=env("METIS_MATHLIB_EXPORT", os.path.join(".lean", "exports", "index")))
    lean_image: str = field(default_factory=env("METIS_LEAN_IMAGE"))
    lean_project: str = field(default_factory=env("METIS_LEAN_PROJECT"))
    allow_live: bool = field(default_factory=env_bool("METIS_ALLOW_LIVE", "false"))
    # Fixture mode imports the reviewed bundles in corpus/ at startup (without vectors) so the
    # catalog offers real sourced modules locally. Live mode imports through budgeted preparation.
    import_corpus: bool = field(default_factory=env_bool("METIS_IMPORT_CORPUS", "true"))
    # Where each saved setting's value came from: "env", "file" or "default".
    sources: dict = field(default_factory=dict)

    @classmethod
    def current(cls):
        """Environment over settings file over defaults; the MongoDB URI from the key store."""
        from metis.secrets import KeyStore

        cfg = cls()
        saved = read_settings(cfg.settings_file)
        for key, env in SAVED.items():
            if os.getenv(env) is not None:
                cfg.sources[key] = "env"
            elif key in saved:
                try:
                    setattr(cfg, key, coerce(key, saved[key]))
                    cfg.sources[key] = "file"
                except (TypeError, ValueError):
                    cfg.sources[key] = "default"
            else:
                cfg.sources[key] = "default"
        if os.getenv("MONGODB_URI"):
            cfg.sources["mongo_uri"] = "env"
        else:
            stored = KeyStore(cfg.keys_file).get("MONGODB_URI")
            cfg.mongo_uri = stored or ""
            cfg.sources["mongo_uri"] = "file" if stored else "default"
        return cfg

    def describe(self):
        """Values and their sources for the Settings screen; the URI itself is never returned."""
        return {
            "mode": {"value": self.mode, "source": self.sources.get("mode", "default")},
            "allow_live": {"value": self.allow_live, "source": self.sources.get("allow_live", "default")},
            "live_budget": {"value": self.live_budget, "source": self.sources.get("live_budget", "default")},
            "mongo_db": {"value": self.mongo_db, "source": self.sources.get("mongo_db", "default")},
            "mongo_uri": {"value": bool(self.mongo_uri), "source": self.sources.get("mongo_uri", "default")},
            "import_corpus": {"value": self.import_corpus, "source": self.sources.get("import_corpus", "default")},
        }

    def validate(self):
        if self.mode not in ("fixture", "live"):
            raise RuntimeError("METIS_MODE must be fixture or live")
        if self.mode == "live" and not self.mongo_uri:
            raise RuntimeError(
                "Live mode requires a MongoDB connection string (Settings › Mode, or MONGODB_URI); refusing fixture fallback"
            )
        if not math.isfinite(self.live_budget) or self.live_budget < 0:
            raise RuntimeError("Budget cannot be negative")
        return self
