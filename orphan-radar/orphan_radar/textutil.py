"""Deterministic text heuristics. They tag evidence; they never invent facts."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def snippet(text: str | None, limit: int = 400) -> str:
    text = strip_html(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


# Displacement events. Each pattern must name the event, not just a mood.
EVENT_PATTERNS: dict[str, list[str]] = {
    "shutdown": [r"\bshut(ting)?\s?down\b", r"\bshuts down\b", r"\bdiscontinu(ed|ing|es)\b", r"\bclosing down\b",
                 r"\bwill (stop|cease) (working|operating)\b", r"\bend of life\b", r"\beol\b", r"\bkilled\b.*\b(app|service|product)\b"],
    "sunset": [r"\bsunset(ting|s)?\b", r"\bdeprecat(ed|ing|ion)\b", r"\bno longer (be )?(maintained|supported|developed)\b",
               r"\bunmaintained\b", r"\babandon(ed|ware)\b", r"\bthis (project|plugin|extension|repository) is archived\b"],
    "acquisition": [r"\bacquir(ed|es|ing)\b", r"\bacquisition\b", r"\bbought by\b", r"\bsold to\b"],
    "price_increase": [r"\bprice (increase|hike|rise)\b", r"\bpric(e|es|ing) (went|go|going|gone) up\b", r"\braised? (the |their )?prices?\b",
                       r"\b(more|too) expensive\b", r"\bnew pricing\b"],
    "free_tier_removed": [r"\b(no longer|not) free\b", r"\bremov(ed|ing|es) (the )?free\b", r"\bfree (tier|plan|version) (is )?(gone|removed|ended|discontinued)\b",
                          r"\b(now )?(requires|demanding|demands) (a )?(subscription|payment|paid plan)\b", r"\bpaywall(ed)?\b",
                          r"\bnow (a )?(paid|subscription)\b"],
    "platform_break": [r"\bstopped working (after|with|since)\b", r"\b(broke|broken|breaks) (after|with|since|on) (the )?(update|upgrade|version|firefox|chrome|wordpress|manifest)\b",
                       r"\bmanifest v3\b", r"\bmv3\b", r"\bincompatible with\b", r"\bnot compatible with\b", r"\bphp 8\b.*\b(error|fatal|broken)\b"],
}
_EVENT_RES = {k: [re.compile(p, re.I) for p in v] for k, v in EVENT_PATTERNS.items()}


def detect_events(text: str) -> list[str]:
    found = []
    for kind, patterns in _EVENT_RES.items():
        if any(p.search(text or "") for p in patterns):
            found.append(kind)
    return found


_NEGATIVE = re.compile(
    r"\b(doesn'?t work|does not work|not working|stopped working|broken|broke|crash(es|ed|ing)?|bug(gy|s)?|error|fail(s|ed|ing)?|"
    r"useless|terrible|awful|worst|garbage|slow|freez(es|ing)|disappoint(ed|ing)|uninstall(ed)?|waste|scam|annoying|"
    r"no (support|response|reply)|ignored|abandon(ed)?|outdated|deprecated|incompatible|missing|can'?t|cannot|won'?t|"
    r"lost (my|all)|data loss|deleted my|spam|ads|adware|tracking|malware|subscription|paywall)\b",
    re.I,
)


def is_negative(text: str | None, stars: int | None = None) -> bool:
    if stars is not None:
        return stars <= 2
    return bool(_NEGATIVE.search(text or ""))


_PAYING = re.compile(
    r"\b(i|we) (paid|pay|bought|purchased|subscribed)\b|\b(paid|pay|paying) (for|\$|\d)|\bpremium\b|\bpro version\b|\blicen[cs]e (key|fee)\b|"
    r"\brefund\b|\bsubscription\b|\$\s?\d+|\b\d+\s?(usd|eur|dollars)\b|\bper (month|year)\b|/\s?(mo|month|yr|year)\b",
    re.I,
)


def mentions_paying(text: str | None) -> bool:
    return bool(_PAYING.search(text or ""))


_INTENT = re.compile(
    r"\b(alternatives? (to|for)|replacement for|replace\b|is there (a|an|any) (tool|app|plugin|extension|way)|"
    r"looking for (a|an) (tool|app|plugin|extension|replacement|alternative)|switch(ed|ing)? (to|from)|migrat(e|ed|ing) (to|from)|"
    r"what (do|should) (you|i) use instead)",
    re.I,
)


def replacement_intent(text: str | None) -> bool:
    return bool(_INTENT.search(text or ""))


_EXPORT = re.compile(r"\b(export|import|backup|migrat\w+|csv|json|xml|opml|download (my|your) data)\b", re.I)


def mentions_export(text: str | None) -> bool:
    return bool(_EXPORT.search(text or ""))


# --- dates ------------------------------------------------------------------

def parse_date(value) -> datetime | None:
    """Accepts ISO strings, 'YYYY-MM-DD 3:14pm GMT' (WordPress), RFC 822 (RSS) and unix seconds."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2})(am|pm) GMT$", text, re.I)
    if m:
        hour = int(m.group(2)) % 12 + (12 if m.group(4).lower() == "pm" else 0)
        return datetime.fromisoformat(f"{m.group(1)}T{hour:02d}:{m.group(3)}:00+00:00")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def iso(value) -> str | None:
    dt = parse_date(value)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else None


def days_between(earlier, later=None) -> float | None:
    a = parse_date(earlier)
    if a is None:
        return None
    b = parse_date(later) if later else datetime.now(timezone.utc)
    return (b - a).total_seconds() / 86400


def version_tuple(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])
