"""A per-entity view of the evidence. Every figure handed to scoring or briefs is a Fact
that carries the ids of the evidence rows it was read or derived from."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .db import loads
from .textutil import days_between, parse_date

MARKETPLACES = {"wordpress": "WordPress.org plugin directory", "firefox": "Firefox Add-ons (addons.mozilla.org)",
                "openvsx": "Open VSX Registry", "github": "GitHub",
                "atlassian": "Atlassian Marketplace"}


@dataclass
class Fact:
    key: str
    value: object
    evidence_ids: list[int]
    label: str = ""
    derived: bool = False   # computed from the cited records rather than read from one

    def __bool__(self):
        return self.value is not None


@dataclass
class EntityView:
    entity: dict
    products: list[dict]
    evidence: list[dict]
    window_days: int = 365
    _metrics: dict = field(default_factory=dict)

    @classmethod
    def load(cls, conn: sqlite3.Connection, entity_id: int, window_days: int = 365) -> "EntityView":
        row = conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            raise ValueError(f"no such opportunity: {entity_id}")
        ent = dict(row)
        prods = [dict(r) for r in conn.execute("SELECT * FROM products WHERE entity_id=? ORDER BY id", (entity_id,))]
        for p in prods:
            p["extra"] = loads(p["extra_json"], {})
            p["tags_list"] = loads(p["tags"], [])
        evs = [dict(r) for r in conn.execute("SELECT * FROM evidence WHERE entity_id=? ORDER BY id", (entity_id,))]
        for e in evs:
            e["tag_list"] = loads(e["tags"], [])
            e["extra"] = loads(e["extra_json"], {})
        view = cls(entity=ent, products=prods, evidence=evs, window_days=window_days)
        for e in evs:
            # any record carrying a figure is indexed (listing metrics, autocomplete counts, views, points)
            if e["metric_key"]:
                view._metrics.setdefault(e["metric_key"], []).append(e)
        return view

    # -- basic accessors ------------------------------------------------------
    @property
    def id(self) -> int:
        return self.entity["id"]

    @property
    def name(self) -> str:
        return self.entity["name"]

    @property
    def primary(self) -> dict | None:
        pid = self.entity.get("primary_product_id")
        return next((p for p in self.products if p["id"] == pid), self.products[0] if self.products else None)

    @property
    def sources(self) -> list[str]:
        return sorted({p["source"] for p in self.products})

    def product_by_id(self, pid) -> dict | None:
        return next((p for p in self.products if p["id"] == pid), None)

    def metric_rows(self, key: str) -> list[dict]:
        return self._metrics.get(key, [])

    def metric(self, key: str, prefer: str = "max") -> Fact | None:
        rows = [r for r in self.metric_rows(key) if r["metric_value"] is not None or r["metric_text"] is not None]
        if not rows:
            return None
        if prefer == "max" and all(r["metric_value"] is not None for r in rows):
            row = max(rows, key=lambda r: r["metric_value"])
        elif prefer == "latest_date":
            row = max(rows, key=lambda r: parse_date(r["metric_text"]) or parse_date("1970-01-01"))
        else:
            primary = self.primary
            row = next((r for r in rows if primary and r["product_id"] == primary["id"]), rows[0])
        value = row["metric_value"] if row["metric_value"] is not None else row["metric_text"]
        if isinstance(value, float) and value.is_integer() and key not in ("rating", "rating_recent"):
            value = int(value)
        return Fact(key, value, [row["id"]], row["text"] or key)

    def metric_for_product(self, key: str, product_id: int) -> Fact | None:
        row = next((r for r in self.metric_rows(key) if r["product_id"] == product_id), None)
        if not row:
            return None
        value = row["metric_value"] if row["metric_value"] is not None else row["metric_text"]
        if isinstance(value, float) and value.is_integer() and key not in ("rating", "rating_recent"):
            value = int(value)
        return Fact(key, value, [row["id"]], row["text"] or key)

    def listing_text(self) -> str:
        """Name, description, category and tags of every listing, lower-cased, for keyword rules."""
        parts = []
        for p in self.products:
            parts += [p.get("name") or "", p.get("description") or "", p.get("category") or "", " ".join(p.get("tags_list") or [])]
        return " ".join(parts).lower()

    def listing_fact(self, product_id: int | None = None) -> Fact | None:
        """A Fact standing for one listing itself: its description row, else any metric read from it."""
        pid = product_id if product_id is not None else (self.primary or {}).get("id")
        for key in ("description", "user_count", "github_stars", "downloads", "last_updated"):
            f = self.metric_for_product(key, pid) if pid is not None else None
            if f:
                return Fact("listing", (self.product_by_id(pid) or {}).get("url"), f.evidence_ids, "listing")
        return None

    # -- audience -------------------------------------------------------------
    def audience(self) -> tuple[Fact | None, bool]:
        """Best audience figure and whether it is a proxy (stars/downloads) rather than users."""
        users = self.metric("user_count")
        if users:
            return users, False
        for key in ("github_stars", "downloads"):
            f = self.metric(key)
            if f:
                return f, True
        return None, True

    def last_update(self) -> Fact | None:
        return self.metric("last_updated", prefer="latest_date")

    # -- evidence slices ------------------------------------------------------
    def recent(self, rows: list[dict]) -> list[dict]:
        out = []
        for e in rows:
            age = days_between(e["date_posted"]) if e["date_posted"] else None
            if age is not None and age <= self.window_days:
                out.append(e)
        return out

    def of_type(self, *types: str) -> list[dict]:
        return [e for e in self.evidence if e["type"] in types]

    def tagged(self, tag: str, rows: list[dict] | None = None) -> list[dict]:
        return [e for e in (self.evidence if rows is None else rows) if tag in e["tag_list"]]

    def tagged_prefix(self, prefix: str) -> list[dict]:
        return [e for e in self.evidence if any(t.startswith(prefix) for t in e["tag_list"])]

    def complaints(self, recent_only: bool = True) -> list[dict]:
        """Negative, quotable evidence: low-star reviews, negative support threads, issues, unanswered questions."""
        rows = [e for e in self.of_type("review", "support_thread", "issue", "question", "discussion")
                if "negative" in e["tag_list"] and e["text"]]
        return self.recent(rows) if recent_only else rows
