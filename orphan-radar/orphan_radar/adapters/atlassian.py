"""Atlassian Marketplace (Jira, Confluence, Bitbucket apps) via the documented REST API v2.

Docs read: https://developer.atlassian.com/platform/marketplace/rest/v2/ (addons, reviews).
Public, unauthenticated, read-only. marketplace.atlassian.com/robots.txt disallows /rest/ for
crawlers; like api.wordpress.org this is a documented API, used under its own terms with a
1.5 s delay. Pass --strict-robots to skip it. Reviewer names and profile links are discarded.
"Installs" are installations (sites), each with many users; they are reported as such.
"""
from __future__ import annotations

from typing import Iterator

from ..models import Evidence, Product, metric
from ..net import FetchError
from ..textutil import days_between, detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

BASE = "https://marketplace.atlassian.com"
ADDONS = BASE + "/rest/2/addons"


def addon_to_product(a: dict, paid: bool) -> Product:
    emb = a.get("_embedded") or {}
    dist = emb.get("distribution") or {}
    rev = emb.get("reviews") or {}
    alt = ((a.get("_links") or {}).get("alternate") or {}).get("href") or f"/apps/{a['key']}"
    return Product(
        source="atlassian", source_id=a["key"], name=snippet(a.get("name"), 120), url=BASE + alt.split("?")[0],
        category=", ".join(c.get("name", "") for c in emb.get("categories") or []) or "atlassian-app",
        user_count=dist.get("totalInstalls"), last_updated=iso(emb.get("lastModified")),
        rating=round(rev["averageStars"], 2) if rev.get("averageStars") is not None else None, rating_count=rev.get("count"),
        pricing_model="paid" if paid else "unknown", license=None, description=snippet(a.get("summary") or a.get("tagLine"), 400),
        extra={"downloads": dist.get("downloads"), "vendor": (emb.get("vendor") or {}).get("name")},
    )


def addon_evidence(p: Product, a: dict, url: str, ts: str, paid: bool) -> list[Evidence]:
    out = [
        metric("atlassian", p, "user_count", p.user_count, url, ts, f"Total installations (sites) reported by the Marketplace for {p.url}"),
        metric("atlassian", p, "rating", p.rating, url, ts, "Average stars, lifetime"),
        metric("atlassian", p, "rating_count", p.rating_count, url, ts, "Number of reviews"),
        metric("atlassian", p, "last_updated", p.last_updated, url, ts, "Date the listing was last modified"),
    ]
    if paid:
        out.append(metric("atlassian", p, "requires_payment", "yes", url, ts, "Listed under the Marketplace's paid-apps filter"))
    return [e for e in out if e]


def parse_reviews(data: dict, p: Product, url: str, ts: str, window_days: int) -> list[Evidence]:
    out, recent = [], []
    for r in (data.get("_embedded") or {}).get("reviews") or []:
        stars = r.get("stars")
        age = days_between(r.get("date"))
        if stars and age is not None and age <= window_days:
            recent.append(int(stars))
        body = snippet(r.get("review"), 600)
        if not body:
            continue
        tags = (["negative"] if is_negative(body, stars) else []) + [f"event:{k}" for k in detect_events(body)]
        if mentions_paying(body):
            tags.append("paying")
        if replacement_intent(body):
            tags.append("intent")
        out.append(Evidence(source="atlassian", type="review", url=f"{p.url}?tab=reviews#review-{r.get('id')}", date_retrieved=ts,
                            date_posted=iso(r.get("date")), text=body, score=stars, subject=p.name,
                            product_ref=(p.source, p.source_id), tags=tags, extra={"hosting": r.get("hosting")}))
    if len(recent) >= 5:
        out.append(Evidence(source="atlassian", type="metric", url=url, date_retrieved=ts, metric_key="rating_recent",
                            metric_value=round(sum(recent) / len(recent), 2),
                            text=f"Average of the {len(recent)} most recent reviews posted within {window_days} days",
                            subject=p.name, product_ref=(p.source, p.source_id)))
    return out


class AtlassianAdapter(Adapter):
    name = "atlassian"
    title = "Atlassian Marketplace"
    docs_url = "https://developer.atlassian.com/platform/marketplace/rest/v2/"
    terms_url = "https://www.atlassian.com/legal/atlassian-developer-terms"
    api_hosts = {"marketplace.atlassian.com": 1.5}

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        window = int(ctx.config.threshold("recent_window_days", 365))
        seen: dict[str, tuple[dict, Product]] = {}
        pages = int(ctx.scan_cfg("atlassian_pages", 3))
        for cost in ("paid", None):
            for page in range(pages):
                params = {"limit": 50, "offset": page * 50, "orderBy": "popularity"}
                if cost:
                    params["cost"] = cost
                try:
                    data, ts = ctx.http.get_json(ADDONS, params=params)
                except FetchError as exc:
                    ctx.log.warning("atlassian: %s", exc)
                    break
                url = ADDONS + "?" + "&".join(f"{k}={v}" for k, v in params.items())
                for a in (data.get("_embedded") or {}).get("addons") or []:
                    if a.get("key") in seen:
                        continue
                    p = addon_to_product(a, paid=cost == "paid")
                    seen[a["key"]] = (a, p)
                    yield p
                    yield from addon_evidence(p, a, url, ts, paid=cost == "paid")

        def suspicion(item):
            _, p = item
            return (days_between(p.last_updated) or 0) / 365 + max(0.0, 4.2 - (p.rating or 5)) * 2 + min((p.user_count or 0) / 50_000, 1)

        for a, p in sorted(seen.values(), key=suspicion, reverse=True)[: int(ctx.scan_cfg("atlassian_reviews_limit", 25))]:
            rurl = f"{ADDONS}/{a['key']}/reviews"
            try:
                data, ts = ctx.http.get_json(rurl, params={"limit": 50, "sort": "recent"})
            except FetchError as exc:
                ctx.log.info("atlassian: reviews skipped: %s", exc)
                continue
            yield from parse_reviews(data, p, rurl + "?limit=50&sort=recent", ts, window)
