"""Match the same product across sources and attach free-floating evidence to it.

Rules, chosen to prefer missing a match over making a wrong one:
- Products with the same canonical name are the same entity, unless the name is generic
  (every word is a common English/software word), in which case each source keeps its own entity.
- Evidence that names no product (Hacker News / Stack Exchange sweeps) attaches to an entity only
  when that entity's distinctive name appears in the text as a whole word. Single-word names
  must appear with the same capitalisation as the product's own name.
"""
from __future__ import annotations

import re
import sqlite3

from .db import loads, now_iso
from .models import norm_name, strip_tagline

GENERIC = set("""
a an all in one seo cache caching backup security editor classic block blocks gallery slider form forms contact
social share sharing analytics google maps map image images photo photos video videos media popup popups
custom fields post posts page pages user users login admin menu menus widget widgets theme themes table tables
calendar events event booking shop store cart checkout payment payments email mail newsletter smtp spam comment
comments search sitemap redirect redirection translate translation language dark mode reader tab tabs bookmark
bookmarks download downloader manager password passwords privacy ad ads blocker block adblock tracker video speed
controller translator screenshot screen color picker notes note todo dictionary weather clock timer music player
new simple easy best ultimate advanced lite basic smart quick fast super top better auto automatic
duplicate duplicator import export migration migrate optimize optimizer optimization image compress lazy load
code snippets snippet header footer scripts insert git json yaml markdown python java javascript react vue icons
theme light night history session sessions proxy vpn
""".split())

COMMON_SINGLE_WORDS = GENERIC | set("""
atom stylus pocket reader keeper buffer feed feeds proxy wallet notion slack dash dashboard redux yarn grunt
gulp bower request moment express hammer sketch
""".split())


def is_distinctive(norm: str) -> bool:
    words = norm.split()
    if not words:
        return False
    if all(w in GENERIC for w in words):
        return False
    if len(words) == 1 and (len(words[0]) < 5 or words[0] in COMMON_SINGLE_WORDS):
        return False
    return True


def entity_key(norm: str, source: str, name: str = "") -> str:
    """Same key = same product. Multi-word names merge across sources even when the words are
    common ("Dark Reader"); a single generic word ("Gallery") stays per source."""
    if is_distinctive(norm) or len(strip_tagline(name).split()) >= 2:
        return norm
    return f"{norm}@{source}"


def _ensure_entity(conn: sqlite3.Connection, key: str, name: str, product_id: int) -> int:
    row = conn.execute("SELECT id FROM entities WHERE norm_name=?", (key,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO entities (name, norm_name, primary_product_id, created_at) VALUES (?,?,?,?)",
                       (name, key, product_id, now_iso()))
    return cur.lastrowid


def _name_pattern(name: str, norm: str) -> re.Pattern | None:
    """A regex that finds the product's name in free text, or None if the name is too generic.

    - distinctive multi-word names ("Yoast SEO"): case-insensitive phrase
    - common-word phrases ("Dark Reader", "WP Super Cache"): the product's own spelling, exact case
    - distinctive single words ("Bitwarden"): exact case
    - generic single words ("Gallery", "Pocket"): never matched from free text
    """
    raw = strip_tagline(name)
    raw_words = [w for w in re.split(r"\s+", raw) if w]
    sep = r"[\s\-_.]*"
    if len(raw_words) >= 2:
        alternatives = []
        brand = re.sub(r"[^\w.+-]", "", raw_words[0])
        if len(brand) >= 6 and brand[:1].isupper() and brand.lower() not in COMMON_SINGLE_WORDS and brand.lower() not in ("google", "wordpress", "firefox", "mozilla", "microsoft", "simple", "custom", "advanced", "social", "ultimate"):
            alternatives.append(re.escape(brand))  # "Wordfence Security" is also written "Wordfence"
        distinctive = is_distinctive(norm)
        if len(raw_words) <= 5 and (distinctive or any(w[:1].isupper() for w in raw_words)):
            phrase = sep.join(re.escape(w) for w in raw_words)
            alternatives.append(phrase if not distinctive else "(?i:" + phrase + ")")
        if not alternatives:
            return None
        return re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])")
    if not is_distinctive(norm):
        return None
    token = raw_words[0] if raw_words else ""
    if len(token) < 5:
        return None
    return re.compile(rf"(?<![\w-]){re.escape(token)}(?![\w-])")


def match_all(conn: sqlite3.Connection) -> dict:
    stats = {"entities": 0, "products": 0, "evidence_attached": 0}
    # 1. products -> entities. The entity takes the name of its largest listing.
    rows = conn.execute("SELECT id, source, name, norm_name, user_count, extra_json FROM products ORDER BY COALESCE(user_count,0) DESC, id").fetchall()
    for r in rows:
        key = entity_key(r["norm_name"], r["source"], r["name"])
        eid = _ensure_entity(conn, key, r["name"], r["id"])
        conn.execute("UPDATE products SET entity_id=? WHERE id=?", (eid, r["id"]))
        stats["products"] += 1
    # Primary product = the listing with the biggest audience (users, else stars/downloads).
    for e in conn.execute("SELECT id FROM entities").fetchall():
        best = conn.execute(
            """SELECT p.id, p.name FROM products p WHERE p.entity_id=?
               ORDER BY COALESCE(p.user_count, 0) DESC,
                        COALESCE(json_extract(p.extra_json,'$.stars'), json_extract(p.extra_json,'$.downloads'), 0) DESC
               LIMIT 1""", (e["id"],)).fetchone()
        if best:
            conn.execute("UPDATE entities SET primary_product_id=?, name=? WHERE id=?", (best["id"], best["name"], e["id"]))
    stats["entities"] = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    # 2. evidence with a product -> that product's entity
    conn.execute("""UPDATE evidence SET entity_id=(SELECT entity_id FROM products WHERE products.id=evidence.product_id)
                    WHERE product_id IS NOT NULL""")

    # 3. evidence that names a subject or nothing -> entity whose name appears in the text
    entities = conn.execute("SELECT e.id, e.name, e.norm_name FROM entities e").fetchall()
    patterns = []
    for e in entities:
        pat = _name_pattern(e["name"], e["norm_name"].split("@")[0])
        if pat:
            patterns.append((e["id"], pat, e["norm_name"]))
    by_norm = {e["norm_name"]: e["id"] for e in entities}
    loose = conn.execute("SELECT id, subject, text, extra_json FROM evidence WHERE product_id IS NULL").fetchall()
    for ev in loose:
        extra = loads(ev["extra_json"], {})
        target = extra.get("entity_id")  # autocomplete records know their entity already
        if target is None and ev["subject"]:
            # subject given by a targeted search: still require the name to appear in the text
            sub_norm = norm_name(ev["subject"])
            cand = by_norm.get(sub_norm)
            pat = next((p for i, p, _ in patterns if i == cand), None)
            if cand and pat and pat.search(ev["text"] or ""):
                target = cand
        if target is None:
            hits = [i for i, pat, _ in patterns if pat.search(ev["text"] or "")]
            if len(hits) == 1:  # ambiguous mentions of several products stay unattached
                target = hits[0]
        conn.execute("UPDATE evidence SET entity_id=? WHERE id=?", (target, ev["id"]))
        if target is not None:
            stats["evidence_attached"] += 1
    conn.commit()
    return stats
