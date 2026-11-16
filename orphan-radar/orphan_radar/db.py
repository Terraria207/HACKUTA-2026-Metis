"""SQLite storage. One file, created on first use, safe to reopen and rerun."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    sources TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    stats_json TEXT NOT NULL DEFAULT '{}'
);

-- A product as listed on one source (one WordPress plugin, one GitHub repo, ...).
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    url TEXT NOT NULL,
    category TEXT,
    user_count INTEGER,
    last_updated TEXT,
    rating REAL,              -- normalised to 0-5
    rating_count INTEGER,
    pricing_model TEXT,       -- free | freemium | paid | unknown
    license TEXT,
    description TEXT,
    tags TEXT,                -- JSON list
    homepage TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}',
    entity_id INTEGER REFERENCES entities(id),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (source, source_id)
);

-- The same product matched across sources. Scores and briefs live at this level.
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL UNIQUE,
    primary_product_id INTEGER REFERENCES products(id),
    created_at TEXT NOT NULL
);

-- Every fact the tool knows. Figures are stored as metric_key/metric_value so
-- that every number in a score or brief can point at the row it came from.
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    product_id INTEGER REFERENCES products(id),
    entity_id INTEGER REFERENCES entities(id),
    subject TEXT,             -- product name the evidence talks about, before matching
    source TEXT NOT NULL,
    type TEXT NOT NULL,       -- metric | review | support_thread | issue | discussion | question | search_suggestion | event | price | license | export
    metric_key TEXT,
    metric_value REAL,
    metric_text TEXT,
    text TEXT,
    url TEXT NOT NULL,
    date_posted TEXT,
    date_retrieved TEXT NOT NULL,
    score INTEGER,            -- stars (1-5) or votes/points, depending on type
    tags TEXT,                -- JSON list of detector tags, e.g. ["negative", "event:shutdown"]
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_evidence_product ON evidence(product_id);
CREATE INDEX IF NOT EXISTS ix_evidence_entity ON evidence(entity_id);
CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence(subject);

CREATE TABLE IF NOT EXISTS signals (
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    kind TEXT NOT NULL,       -- abandonment | displacement | pain
    strength REAL NOT NULL,   -- 0..1
    reasons_json TEXT NOT NULL,
    evidence_ids TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, kind)
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    fix TEXT NOT NULL,
    summary TEXT,
    method TEXT NOT NULL,     -- rules | llm
    size INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE (entity_id, key)
);
CREATE TABLE IF NOT EXISTS cluster_evidence (
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id),
    PRIMARY KEY (cluster_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    scan_id INTEGER,
    total REAL NOT NULL,
    components_json TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_scores_entity ON scores(entity_id, computed_at);

CREATE TABLE IF NOT EXISTS exclusions (
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    rule TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_id INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, rule)
);

CREATE TABLE IF NOT EXISTS states (
    entity_id INTEGER PRIMARY KEY REFERENCES entities(id),
    state TEXT NOT NULL CHECK (state IN ('new', 'watching', 'building', 'dismissed')),
    note TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefs (
    entity_id INTEGER PRIMARY KEY REFERENCES entities(id),
    generated_at TEXT NOT NULL,
    score REAL,
    method TEXT NOT NULL,
    markdown TEXT NOT NULL,
    facts_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id),
    launched_name TEXT NOT NULL,
    launched_url TEXT,
    launched_at TEXT NOT NULL,
    visitors_30d INTEGER,
    trials_30d INTEGER,
    paying_30d INTEGER,
    revenue_30d REAL,
    notes TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',   -- score + signals at launch time
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    status INTEGER NOT NULL,
    content_type TEXT,
    body BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS skipped_sources (
    source TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def evidence_uid(source: str, url: str, type_: str, metric_key: str | None, subject: str | None = None) -> str:
    raw = "\x1f".join([source, url, type_, metric_key or "", (subject or "").lower()])
    return hashlib.sha1(raw.encode()).hexdigest()


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def loads(text, default=None):
    if text in (None, ""):
        return default
    return json.loads(text)
