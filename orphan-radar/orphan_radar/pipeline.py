"""Collect -> match -> detect -> cluster -> score -> filter -> brief. Safe to rerun at any point."""
from __future__ import annotations

import logging
import sqlite3
import time

from . import llm
from .adapters import Adapter, ScanContext, get_adapters
from .cluster import cluster_entity
from .config import Config, env
from .db import connect, dumps, now_iso
from .detect import detect
from .facts import EntityView
from .filters import hard_filters
from .matching import match_all
from .models import Evidence, Product, insert_evidence, upsert_product
from .net import HttpClient
from .score import score_entity
from .textutil import detect_events

log = logging.getLogger("orphan_radar")


def make_http(conn: sqlite3.Connection, config: Config, offline: bool = False, strict_robots: bool = False) -> HttpClient:
    h = config.section("http")
    return HttpClient(conn, h.get("user_agent", "OrphanRadar/0.1"), float(h.get("cache_ttl_hours", 20)),
                      float(h.get("min_interval_seconds", 1.0)), float(h.get("timeout_seconds", 30)),
                      offline=offline, strict_robots=strict_robots)


def store(conn: sqlite3.Connection, records, stats: dict) -> None:
    listing_ts: dict[tuple[str, str], str] = {}
    pending_desc: list[Product] = []
    for rec in records:
        if isinstance(rec, Product):
            upsert_product(conn, rec)
            stats["products"] += 1
            pending_desc.append(rec)
        elif isinstance(rec, Evidence):
            _, created = insert_evidence(conn, rec)
            stats["evidence_new" if created else "evidence_refreshed"] += 1
            if rec.product_ref and rec.type == "metric":
                listing_ts.setdefault(rec.product_ref, rec.date_retrieved)
        if stats["products"] % 50 == 0:
            conn.commit()
    # A listing whose own description announces a sunset/deprecation is an event in its own right.
    for p in pending_desc:
        kinds = detect_events(p.description or "")
        ts = listing_ts.get((p.source, p.source_id))
        if ts and p.description:
            # the listing's own description, stored so briefs can quote what the product does
            insert_evidence(conn, Evidence(source=p.source, type="metric", url=p.url, date_retrieved=ts, metric_key="description",
                                           metric_text=p.description[:600], text="Listing description",
                                           subject=p.name, product_ref=(p.source, p.source_id)))
        if kinds and ts:
            insert_evidence(conn, Evidence(source=p.source, type="event", url=p.url, date_retrieved=ts, text=p.description,
                                           subject=p.name, product_ref=(p.source, p.source_id),
                                           tags=[f"event:{k}" for k in kinds] + ["listing"]))
    conn.commit()


def run_adapter(conn, adapter: Adapter, ctx: ScanContext, stats: dict) -> None:
    ok, why = adapter.available()
    if not ok:
        log.info("skip %s: %s", adapter.name, why)
        stats["skipped"][adapter.name] = why
        return
    adapter.prepare(ctx.http)
    t0 = time.time()
    before = dict(stats)
    try:
        store(conn, adapter.collect(ctx), stats)
        stats["ran"][adapter.name] = {
            "products": stats["products"] - before["products"],
            "evidence_new": stats["evidence_new"] - before["evidence_new"],
            "evidence_refreshed": stats["evidence_refreshed"] - before["evidence_refreshed"],
            "seconds": round(time.time() - t0, 1)}
        log.info("%s: %s", adapter.name, stats["ran"][adapter.name])
    except Exception as exc:  # one broken source must not stop the scan
        conn.rollback()
        log.exception("%s failed", adapter.name)
        stats["failed"][adapter.name] = repr(exc)


