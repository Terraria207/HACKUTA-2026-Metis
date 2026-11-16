"""Hard filters. An excluded product is never ranked; it is listed separately with the reason."""
from __future__ import annotations

import re

from .facts import EntityView
from .textutil import word_hits

_SUCCESSOR = re.compile(r"\b(use|try|switch to|migrate to|moved to|replaced by|superseded by|successor[: ]|deprecated in favou?r of|continued (at|as|in)|has moved to|is now part of)\b", re.I)
_NATIVE = re.compile(r"\b(now (built[- ]in|native|part of (wordpress|firefox|core|vs ?code))|merged into (core|wordpress|firefox)|"
                     r"(wordpress|firefox|vs ?code) (now )?(has|includes|ships|supports) (this|it) natively|no longer needed)\b", re.I)


# Users saying the platform already does the job. Positive phrasings only ("can be done natively in Firefox"),
# not wishes ("should be built into WordPress") or availability elsewhere ("available in Chrome").
NATIVE_CLAIM = re.compile(r"\b(can be done|is done|works|now works|you can do (it|this|that)) (natively |already )?in (firefox|wordpress|chrome|vs ?code)( natively| itself| anyway| anyways| now)?\b|"
                          r"\bnatively in (firefox|wordpress|chrome|vs ?code|core)\b|"
                          r"\b(firefox|wordpress|chrome|vs ?code) (now |already )?(does|has|can do) (this|it|that) (natively|built[- ]in|itself|out of the box)\b", re.I)


def native_claims(v) -> list[dict]:
    return [e for e in v.evidence if e["text"] and e["type"] in ("review", "support_thread", "discussion", "issue", "question") and NATIVE_CLAIM.search(e["text"])]


def _word_hit(words: list[str], text: str) -> str | None:
    hits = word_hits(words, text)
    return hits[0] if hits else None


def hard_filters(v: EntityView, config) -> list[tuple[str, str, int | None]]:
    """Returns [(rule, reason, evidence_id)]. Empty = passes."""
    hf = config.section("hard_filters")
    out: list[tuple[str, str, int | None]] = []
    p = v.primary or {}
    listing = v.listing_text()
    url = p.get("url", "")

    def first_metric_id():
        rows = v.metric_rows("user_count") + v.metric_rows("github_stars") + v.metric_rows("downloads")
        return rows[0]["id"] if rows else None

    for rule, key, what in (("sensitive_data", "health", "health data"), ("sensitive_data", "financial", "financial-account data"),
                            ("sensitive_data", "children", "children's data")):
        hit = _word_hit(hf.get(key, []), listing)
        if hit:
            out.append((f"{rule}:{key}", f"Handles {what}: the listing at {url} mentions '{hit}'.", first_metric_id()))
    hit = _word_hit(hf.get("licensed", []), listing)
    if hit:
        out.append(("needs_license_or_hardware", f"Needs a license, partnership, hardware or approval: the listing at {url} mentions '{hit}'.", first_metric_id()))
    hit = _word_hit(hf.get("trademark_or_proprietary", []), p.get("name") or "")
    if hit:
        out.append(("trademark_or_proprietary", f"Depends on another company's trademark or proprietary service: the listing at {url} mentions '{hit}'.", first_metric_id()))

    desc = " ".join(filter(None, [q.get("description") for q in v.products]))
    if desc and _SUCCESSOR.search(desc) and re.search(r"\b(deprecated|archived|no longer|unmaintained|discontinued|moved)\b", desc, re.I):
        out.append(("replacement_dominates", f"The maintainers point users to a maintained successor: \"{desc[:200]}\"", first_metric_id()))
    native = [e for e in v.evidence if e["text"] and _NATIVE.search(e["text"]) and e["type"] in ("event", "discussion", "metric")]
    claims = native_claims(v)
    if desc and _NATIVE.search(desc):
        out.append(("platform_native", f"The listing says the platform now does this natively: \"{desc[:200]}\"", first_metric_id()))
    elif native:
        out.append(("platform_native", f"A discussion says the platform now does this natively: {native[0]['url']}", native[0]["id"]))
    elif len(claims) >= 2:  # one reviewer is a risk note in the brief; two independent ones exclude
        out.append(("platform_native", f"{len(claims)} users say the platform already does this natively, e.g. {claims[0]['url']}", claims[0]["id"]))

    min_users = int(config.threshold("min_users", 1000))
    aud, proxy = v.audience()
    if aud is None:
        out.append(("too_small", "No verifiable user count, star count or download count.", None))
    elif isinstance(aud.value, (int, float)) and aud.value < min_users:
        kind = "audience proxy (stars/downloads)" if proxy else "users"
        out.append(("too_small", f"{aud.value} {kind}, below the {min_users} minimum.", aud.evidence_ids[0]))
    return out
