"""Shared test helpers: an in-memory database, a config, and a tiny synthetic product."""
from __future__ import annotations

import copy
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orphan_radar.config import ROOT, Config, load_config
from orphan_radar.db import connect
from orphan_radar.models import Evidence, Product, insert_evidence, upsert_product

FIXTURES = Path(__file__).parent / "fixtures"
TS = "2026-11-16T12:00:00+00:00"


def config(**overrides) -> Config:
    base = load_config(ROOT / "config.toml")
    raw = copy.deepcopy(base.raw)
    for dotted, value in overrides.items():
        section, key = dotted.split(".")
        raw.setdefault(section, {})[key] = value
    return Config(raw=raw, path=base.path, data_dir=base.data_dir)


def memdb() -> sqlite3.Connection:
    return connect(":memory:")


def days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).replace(microsecond=0).isoformat()


def add_plugin(conn, slug="old-gallery-pro", name="Old Gallery Pro", users=200_000, updated_days=900, rating=3.1,
               rating_count=850, tested="6.2", core="7.1.4", opened=12, resolved=1, business_model="commercial",
               complaints: list[tuple[str, int]] | None = None, description="Gallery grids and lightboxes for posts."):
    """A WordPress-like product with its metrics and some reviews, stored as real evidence rows."""
    p = Product(source="wordpress", source_id=slug, name=name, url=f"https://wordpress.org/plugins/{slug}/",
                category="wordpress-plugin", user_count=users, last_updated=days_ago(updated_days), rating=rating,
                rating_count=rating_count, pricing_model="freemium", license="GPL-compatible (WordPress.org directory requirement)",
                description=description)
    upsert_product(conn, p)
    api = f"https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&slug={slug}"
    ref = ("wordpress", slug)
    metrics = [("user_count", users), ("rating", rating), ("rating_count", rating_count), ("last_updated", days_ago(updated_days)),
               ("tested_up_to", tested), ("platform_current_version", core), ("support_threads_recent", opened),
               ("support_threads_resolved", resolved), ("business_model", business_model),
               ("license", "GPL-compatible (WordPress.org directory requirement)"), ("description", description)]
    for key, value in metrics:
        num = value if isinstance(value, (int, float)) else None
        insert_evidence(conn, Evidence(source="wordpress", type="metric", url=api, date_retrieved=TS, metric_key=key,
                                       metric_value=num, metric_text=None if num is not None else str(value), subject=name, product_ref=ref))
    for n, (text, stars) in enumerate(complaints or []):
        insert_evidence(conn, Evidence(source="wordpress", type="review", url=f"https://wordpress.org/support/topic/{slug}-review-{n}/",
                                       date_retrieved=TS, date_posted=days_ago(20 + n), text=text, score=stars, subject=name,
                                       product_ref=ref, tags=["negative"] if stars <= 2 else []))
    conn.commit()
    return p


COMPLAINTS = [
    ("Stopped working after the WordPress 6.5 update, fatal error on every page", 1),
    ("Fatal error with PHP 8.2, incompatible with the latest WordPress", 1),
    ("Not compatible with the block editor anymore, broke after update", 2),
    ("They moved the lightbox behind a paywall, now requires a subscription. I paid $49 last year.", 1),
    ("Pro version upsell everywhere, the free version is crippled and limited", 2),
    ("Way too slow, my page speed dropped and CPU usage is high", 2),
    ("Lost all my galleries after the update, settings reset", 1),
    ("No reply from support in months, the plugin looks abandoned", 1),
]
