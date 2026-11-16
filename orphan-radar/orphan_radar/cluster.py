"""Group recent complaints into concrete, fixable problems.

Rules always run (no key needed). When a language model is configured it may regroup and
relabel the same complaints; its output is accepted only if every cluster cites evidence ids
from the input and contains no number absent from that evidence. Otherwise the rule result stands.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import llm
from .db import now_iso
from .facts import EntityView

# key: (label, fix, patterns). Order is the tie-break priority.
TAXONOMY: list[tuple[str, str, str, list[str]]] = [
    ("compat", "Broken by a platform, browser or PHP update", "Works on the current platform release and PHP version",
     [r"(stopped|stop|not|isn'?t|doesn'?t) work\w* (after|since|with) (the )?(update|upgrade|latest|new version|wordpress|firefox|php)",
      r"\bincompatib", r"\bnot compatible\b", r"\bphp ?[78]", r"\bwordpress [5-7]\.\d", r"\bfirefox \d{3}", r"\bmanifest v?3\b", r"\bdeprecated\b.*\b(function|warning|notice)\b",
      r"\bblock editor\b|\bgutenberg\b", r"\bfatal error\b"]),
    ("not_working", "Stopped doing its core job on many sites or setups", "Does its core job reliably on today's sites and setups",
     [r"\b(doesn'?t|does not|didn'?t|won'?t|no longer|not) work(s|ing)?\b", r"\bstopped working\b", r"\bnot working\b", r"\buseless\b", r"\bunusable\b",
      r"\bbroke (my|the) (website|site|page)\b", r"\bno longer (does|blocks|removes|shows)\b", r"\bnützt nichts\b", r"\bfunktioniert nicht\b", r"\bne fonctionne plus\b",
      r"\bn'?est plus (aussi )?efficace\b", r"\bon (many|most|lots of) (sites|websites|pages)\b"]),
    ("paywall", "Features moved behind a paywall or subscription", "Core features free, or a fair one-time price",
     [r"\bpaywall", r"\bsubscription\b", r"\b(now|became) (paid|premium)\b", r"\bpay (to|for)\b", r"\bpremium (only|version)\b", r"\bupsell", r"\bpro version\b",
      r"\bno longer free\b", r"\bfree version\b.*\b(limited|useless|crippled)\b", r"\b(wait|waiting) \d+ (hours|minutes)\b", r"\bprice\b",
      r"\bupgrade\b.*\b(paid|plan|package|pro|premium|credit)", r"\bcredits?\b", r"\bfree (\w+ )?limit\b", r"\bpaid package\b", r"\bcheated\b", r"\$\s?\d+"]),
    ("data_loss", "Lost data or settings", "Never loses data: safe upgrades, backups, undo",
     [r"\blost (all|my|our)\b", r"\b(deleted|wiped|erased) (all|my|our)\b", r"\bdata loss\b", r"\bsettings (reset|gone|lost)\b", r"\bdisappeared\b", r"\bgone\b.*\b(bookmarks|data|settings|notes)\b"]),
    ("crash", "Crashes, errors and broken pages", "Stable core with error handling and a test suite",
     [r"\bcrash", r"\berror\b", r"\bwhite screen\b", r"\b500\b", r"\bbroke(n)? (my|the) (site|page|layout)\b", r"\bfreez", r"\bhangs?\b", r"\bbug(gy|s)?\b"]),
    ("performance", "Slow, heavy or resource-hungry", "Lightweight and fast: lazy work, no bloat",
     [r"\bslow", r"\bheavy\b", r"\bbloat", r"\bcpu\b", r"\bmemory\b", r"\bram\b", r"\blag", r"\bperformance\b", r"\bpage ?speed\b", r"\bload(ing)? time\b"]),
    ("ads_privacy", "Ads, tracking, or distrust of a new owner", "No ads, no tracking, transparent ownership, open source",
     [r"\bads?\b", r"\badvert", r"\btracking\b", r"\btelemetry\b", r"\bspyware\b", r"\bmalware\b", r"\bprivacy\b", r"\bnag", r"\bpopups?\b.*\b(annoying|constant|every)\b", r"\bspam",
      r"\bsold (it|his|her|the|our|to)\b", r"\bowned by\b", r"\bour data\b", r"\bdata being handled\b", r"\bnew owner"]),
    ("ui_regression", "Redesign removed or worsened a feature people used", "Restores the removed workflow; no forced redesigns",
     [r"\bbring back\b", r"\bold version\b", r"\bnew (ui|interface|version|design|update)\b.*\b(worse|terrible|awful|confusing|hate)\b", r"\bremoved (the|a|my)?\s?\w*\s?(feature|option|button)",
      r"\bno longer (has|have|shows?|allows?|supports?)\b", r"\bwhere (is|did) (the )?\w+ go\b", r"\bdowngrad"]),
    ("sync_login", "Breaks or fails at sign-in, sync or accounts", "Never breaks sign-in or sync (its own or on the sites it touches); no account needed",
     [r"\bsync", r"\blog ?in\b", r"\bsign ?in\b", r"\baccount\b", r"\bauthenticat", r"\blogged out\b", r"\bapi key\b"]),
    ("import_export", "Cannot import, export or migrate data", "Open formats with one-click import and export",
     [r"\bimport", r"\bexport", r"\bmigrat", r"\bbackup", r"\bcsv\b", r"\bjson\b", r"\bxml\b"]),
    ("support", "No answer from the developer or support", "Responsive public issue tracker",
     [r"\bno (reply|response|answer|support)\b", r"\bnever (replied|responded|answered)\b", r"\bignored\b", r"\babandon", r"\bdead (plugin|project|extension)\b", r"\bunmaintained\b", r"\bnot maintained\b",
      r"\bsupport (is )?(useless|terrible|non-?existent)\b"]),
    ("missing_feature", "A specific feature is missing", "Adds the requested feature",
     [r"\bplease add\b", r"\bfeature request\b", r"\bwould be (nice|great)\b", r"\bwish (it|there)\b", r"\bdoesn'?t (support|have|allow)\b", r"\bno (option|way|setting) to\b", r"\bcan'?t (choose|set|change|disable)\b",
      r"\b(add|need|want) (an? )?(option|support|setting)\b", r"\bcan'?not turn off\b", r"\bno (auto|option|setting)\w*\b"]),
]
_COMPILED = [(k, label, fix, [re.compile(p, re.I) for p in pats]) for k, label, fix, pats in TAXONOMY]


@dataclass
class Cluster:
    key: str
    label: str
    fix: str
    evidence_ids: list[int] = field(default_factory=list)
    summary: str | None = None
    method: str = "rules"

    @property
    def size(self) -> int:
        return len(self.evidence_ids)


def classify(text: str) -> str | None:
    best, best_hits = None, 0
    for key, _, _, pats in _COMPILED:
        hits = sum(1 for p in pats if p.search(text))
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def rule_clusters(complaints: list[dict]) -> list[Cluster]:
    meta = {k: (label, fix) for k, label, fix, _ in TAXONOMY}
    buckets: dict[str, list[int]] = {}
    for e in complaints:
        key = classify(e["text"] or "") or "other"
        buckets.setdefault(key, []).append(e["id"])
    out = []
    for key, ids in buckets.items():
        label, fix = meta.get(key, ("Other complaints (not specific enough to act on)", "unknown"))
        out.append(Cluster(key, label, fix, ids))
    out.sort(key=lambda c: (c.key == "other", -c.size))
    return out


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "the concrete problem, under 12 words"},
                    "fix": {"type": "string", "description": "the feature or fix that would remove it, under 12 words"},
                    "summary": {"type": "string", "description": "one sentence restating what the cited complaints say"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["label", "fix", "summary", "evidence_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


def llm_clusters(product: str, complaints: list[dict]) -> list[Cluster] | None:
    if not complaints:
        return []
    items = "\n".join(f"[{e['id']}] {(e['text'] or '')[:500]}" for e in complaints[:80])
    prompt = (
        f"Complaints about {product}. Group them into at most 6 concrete problems that a developer could fix. "
        "Every complaint id must appear in exactly one cluster; put vague ones in a cluster labelled 'Other'. "
        f"Use only what the complaints say.\n\n{items}"
    )
    try:
        data = llm.complete_json(prompt, LLM_SCHEMA)
    except llm.LLMError:
        return None
    by_id = {e["id"]: e for e in complaints}
    out, used = [], set()
    for c in data.get("clusters", []):
        ids = [i for i in c.get("evidence_ids", []) if i in by_id and i not in used]
        if not ids:
            continue
        sources = [by_id[i]["text"] or "" for i in ids]
        text = " ".join([c.get("label", ""), c.get("fix", ""), c.get("summary", "")])
        if llm.ungrounded_numbers(text, sources):
            return None  # grounding rule violated: discard the whole LLM answer
        used.update(ids)
        is_other = c.get("label", "").strip().lower().startswith("other")
        out.append(Cluster("other" if is_other else f"llm{len(out)}", c["label"].strip(), c.get("fix", "unknown").strip() or "unknown",
                           ids, c.get("summary"), "llm"))
    missing = [i for i in by_id if i not in used]
    if missing:
        other = next((c for c in out if c.key == "other"), None)
        if other:
            other.evidence_ids += missing
        else:
            out.append(Cluster("other", "Other complaints (not specific enough to act on)", "unknown", missing, method="llm"))
    out.sort(key=lambda c: (c.key == "other", -c.size))
    return out


def cluster_entity(conn: sqlite3.Connection, view: EntityView, use_llm: bool) -> list[Cluster]:
    complaints = view.complaints(recent_only=True)
    clusters = None
    if use_llm:
        clusters = llm_clusters(view.name, complaints)
    if clusters is None:
        clusters = rule_clusters(complaints)
    conn.execute("DELETE FROM clusters WHERE entity_id=?", (view.id,))
    ts = now_iso()
    for c in clusters:
        cur = conn.execute(
            "INSERT INTO clusters (entity_id, key, label, fix, summary, method, size, computed_at) VALUES (?,?,?,?,?,?,?,?)",
            (view.id, c.key, c.label, c.fix, c.summary, c.method, c.size, ts))
        conn.executemany("INSERT OR IGNORE INTO cluster_evidence (cluster_id, evidence_id) VALUES (?,?)",
                         [(cur.lastrowid, i) for i in c.evidence_ids])
    return clusters


def load_clusters(conn: sqlite3.Connection, entity_id: int) -> list[Cluster]:
    out = []
    for r in conn.execute("SELECT * FROM clusters WHERE entity_id=? ORDER BY key='other', size DESC", (entity_id,)):
        ids = [x[0] for x in conn.execute("SELECT evidence_id FROM cluster_evidence WHERE cluster_id=?", (r["id"],))]
        out.append(Cluster(r["key"], r["label"], r["fix"], ids, r["summary"], r["method"]))
    return out
