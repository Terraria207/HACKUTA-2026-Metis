"""Firefox Add-ons (addons.mozilla.org) API v5.

Docs read: https://mozilla.github.io/addons-server/topics/api/addons.html and
.../topics/api/ratings.html. Public, unauthenticated, read-only; addons.mozilla.org
robots.txt allows /api/. Reviewer names and profile links are discarded.
"""
from __future__ import annotations

from typing import Iterator

from ..models import Evidence, Product, metric
from ..net import FetchError
from ..textutil import days_between, detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

SEARCH = "https://addons.mozilla.org/api/v5/addons/search/"
RATINGS = "https://addons.mozilla.org/api/v5/ratings/rating/"


def _t(value) -> str | None:
    """AMO returns translated fields as a string (with lang=) or a {locale: text} dict."""
    if isinstance(value, dict):
        return value.get("en-US") or value.get("en-GB") or next(iter(value.values()), None)
    return value


def addon_to_product(a: dict) -> Product:
    cv = a.get("current_version") or {}
    lic = cv.get("license") or {}
    lic_name = _t(lic.get("name")) or lic.get("slug")
    return Product(
        source="firefox", source_id=a["slug"], name=snippet(_t(a.get("name")) or a["slug"], 120),
        url=a.get("url") or f"https://addons.mozilla.org/en-US/firefox/addon/{a['slug']}/",
        category=",".join(a.get("categories") or []) if isinstance(a.get("categories"), list) else "firefox-addon",
        user_count=a.get("average_daily_users"), last_updated=iso(a.get("last_updated")),
        rating=(a.get("ratings") or {}).get("average"), rating_count=(a.get("ratings") or {}).get("count"),
        pricing_model="paid" if a.get("requires_payment") else "unknown", license=lic_name,
        description=snippet(_t(a.get("summary")), 400), tags=list(a.get("tags") or []),
        homepage=_t((a.get("homepage") or {}).get("url")) if isinstance(a.get("homepage"), dict) else _t(a.get("homepage")),
        extra={"guid": a.get("guid"), "version": cv.get("version"), "compatibility": cv.get("compatibility"),
               "license_url": lic.get("url"), "promoted": a.get("promoted"), "requires_payment": a.get("requires_payment"),
               "is_disabled": a.get("is_disabled"), "status": a.get("status")},
    )


def addon_metrics(p: Product, a: dict, url: str, ts: str) -> list[Evidence]:
    out = [
        metric("firefox", p, "user_count", a.get("average_daily_users"), url, ts, f"Average daily users as reported by addons.mozilla.org for {p.url}"),
        metric("firefox", p, "rating", p.rating, url, ts, "Average rating out of 5, lifetime"),
        metric("firefox", p, "rating_count", p.rating_count, url, ts, "Number of ratings, lifetime"),
        metric("firefox", p, "last_updated", p.last_updated, url, ts, "Date of the last update"),
        metric("firefox", p, "license", p.license, url, ts, "License of the current version"),
    ]
    if a.get("requires_payment"):
        out.append(metric("firefox", p, "requires_payment", "yes", url, ts, "Listing says the add-on requires payment for some features"))
    return [e for e in out if e]


def parse_ratings(data: dict, p: Product, url: str, ts: str, window_days: int) -> list[Evidence]:
    out = []
    recent_scores = []
    for r in data.get("results") or []:
        if r.get("is_developer_reply"):
            continue
        age = days_between(r.get("created"))
        if age is not None and age <= window_days and r.get("score"):
            recent_scores.append(int(r["score"]))
        body = snippet(r.get("body"), 600)
        if not body:
            continue  # star-only ratings count toward the average but are not quotable evidence
        score = int(r["score"]) if r.get("score") else None
        tags = (["negative"] if is_negative(body, score) else []) + [f"event:{k}" for k in detect_events(body)]
        if mentions_paying(body):
            tags.append("paying")
        if replacement_intent(body):
            tags.append("intent")
        out.append(Evidence(
            source="firefox", type="review", url=f"https://addons.mozilla.org/en-US/firefox/addon/{p.source_id}/reviews/{r['id']}/",
            date_retrieved=ts, date_posted=iso(r.get("created")), text=body, score=score, subject=p.name,
            product_ref=(p.source, p.source_id), tags=tags,
            extra={"version": (r.get("version") or {}).get("version") if isinstance(r.get("version"), dict) else None},
        ))
    if len(recent_scores) >= 5:
        avg = round(sum(recent_scores) / len(recent_scores), 2)
        out.append(Evidence(
            source="firefox", type="metric", url=url, date_retrieved=ts, metric_key="rating_recent", metric_value=avg,
            text=f"Average of the {len(recent_scores)} most recent ratings posted within {window_days} days",
            subject=p.name, product_ref=(p.source, p.source_id), extra={"n": len(recent_scores)},
        ))
    return out


class FirefoxAdapter(Adapter):
    name = "firefox"
    title = "Firefox Add-ons"
    docs_url = "https://mozilla.github.io/addons-server/topics/api/index.html"
    terms_url = "https://www.mozilla.org/about/legal/terms/services/"
    api_hosts = {"addons.mozilla.org": 1.0}

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        window = int(ctx.config.threshold("recent_window_days", 365))
        seen: dict[str, tuple[dict, Product]] = {}
        for page in range(1, int(ctx.scan_cfg("firefox_pages", 3)) + 1):
            params = {"app": "firefox", "type": "extension", "sort": "users", "page_size": 50, "page": page, "lang": "en-US"}
            try:
                data, ts = ctx.http.get_json(SEARCH, params=params)
            except FetchError as exc:
                ctx.log.warning("firefox: %s", exc)
                break
            url = SEARCH + "?" + "&".join(f"{k}={v}" for k, v in params.items())
            for a in data.get("results") or []:
                if a.get("slug") in seen:
                    continue
                p = addon_to_product(a)
                seen[a["slug"]] = (a, p)
                yield p
                yield from addon_metrics(p, a, url, ts)

        # Recent reviews for the most suspicious add-ons: stale first, then low-rated, then big.
        def suspicion(item):
            a, p = item
            stale = (days_between(p.last_updated) or 0) / 365
            low = max(0.0, 4.3 - (p.rating or 5))
            return stale + low * 2 + min((p.user_count or 0) / 1_000_000, 1)

        limit = int(ctx.scan_cfg("firefox_reviews_limit", 40))
        for a, p in sorted(seen.values(), key=suspicion, reverse=True)[:limit]:
            params = {"addon": p.source_id, "sort": "created", "page_size": 50, "lang": "en-US"}
            try:
                data, ts = ctx.http.get_json(RATINGS, params=params)
            except FetchError as exc:
                ctx.log.info("firefox: ratings skipped: %s", exc)
                continue
            url = RATINGS + f"?addon={p.source_id}&sort=created&page_size=50"
            yield from parse_ratings(data, p, url, ts, window)
