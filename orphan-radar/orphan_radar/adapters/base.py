"""The one interface every source implements.

To add a source: subclass Adapter, set the class attributes, implement collect(),
and add the class to ADAPTERS in adapters/__init__.py. collect() yields Product
and Evidence records; the pipeline stores, deduplicates and matches them.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Iterator

from ..config import Config, env
from ..models import Evidence, Product
from ..net import HttpClient

Record = Product | Evidence


@dataclass
class ScanContext:
    conn: sqlite3.Connection
    http: HttpClient
    config: Config
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("orphan_radar"))

    def scan_cfg(self, key: str, default=None):
        return self.config.section("scan").get(key, default)

    def candidates(self, limit: int) -> list[sqlite3.Row]:
        """Most promising entities so far (latest score, else user count), for enrichment adapters."""
        return self.conn.execute(
            """
            SELECT e.id, e.name, e.norm_name,
                   (SELECT total FROM scores s WHERE s.entity_id=e.id ORDER BY s.id DESC LIMIT 1) AS score,
                   (SELECT MAX(COALESCE(p.user_count, 0)) FROM products p WHERE p.entity_id=e.id) AS users
            FROM entities e
            WHERE e.id NOT IN (SELECT entity_id FROM exclusions)
            ORDER BY COALESCE(score, -1) DESC, users DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


class Adapter:
    name: str = ""                  # short id used on the CLI: `scan --source <name>`
    title: str = ""
    docs_url: str = ""              # the documentation read before writing the adapter
    terms_url: str = ""
    api_hosts: dict[str, float] = {}  # documented API host -> minimum seconds between requests
    env_required: tuple[str, ...] = ()
    phase: int = 1                  # 1 = discovers products; 2 = enriches existing candidates

    def available(self) -> tuple[bool, str]:
        missing = [k for k in self.env_required if not env(k)]
        if missing:
            return False, f"needs environment variable(s): {', '.join(missing)}"
        return True, ""

    def prepare(self, http: HttpClient) -> None:
        for host, interval in self.api_hosts.items():
            http.register_api(host, interval)

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        raise NotImplementedError
