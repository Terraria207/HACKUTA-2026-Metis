"""Score 0-100 from six weighted components. Every component reports its points, its maximum
and the reasons (with the Facts behind them), so the breakdown is always shown and traceable.

Each component computes a fraction 0..1 from sub-parts; points = fraction x weight from config.toml.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cluster import Cluster
from .detect import Reason, Signal, months_since
from .facts import EntityView, Fact
from .textutil import days_between, word_hits

LISTING_MARKETPLACES = {"wordpress", "firefox", "openvsx", "atlassian"}


@dataclass
class Component:
    name: str
    weight: float
    fraction: float = 0.0
    parts: list[tuple[str, float, float, list[Fact]]] = field(default_factory=list)  # (label, got, max, facts)

    def add(self, label: str, got: float, maximum: float, facts: list[Fact] | None = None):
        # maximum == 0 marks a penalty: it can only subtract, and does not enlarge the denominator
        got = min(0.0, got) if maximum == 0 else max(0.0, min(got, maximum))
        self.parts.append((label, round(got, 3), maximum, facts or []))

    def finish(self):
        total_max = sum(m for _, _, m, _ in self.parts if m > 0) or 1
        self.fraction = max(0.0, min(1.0, sum(g for _, g, _, _ in self.parts) / total_max))
        return self

    @property
    def points(self) -> float:
        return round(self.fraction * self.weight, 1)

    def to_dict(self) -> dict:
        return {"name": self.name, "points": self.points, "max": self.weight,
                "parts": [{"label": l, "got": g, "max": m, "evidence_ids": sorted({i for f in fs for i in f.evidence_ids}),
                           "facts": [{"key": f.key, "value": f.value, "evidence_ids": f.evidence_ids} for f in fs]}
                          for l, g, m, fs in self.parts]}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def demand(v: EntityView, w: float, cfg: dict) -> Component:
    c = Component("demand", w)
    aud, proxy = v.audience()
    lo, hi = float(cfg.get("users_log_floor", 3)), float(cfg.get("users_log_ceiling", 7))
    if aud and isinstance(aud.value, (int, float)) and aud.value > 0:
        frac = _clamp((math.log10(aud.value) - lo) / (hi - lo))
        if proxy:
            frac *= 0.6  # stars and downloads overstate or understate users; discount them
        c.add("audience on a log scale" + (" (stars/downloads proxy, discounted)" if proxy else ""), frac * 12, 12, [aud])
    else:
        c.add("audience unknown", 0, 12)
    rc_rows = [f for f in (v.metric_for_product("rating_count", p["id"]) for p in v.products) if f and isinstance(f.value, (int, float))]
    if rc_rows:
        total = sum(f.value for f in rc_rows)
        ceiling = float(cfg.get("rating_count_ceiling", 2000))
        c.add("rating count", _clamp(math.log10(total + 1) / math.log10(ceiling)) * 6, 6,
              rc_rows if len(rc_rows) == 1 else [Fact("rating_count_total", total, [i for f in rc_rows for i in f.evidence_ids], derived=True)])
    else:
        c.add("rating count unknown", 0, 6)
    alt = v.metric("suggestions_alternative")
    other = [f for f in (v.metric("suggestions_not_working"), v.metric("suggestions_pricing")) if f and f.value]
    if alt and alt.value:
        c.add("people search for '<product> alternative'", 7, 7, [alt])
    elif other:
        c.add("people search for '<product> not working' / '<product> pricing'", 3, 7, other)
    else:
        c.add("no replacement searches found" if alt is not None else "replacement searches not checked", 0, 7, [alt] if alt is not None else [])
    return c.finish()


def supply_failure(v: EntityView, w: float, signals: dict[str, Signal], stale_months: float) -> Component:
    c = Component("supply_failure", w)
    last = v.last_update()
    m = months_since(last.value) if last else None
    if m is not None:
        c.add("months since last update", _clamp(m / stale_months) * 8, 8, [last])
    else:
        c.add("last update unknown", 0, 8)
    opened, resolved = v.metric("support_threads_recent"), v.metric("support_threads_resolved")
    if opened and resolved is not None and resolved.value is not None and (opened.value or 0) >= 3:
        share = _clamp((opened.value - resolved.value) / opened.value)
        c.add("share of recent support threads unresolved", share * 5, 5, [opened, resolved])
    else:
        unanswered = [e for e in v.of_type("issue", "support_thread") if "unanswered" in e["tag_list"]]
        if len(unanswered) >= 3:
            c.add("recent issues/threads with no reply", _clamp(len(unanswered) / 10) * 5, 5,
                  [Fact("unanswered", len(unanswered), [e["id"] for e in unanswered], derived=True)])
        else:
            c.add("support resolution unknown", 0, 5)
    pain_reasons = [r for r in signals["pain"].reasons if r.text.startswith("recent rating")]
    if pain_reasons:
        drop = pain_reasons[0].weight
        c.add("last-year rating below lifetime rating", _clamp(drop / 1.5) * 4, 4, pain_reasons[0].facts)
    else:
        c.add("no rating decline found", 0, 4)
    compat = [r for r in signals["abandonment"].reasons if r.text.startswith("WordPress releases behind")]
    archived = [r for r in signals["abandonment"].reasons if r.text.startswith("repository archived")]
    if compat:
        c.add("not tested with current platform releases", compat[0].weight * 4, 4, compat[0].facts)
    elif archived:
        c.add("archived: will not follow platform changes", 4, 4, archived[0].facts)
    else:
        c.add("no compatibility break found", 0, 4)
    disp = signals["displacement"]
    if disp.strength:
        best = max(disp.reasons, key=lambda r: r.weight)
        c.add("displacement event: " + best.text, disp.strength * 4, 4, best.facts)
    else:
        c.add("no displacement event found", 0, 4)
    return c.finish()


def pain_specificity(v: EntityView, w: float, clusters: list[Cluster], max_clusters: int) -> Component:
    c = Component("pain_specificity", w)
    total = sum(cl.size for cl in clusters)
    specific = [cl for cl in clusters if cl.key != "other" and cl.size >= 2]
    if not total:
        c.add("no recent complaints", 0, 9)
        c.add("complaint volume", 0, 6)
        return c.finish()
    covered = sum(cl.size for cl in specific)
    all_ids = [i for cl in clusters for i in cl.evidence_ids]
    facts = [Fact("specific_clusters", len(specific), [i for cl in specific for i in cl.evidence_ids], derived=True),
             Fact("complaints", total, all_ids, derived=True)]
    if 1 <= len(specific) <= max_clusters:
        c.add(f"complaints fall into cfg:{max_clusters} or fewer fixable problems; share covered", (covered / total) * 9, 9, facts)
    elif len(specific) > max_clusters:
        top = sorted(specific, key=lambda cl: -cl.size)[:max_clusters]
        c.add(f"complaints spread over more than cfg:{max_clusters} problems; share in the top cfg:{max_clusters}",
              (sum(cl.size for cl in top) / total) * 5, 9, facts)
    else:
        c.add("complaints too vague to name a fix", 0, 9, facts)
    c.add("complaint volume", _clamp(total / 8) * 6, 6, [facts[1]])
    return c.finish()


def channel(v: EntityView, w: float) -> Component:
    c = Component("channel", w)
    listed = [p for p in v.products if p["source"] in LISTING_MARKETPLACES]
    if listed:
        lf = v.listing_fact(listed[0]["id"])
        c.add("a replacement can be listed in the same marketplace", 8, 8, [lf] if lf else [])
    elif any(p["source"] == "github" for p in v.products):
        c.add("users gather on GitHub (issues, stars) but there is no marketplace", 4, 8)
    else:
        c.add("no known listing channel", 0, 8)
    alt = v.metric("suggestions_alternative")
    c.add("replacement searches to target", 4 if alt and alt.value else 0, 4, [alt] if alt else [])
    asks = [e for e in v.evidence if "intent" in e["tag_list"] and e["type"] in ("discussion", "question", "review", "support_thread", "issue")]
    c.add("public threads asking for an alternative", 3 if asks else 0, 3,
          [Fact("alternative_requests", len(asks), [e["id"] for e in asks], derived=True)] if asks else [])
    return c.finish()


def potential_profit(v: EntityView, w: float, cfg: dict, listing: str) -> Component:
    """Revenue ceiling (audience) x proof that money changes hands x business buyers."""
    c = Component("potential_profit", w)
    aud, proxy = v.audience()
    lo, hi = float(cfg.get("users_log_floor", 3)), float(cfg.get("users_log_ceiling", 6))
    if aud and isinstance(aud.value, (int, float)) and aud.value > 0:
        frac = _clamp((math.log10(aud.value) - lo) / (hi - lo))
        if proxy:
            frac *= float(cfg.get("proxy_discount", 0.6))
        c.add("revenue ceiling: audience on a log scale" + (" (proxy, discounted)" if proxy else ""), frac * 5, 5, [aud])
    else:
        c.add("revenue ceiling unknown", 0, 5)
    charges = [f for f in (v.metric("business_model"), v.metric("requires_payment")) if f and str(f.value) in ("commercial", "yes")]
    c.add("incumbent charges money (paid upgrades or required payment)", 4 if charges else 0, 4, charges)
    paying = [e for e in v.evidence if "paying" in e["tag_list"] and e["type"] not in ("search_suggestion", "metric")]
    c.add("users mention paying, refunds or subscriptions", (2 if paying else 0) + (1 if len(paying) >= 3 else 0), 3,
          [Fact("paying_mentions", len(paying), [e["id"] for e in paying], derived=True)] if paying else [])
    biz = word_hits(cfg.get("business_words", []), listing)
    lf = v.listing_fact()
    c.add("business buyers (listing names business use: " + ", ".join(biz[:4]) + ")" if biz else "no business-buyer words in the listing",
          2 if biz and lf else 0, 2, [lf] if biz and lf else [])
    pricing = v.metric("suggestions_pricing")
    c.add("people search for its pricing", 1 if pricing and pricing.value else 0, 1, [pricing] if pricing else [])
    return c.finish()


def ease_of_development(v: EntityView, w: float, clusters: list[Cluster], cfg: dict, listing: str) -> Component:
    """How small and routine the replacement is to build, read from the listing, license and complaint clusters."""
    c = Component("ease_of_development", w)
    primary = v.primary or {}
    plat = cfg.get("platform", {})
    src = primary.get("source")
    lf = v.listing_fact()
    if src in plat and lf:
        easy = float(plat[src]) >= float(cfg.get("platform_easy_cutoff", 0.7))
        c.add(f"platform: a {src} replacement is a small, well-documented build" if easy else f"platform: {src} builds need hosting, auth or a large codebase",
              float(plat[src]) * 5, 5, [lf])
    else:
        c.add("platform unknown", 0, 5)
    lic = v.metric("license", prefer="primary")
    open_src = bool(lic and re.search(r"gpl|mit|apache|bsd|mpl|mozilla|epl|eclipse|isc|unlicense|cc0|public domain", str(lic.value), re.I))
    c.add("incumbent is open source: its code and data formats can be studied" if open_src else ("license not open: build from scratch" if lic else "license unknown"),
          3 if open_src else 0, 3, [lic] if lic else [])
    specific = [cl for cl in clusters if cl.key != "other" and cl.size >= 1]
    routine = [cl for cl in specific if cl.key in set(cfg.get("routine_clusters", []))]
    if specific:
        share = len(routine) / len(specific)
        narrow = 1.0 if len(specific) <= 3 else max(0.0, 1 - (len(specific) - 3) / 4)
        ids = [i for cl in specific for i in cl.evidence_ids]
        c.add("fixes are routine engineering (share of complaint clusters)",
              share * 3, 3, [Fact("routine_clusters", len(routine), [i for cl in routine for i in cl.evidence_ids], derived=True)] if routine else [Fact("clusters", len(specific), ids, derived=True)])
        c.add("narrow scope: few distinct problems to fix", narrow * 2, 2, [Fact("specific_clusters", len(specific), ids, derived=True)])
    else:
        c.add("no complaint clusters: scope is only parity with the incumbent", 2, 3)
        c.add("narrow scope: few distinct problems to fix", 2, 2)
    hard = word_hits(cfg.get("hard_words", []), listing)
    if hard and lf:
        c.add("listing implies servers, accounts, payments or third-party dependencies (" + ", ".join(hard[:4]) + ")",
              -min(len(hard), int(cfg.get("hard_word_max", 4))) * float(cfg.get("hard_word_penalty", 0.75)), 0, [lf])
    return c.finish()


def timing(v: EntityView, w: float, signals: dict[str, Signal], fresh_days: float) -> Component:
    c = Component("timing", w)
    dated = [f for r in signals["displacement"].reasons for f in r.facts if f.key == "event_date"]
    if dated:
        latest = max(dated, key=lambda f: f.value)
        age = days_between(latest.value) or 0
        frac = 1.0 if age <= fresh_days else _clamp(1 - (age - fresh_days) / (2 * fresh_days))
        c.add("recency of the latest displacement event", frac * 7, 7, [latest])
    elif signals["displacement"].strength:
        c.add("displacement event without a date", 3, 7, [f for r in signals["displacement"].reasons for f in r.facts][:1])
    elif signals["abandonment"].present:
        c.add("slow-burn abandonment, no dated event", 2, 7)
    else:
        c.add("no event", 0, 7)
    recent_pain = v.complaints(recent_only=True)
    c.add("complaints are still arriving", 3 if len([e for e in recent_pain if (days_between(e["date_posted"]) or 999) <= 90]) >= 2 else 0, 3)
    # A maintained replacement that is already growing makes the window smaller.
    switched = [e for e in v.evidence if e["text"] and _SWITCHED.search(e["text"])]
    if len(switched) >= 3:
        c.add("users report having already switched to another tool", -3, 0,
              [Fact("switch_reports", len(switched), [e["id"] for e in switched], derived=True)])
    return c.finish()


import re  # noqa: E402

_SWITCHED = re.compile(r"\b(switched|moved|migrated) (over )?to\b|\bnow (i )?use\b|\bwent back to\b", re.I)


def score_entity(v: EntityView, signals: dict[str, Signal], clusters: list[Cluster], config) -> dict:
    wts = config.weights
    th = config.section("thresholds")
    listing = v.listing_text()
    comps = [
        demand(v, wts["demand"], config.section("demand")),
        supply_failure(v, wts["supply_failure"], signals, float(th.get("stale_months", 18))),
        pain_specificity(v, wts["pain_specificity"], clusters, int(th.get("max_clusters_for_specificity", 5))),
        channel(v, wts["channel"]),
        potential_profit(v, wts["potential_profit"], config.section("profit"), listing),
        ease_of_development(v, wts["ease_of_development"], clusters, config.section("ease"), listing),
        timing(v, wts["timing"], signals, float(th.get("event_fresh_days", 180))),
    ]
    total = round(sum(c.points for c in comps), 1)
    return {"total": total, "components": [c.to_dict() for c in comps],
            "signals": {k: {"strength": s.strength, "present": s.present} for k, s in signals.items()},
            "signal_count": sum(1 for s in signals.values() if s.present)}
