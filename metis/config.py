import os
import math
from dataclasses import dataclass


@dataclass
class Config:
    mode: str = os.getenv("METIS_MODE", "fixture")
    mongo_uri: str = os.getenv("MONGODB_URI", "")
    mongo_db: str = os.getenv("MONGODB_DATABASE", "metis")
    sqlite_path: str = os.getenv("METIS_SQLITE_PATH", ".metis/fixture.sqlite")
    api_token: str = os.getenv("METIS_API_TOKEN", "")
    live_budget: float = float(os.getenv("METIS_LIVE_BUDGET_USD", "0"))
    # Role configuration and API keys entered in the Settings screen live in private server files
    # (0600, under the git-ignored .metis/ directory by default). Environment variables win.
    provider_file: str = os.getenv("METIS_PROVIDERS_FILE", ".metis/providers.json")
    keys_file: str = os.getenv("METIS_KEYS_FILE", ".metis/keys.json")
    # Declaration export (scripts/extract_mathlib.py) used to build missing basis groups in-app.
    # Defaults to the index scripts/install_basis_groups.py writes; ignored when it does not exist.
    mathlib_export: str = os.getenv("METIS_MATHLIB_EXPORT", os.path.join(".lean", "exports", "index"))
    lean_image: str = os.getenv("METIS_LEAN_IMAGE", "")
    lean_project: str = os.getenv("METIS_LEAN_PROJECT", "")
    allow_live: bool = os.getenv("METIS_ALLOW_LIVE", "false").lower() == "true"
    # Fixture mode imports the reviewed bundles in corpus/ at startup (without vectors) so the
    # catalog offers real sourced modules locally. Live mode imports through budgeted preparation.
    import_corpus: bool = os.getenv("METIS_IMPORT_CORPUS", "true").lower() == "true"

    def validate(self):
        if self.mode not in ("fixture", "live"):
            raise RuntimeError("METIS_MODE must be fixture or live")
        if self.mode == "live" and not self.mongo_uri:
            raise RuntimeError(
                "Live mode requires MONGODB_URI; refusing fixture fallback"
            )
        if not math.isfinite(self.live_budget) or self.live_budget < 0:
            raise RuntimeError("Budget cannot be negative")
        return self
