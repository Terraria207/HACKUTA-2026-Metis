"""Normalised records produced by adapters, and the code that stores them."""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from .db import dumps, evidence_uid, now_iso

EVIDENCE_TYPES = {
    "metric", "review", "support_thread", "issue", "discussion", "question",
    "search_suggestion", "event", "price", "license", "export",
}

# Words that carry no identity when matching a product across sources.
_NAME_NOISE = {
    "the", "for", "and", "plugin", "plugins", "addon", "add", "on", "extension",
    "wordpress", "wp", "firefox", "chrome", "vscode", "vs", "code", "by", "pro",
    "lite", "free", "official", "app", "tool", "tools",
}


def strip_tagline(name: str) -> str:
    """'Elementor Website Builder \u2013 More Than Just a Page Builder' -> 'Elementor Website Builder'."""
    cut = re.split("\\s+[\u2013\u2014|-]\\s+|\\s*[:(\\[|]\\s*|\\s+[\u2013\u2014]", name, maxsplit=1)[0].strip()
    return cut or name.strip()


def norm_name(name: str) -> str:
    """Canonical name used to match the same product across sources."""
    base = strip_tagline(name or "")
    text = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in _NAME_NOISE]
    return " ".join(words) or re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


@dataclass
class Product:
    source: str
    source_id: str
    name: str
    url: str
    category: str | None = None
    user_count: int | None = None
    last_updated: str | None = None      # ISO date
    rating: float | None = None          # 0-5
    rating_count: int | None = None
    pricing_model: str = "unknown"
    license: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    homepage: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Evidence:
    source: str
    type: str
    url: str
    date_retrieved: str
    text: str | None = None
    date_posted: str | None = None
    metric_key: str | None = None
    metric_value: float | None = None
    metric_text: str | None = None
    score: int | None = None
    subject: str | None = None            # product name the evidence talks about
    product_ref: tuple[str, str] | None = None  # (source, source_id) when known
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence type {self.type!r}")
        if not self.url:
            raise ValueError("evidence needs a URL")
        if not self.date_retrieved:
            raise ValueError("evidence needs a retrieval date")


def metric(source: str, product: Product, key: str, value, url: str, retrieved: str,
           text: str | None = None, posted: str | None = None) -> Evidence | None:
    """A figure about a product, stored as evidence so it can be cited."""
    if value is None:
        return None
    numeric = value if isinstance(value, (int, float)) else None
    return Evidence(
        source=source, type="metric", url=url, date_retrieved=retrieved, date_posted=posted,
        metric_key=key, metric_value=numeric, metric_text=None if numeric is not None else str(value),
        text=text, subject=product.name, product_ref=(product.source, product.source_id),
    )


def upsert_product(conn: sqlite3.Connection, p: Product) -> int:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO products (source, source_id, name, norm_name, url, category, user_count,
            last_updated, rating, rating_count, pricing_model, license, description, tags,
            homepage, extra_json, first_seen, last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name=excluded.name, norm_name=excluded.norm_name, url=excluded.url,
            category=COALESCE(excluded.category, products.category),
            user_count=COALESCE(excluded.user_count, products.user_count),
            last_updated=COALESCE(excluded.last_updated, products.last_updated),
            rating=COALESCE(excluded.rating, products.rating),
            rating_count=COALESCE(excluded.rating_count, products.rating_count),
            pricing_model=CASE WHEN excluded.pricing_model='unknown' THEN products.pricing_model ELSE excluded.pricing_model END,
            license=COALESCE(excluded.license, products.license),
            description=COALESCE(excluded.description, products.description),
            tags=excluded.tags, homepage=COALESCE(excluded.homepage, products.homepage),
            extra_json=excluded.extra_json, last_seen=excluded.last_seen
        """,
        (p.source, p.source_id, p.name, norm_name(p.name), p.url, p.category, p.user_count,
         p.last_updated, p.rating, p.rating_count, p.pricing_model, p.license,
         (p.description or "")[:2000] or None, dumps(p.tags), p.homepage, dumps(p.extra), ts, ts),
    )
    row = conn.execute("SELECT id FROM products WHERE source=? AND source_id=?", (p.source, p.source_id)).fetchone()
    return row["id"]


def insert_evidence(conn: sqlite3.Connection, e: Evidence) -> tuple[int, bool]:
    """Insert or refresh one evidence row. Returns (id, created)."""
    product_id = None
    if e.product_ref:
        row = conn.execute("SELECT id, entity_id FROM products WHERE source=? AND source_id=?", e.product_ref).fetchone()
        if row:
            product_id = row["id"]
    # Metrics are re-observed every scan, so they are keyed without the value and refreshed.
    # A metric is identified by the product and the metric, not by the (shifting) listing URL it was read from.
    if e.type == "metric" and e.product_ref:
        uid = evidence_uid(e.source, "product:" + "/".join(e.product_ref), e.type, e.metric_key)
    elif e.type == "metric":
        uid = evidence_uid(e.source, "subject:" + (e.subject or ""), e.type, e.metric_key)
    else:
        uid = evidence_uid(e.source, e.url, e.type, e.metric_key, e.subject if e.type == "search_suggestion" else None)
    existing = conn.execute("SELECT id FROM evidence WHERE uid=?", (uid,)).fetchone()
    text = (e.text or "")[:4000] or None
    if existing:
        conn.execute(
            """UPDATE evidence SET metric_value=?, metric_text=?, text=COALESCE(?, text), date_retrieved=?, url=?,
               score=COALESCE(?, score), product_id=COALESCE(?, product_id), tags=?, extra_json=?
               WHERE id=?""",
            (e.metric_value, e.metric_text, text, e.date_retrieved, e.url, e.score, product_id,
             dumps(sorted(set(e.tags))), dumps(e.extra), existing["id"]),
        )
        return existing["id"], False
    cur = conn.execute(
        """INSERT INTO evidence (uid, product_id, subject, source, type, metric_key, metric_value,
           metric_text, text, url, date_posted, date_retrieved, score, tags, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, product_id, e.subject, e.source, e.type, e.metric_key, e.metric_value, e.metric_text,
         text, e.url, e.date_posted, e.date_retrieved, e.score, dumps(sorted(set(e.tags))), dumps(e.extra)),
    )
    return cur.lastrowid, True