def scan(config: Config, sources: list[str] | None = None, offline: bool = False, strict_robots: bool = False,
         use_llm: bool | None = None, conn: sqlite3.Connection | None = None, http: HttpClient | None = None) -> dict:
    conn = conn or connect(config.db_path)
    http = http or make_http(conn, config, offline=offline, strict_robots=strict_robots)
    adapters = get_adapters(sources)
    cur = conn.execute("INSERT INTO scans (started_at, sources) VALUES (?, ?)", (now_iso(), dumps([a.name for a in adapters])))
    scan_id = cur.lastrowid
    conn.commit()
    stats = {"products": 0, "evidence_new": 0, "evidence_refreshed": 0, "ran": {}, "skipped": {}, "failed": {}}
    ctx = ScanContext(conn=conn, http=http, config=config, log=log)
    for phase in (1, 2):
        batch = [a for a in adapters if a.phase == phase]
        if phase == 2 and batch:
            analyze(config, conn, scan_id=None, use_llm=False)  # rank candidates for the enrichment adapters
        for a in batch:
            run_adapter(conn, a, ctx, stats)
    result = analyze(config, conn, scan_id=scan_id, use_llm=use_llm)
    stats.update(result)
    stats["http_requests"], stats["cache_hits"] = http.requests_made, http.cache_hits
    conn.execute("UPDATE scans SET finished_at=?, status=?, stats_json=? WHERE id=?",
                 (now_iso(), "failed" if stats["failed"] and not stats["ran"] else "done", dumps(stats), scan_id))
    conn.commit()
    return stats


def analyze(config: Config, conn: sqlite3.Connection, scan_id: int | None = None, use_llm: bool | None = None) -> dict:
    """Recompute matching, signals, clusters, scores and filters from stored evidence. No network."""
    if use_llm is None:
        use_llm = llm.available()[0]
    match_all(conn)
    th = config.section("thresholds")
    window = int(th.get("recent_window_days", 365))
    ts = now_iso()
    n_scored = n_excluded = 0
    for (eid,) in conn.execute("SELECT id FROM entities").fetchall():
        v = EntityView.load(conn, eid, window)
        signals = detect(v, float(th.get("stale_months", 18)), float(th.get("event_fresh_days", 180)))
        for kind, s in signals.items():
            conn.execute("INSERT OR REPLACE INTO signals (entity_id, kind, strength, reasons_json, evidence_ids, computed_at) VALUES (?,?,?,?,?,?)",
                         (eid, kind, s.strength, dumps([{"text": r.text, "weight": r.weight,
                                                         "facts": [{"key": f.key, "value": f.value, "evidence_ids": f.evidence_ids} for f in r.facts]}
                                                        for r in s.reasons]), dumps(s.evidence_ids), ts))
        clusters = cluster_entity(conn, v, use_llm=use_llm and scan_id is not None)
        result = score_entity(v, signals, clusters, config)
        prev = conn.execute("SELECT total, components_json FROM scores WHERE entity_id=? ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
        comp_json = dumps(result)
        if scan_id is not None or prev is None or prev["components_json"] != comp_json:
            conn.execute("INSERT INTO scores (entity_id, scan_id, total, components_json, computed_at) VALUES (?,?,?,?,?)",
                         (eid, scan_id, result["total"], comp_json, ts))
        conn.execute("DELETE FROM exclusions WHERE entity_id=? AND rule != 'manual'", (eid,))
        for rule, reason, ev_id in hard_filters(v, config):
            conn.execute("INSERT OR REPLACE INTO exclusions (entity_id, rule, reason, evidence_id, computed_at) VALUES (?,?,?,?,?)",
                         (eid, rule, reason, ev_id, ts))
        if conn.execute("SELECT 1 FROM exclusions WHERE entity_id=?", (eid,)).fetchone():
            n_excluded += 1
        n_scored += 1
    conn.commit()
    return {"entities_scored": n_scored, "entities_excluded": n_excluded, "llm": bool(use_llm)}


def latest_scores(conn: sqlite3.Connection, include_excluded: bool = False) -> list[sqlite3.Row]:
    """Ranked entities with their latest score. Excluded ones are left out unless asked for."""
    where = "" if include_excluded else "WHERE e.id NOT IN (SELECT entity_id FROM exclusions)"
    return conn.execute(f"""
        SELECT e.id, e.name, s.total, s.components_json, s.computed_at,
               COALESCE(st.state, 'new') AS state,
               (SELECT group_concat(DISTINCT p.source) FROM products p WHERE p.entity_id=e.id) AS sources,
               (SELECT p.category FROM products p WHERE p.id=e.primary_product_id) AS category,
               (SELECT p.url FROM products p WHERE p.id=e.primary_product_id) AS url
        FROM entities e
        JOIN scores s ON s.id = (SELECT id FROM scores WHERE entity_id=e.id ORDER BY id DESC LIMIT 1)
        LEFT JOIN states st ON st.entity_id=e.id
        {where}
        ORDER BY s.total DESC
    """).fetchall()
