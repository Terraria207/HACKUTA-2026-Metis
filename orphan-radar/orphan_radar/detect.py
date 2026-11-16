"""The three signals: abandonment, displacement, pain density. Each is 0..1 with reasons,
and each reason carries the Facts (and therefore the evidence ids) behind it."""
from __future__ import annotations

from dataclasses import dataclass, field

from .facts import EntityView, Fact
from .textutil import days_between, version_tuple

SIGNAL_PRESENT = 0.35
STRONG_EVENT_KINDS = {"shutdown", "sunset", "free_tier_removed", "acquisition", "price_increase"}
# A single reviewer's claim is weak; listings, maintainers, HN stories and multiple reviewers are strong.
STRONG_EVENT_TYPES = {"event", "discussion"}


@dataclass
class Reason:
    text: str                      # human sentence; figures in it are given by `facts`
    facts: list[Fact] = field(default_factory=list)
    weight: float = 0.0


@dataclass
class Signal:
    kind: str
    strength: float
    reasons: list[Reason]

    @property
    def present(self) -> bool:
        return self.strength >= SIGNAL_PRESENT

    @property
    def evidence_ids(self) -> list[int]:
        return sorted({i for r in self.reasons for f in r.facts for i in f.evidence_ids})


def wp_releases_behind(tested: str | None, current: str | None) -> int | None:
    """WordPress majors go x.0 .. x.9 then (x+1).0, so 6.8 -> 7.1 is 3 releases."""
    t, c = version_tuple(tested), version_tuple(current)
    if len(t) < 2 or len(c) < 2:
        return None
    return max(0, (c[0] * 10 + c[1]) - (t[0] * 10 + t[1]))


def months_since(date_value) -> float | None:
    d = days_between(date_value)
    return None if d is None else d / 30.44


def abandonment(v: EntityView, stale_months: float) -> Signal:
    reasons: list[Reason] = []
    score = 0.0
    last = v.last_update()
    if last:
        m = months_since(last.value)
        if m is not None:
            frac = min(m / stale_months, 1.0)
            score += 0.5 * frac
            reasons.append(Reason("months since last update", [last, Fact("months_since_update", round(m), last.evidence_ids, derived=True)], frac))
    opened, resolved = v.metric("support_threads_recent"), v.metric("support_threads_resolved")
    if opened and resolved is not None and resolved.value is not None and opened.value and opened.value >= 3:
        share = max(0.0, (opened.value - resolved.value) / opened.value)
        score += 0.2 * share
        reasons.append(Reason("support threads opened vs resolved in the last two months", [opened, resolved,
                       Fact("unresolved_share", f"{round(share * 100)}%", opened.evidence_ids + resolved.evidence_ids, derived=True)], share))
    unanswered = v.recent(v.tagged("unanswered", v.of_type("support_thread")))
    if len(unanswered) >= 3:
        frac = min(len(unanswered) / 10, 1.0)
        score += 0.1 * frac
        reasons.append(Reason("recent support threads with zero replies", [Fact("unanswered_threads", len(unanswered), [e["id"] for e in unanswered], derived=True)], frac))
    tested, current = v.metric("tested_up_to", prefer="primary"), v.metric("platform_current_version", prefer="primary")
    if tested and current:
        behind = wp_releases_behind(str(tested.value), str(current.value))
        if behind:
            frac = 1.0 if behind >= 3 else behind / 3
            score += 0.2 * frac
            reasons.append(Reason("WordPress releases behind the current version (WordPress.org shows a warning from three)", [tested, current,
                           Fact("releases_behind", behind, tested.evidence_ids + current.evidence_ids, derived=True)], frac))
    archived = [e for e in v.of_type("event") if "archived" in e["tag_list"]]
    if archived:
        score = max(score, 0.9)
        reasons.append(Reason("repository archived by its owner", [Fact("archived", "archived", [e["id"] for e in archived])], 1.0))
    return Signal("abandonment", round(min(score, 1.0), 3), reasons)


def displacement(v: EntityView, fresh_days: float) -> Signal:
    by_kind: dict[str, list[dict]] = {}
    for e in v.tagged_prefix("event:"):
        for t in e["tag_list"]:
            if t.startswith("event:"):
                by_kind.setdefault(t.split(":", 1)[1], []).append(e)
    reasons, score = [], 0.0
    for kind, rows in sorted(by_kind.items()):
        strong_rows = [e for e in rows if e["type"] in STRONG_EVENT_TYPES]
        if strong_rows or len(rows) >= 2:
            base = 1.0 if kind in STRONG_EVENT_KINDS else 0.6
        else:
            base = 0.4 if kind in STRONG_EVENT_KINDS else 0.25
        dated = [e for e in rows if e["date_posted"]]
        latest = max(dated, key=lambda e: e["date_posted"]) if dated else None
        facts = [Fact(f"event_{kind}", kind.replace("_", " "), [e["id"] for e in rows]),
                 Fact("event_mentions", len(rows), [e["id"] for e in rows], derived=True)]
        if latest:
            facts.append(Fact("event_date", latest["date_posted"][:10], [latest["id"]]))
        score = max(score, base)
        reasons.append(Reason(f"{kind.replace('_', ' ')} mentioned", facts, base))
    return Signal("displacement", round(min(score, 1.0), 3), reasons)


def pain(v: EntityView) -> Signal:
    complaints = v.complaints(recent_only=True)
    reasons, score = [], 0.0
    if complaints:
        frac = min(len(complaints) / 10, 1.0)
        score += 0.7 * frac
        reasons.append(Reason("recent complaints (low-star reviews, negative threads, issues)",
                              [Fact("recent_complaints", len(complaints), [e["id"] for e in complaints], derived=True)], frac))
    issues = [e for e in v.of_type("issue") if (e["score"] or 0) >= 20]
    if issues:
        top = max(issues, key=lambda e: e["score"])
        frac = min(top["score"] / 200, 1.0)
        score += 0.3 * frac
        reasons.append(Reason("most-reacted open issue", [Fact("top_issue_reactions", top["score"], [top["id"]])], frac))
    rating, recent = v.metric("rating", prefer="primary"), v.metric("rating_recent")
    if not recent:
        recent = recent_review_average(v)
    if rating and recent and isinstance(rating.value, (int, float)) and recent.value < rating.value - 0.4:
        drop = rating.value - recent.value
        score += min(drop / 2, 0.3)
        reasons.append(Reason("recent rating below lifetime rating", [rating, recent], drop))
    return Signal("pain", round(min(score, 1.0), 3), reasons)


def recent_review_average(v: EntityView) -> Fact | None:
    """Average stars of reviews posted inside the window, when at least 5 exist (WordPress feeds)."""
    rows = [e for e in v.recent(v.of_type("review")) if e["score"]]
    if len(rows) < 5:
        return None
    avg = round(sum(e["score"] for e in rows) / len(rows), 2)
    return Fact("rating_recent", avg, [e["id"] for e in rows], f"average of {len(rows)} reviews posted in the last {v.window_days} days", derived=True)


def detect(v: EntityView, stale_months: float = 18, fresh_days: float = 180) -> dict[str, Signal]:
    return {"abandonment": abandonment(v, stale_months), "displacement": displacement(v, fresh_days), "pain": pain(v)}
