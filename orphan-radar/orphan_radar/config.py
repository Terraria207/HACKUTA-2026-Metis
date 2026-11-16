"""Configuration: config.toml for weights/thresholds, environment for secrets."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides the real environment."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    raw: dict
    path: Path
    data_dir: Path = field(default_factory=lambda: ROOT / "data")

    @property
    def weights(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.raw["weights"].items()}

    def section(self, name: str) -> dict:
        return self.raw.get(name, {})

    def threshold(self, name: str, default=None):
        return self.raw.get("thresholds", {}).get(name, default)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "orphan_radar.sqlite3"


def load_config(path: str | os.PathLike | None = None) -> Config:
    load_dotenv()
    path = Path(path or os.environ.get("ORPHAN_RADAR_CONFIG") or ROOT / "config.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    total = sum(float(v) for v in raw["weights"].values())
    if abs(total - 100) > 1e-6:
        raise ValueError(f"weights in {path} must sum to 100, got {total}")
    data_dir = Path(os.environ.get("ORPHAN_RADAR_DATA_DIR") or ROOT / "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(raw=raw, path=path, data_dir=data_dir)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default
