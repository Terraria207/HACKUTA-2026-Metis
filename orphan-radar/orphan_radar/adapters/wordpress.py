"""WordPress.org plugin directory.

Docs read: https://codex.wordpress.org/WordPress.org_API (plugins/info/1.2 query_plugins and
plugin_information), https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/
api.wordpress.org is a documented public API (every WordPress install calls it); its robots.txt
targets crawlers, so it is used under the API's own terms with a polite delay. Support and review
RSS feeds live on wordpress.org, whose robots.txt allows /support/ and is checked on every fetch.
No login, no personal data: forum author names in the feeds are discarded.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Iterator

from ..models import Evidence, Product, metric
from ..net import FetchError
from ..textutil import days_between, detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet, version_tuple
from .base import Adapter, Record, ScanContext

API = "https://api.wordpress.org/plugins/info/1.2/"
CORE = "https://api.wordpress.org/core/version-check/1.7/"
GUIDELINES = "https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/"
FIELDS = {"description": 0, "sections": 0, "icons": 0, "banners": 0, "screenshots": 0, "versions": 0,
          "contributors": 0, "business_model": 1, "short_description": 1, "tags": 1, "ratings": 1}


def query_params(extra: dict) -> dict:
    params = {"action": "query_plugins", "request[per_page]": 100}
    for k, v in extra.items():
        params[f"request[{k}]"] = v
    for k, v in FIELDS.items():
        params[f"request[fields][{k}]"] = v
    return params


def plugin_to_product(p: dict) -> Product:
    slug = p["slug"]
    model = p.get("business_model")
    pricing = "freemium" if model == "commercial" else ("free" if model in ("community", False) else "free")
    return Product(
        source="wordpress", source_id=slug, name=snippet(p.get("name"), 120), url=f"https://wordpress.org/plugins/{slug}/",
        category="wordpress-plugin", user_count=p.get("active_installs"), last_updated=iso(p.get("last_updated")),
        rating=round(p["rating"] / 20, 2) if p.get("rating") is not None else None, rating_count=p.get("num_ratings"),
        pricing_model=pricing, license="GPL-compatible (WordPress.org directory requirement)",
        description=snippet(p.get("short_description"), 400), tags=sorted((p.get("tags") or {}).values()) if isinstance(p.get("tags"), dict) else [],
        homepage=p.get("homepage"),
        extra={"tested": p.get("tested"), "requires": p.get("requires"), "support_threads": p.get("support_threads"),
               "support_threads_resolved": p.get("support_threads_resolved"), "business_model": model, "version": p.get("version"),
               "ratings": p.get("ratings"), "added": p.get("added"), "author": snippet(p.get("author"), 80)},
    )


def plugin_metrics(prod: Product, raw: dict, url: str, ts: str, core_version: str | None, core_url: str) -> list[Evidence]:
    page = prod.url
    out = [
        metric("wordpress", prod, "user_count", raw.get("active_installs"), url, ts, f"Active installations as shown on {page}"),
        metric("wordpress", prod, "rating", prod.rating, url, ts, "Average rating out of 5 (WordPress.org reports 0-100; divided by 20)"),
        metric("wordpress", prod, "rating_count", raw.get("num_ratings"), url, ts, "Number of ratings"),
        metric("wordpress", prod, "last_updated", iso(raw.get("last_updated")), url, ts, "Date of the last release"),
        metric("wordpress", prod, "tested_up_to", raw.get("tested"), url, ts, "Highest WordPress version the author has tested"),
        metric("wordpress", prod, "support_threads_recent", raw.get("support_threads"), url, ts, "Support threads opened in the last two months"),
        metric("wordpress", prod, "support_threads_resolved", raw.get("support_threads_resolved"), url, ts, "Of those, threads marked resolved"),
        metric("wordpress", prod, "license", prod.license, GUIDELINES, ts, "WordPress.org only hosts GPL-compatible plugins (guideline 1)"),
    ]
    if raw.get("author"):
        out.append(metric("wordpress", prod, "author", snippet(raw.get("author"), 80), url, ts, "Plugin author as shown on the listing"))
    if raw.get("business_model"):
        out.append(metric("wordpress", prod, "business_model", raw.get("business_model"), url, ts,
                          "Business model declared on the listing ('commercial' = paid upgrades or services exist)"))
    ratings = raw.get("ratings") or {}
    if isinstance(ratings, dict):
        for star in ("1", "2"):
            if star in ratings:
                out.append(metric("wordpress", prod, f"ratings_{star}_star", ratings[star], url, ts, f"Number of {star}-star ratings, lifetime"))
    if core_version:
        out.append(metric("wordpress", prod, "platform_current_version", core_version, core_url, ts, "Current WordPress release"))
    return [e for e in out if e]


def suspicion(p: dict, core_version: str | None) -> float:
    """Order plugins for the expensive feed fetches: stale, untested, unresolved, big."""
    s = 0.0
    age = days_between(iso(p.get("last_updated"))) or 0
    s += min(age / 365, 3)
    if core_version and version_tuple(p.get("tested"))[:2] < version_tuple(core_version)[:2]:
        s += 1
    opened, resolved = p.get("support_threads") or 0, p.get("support_threads_resolved") or 0
    if opened >= 3:
        s += (opened - resolved) / opened
    if (p.get("rating") or 100) < 70:
        s += 1
    s += min((p.get("active_installs") or 0) / 1_000_000, 1)
    return s


_STARS = re.compile(r"\((\d) stars?\)\s*$")
_REPLIES = re.compile(r"Replies:\s*(\d+)")


def parse_feed(xml_text: str, prod: Product, kind: str, ts: str) -> list[Evidence]:
    """kind: 'support' or 'reviews'. Author names are deliberately not read."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        if not link:
            continue
        replies_m = _REPLIES.search(desc)
        replies = int(replies_m.group(1)) if replies_m else None
        body = snippet(_REPLIES.sub("", desc).replace("Rating:", "", 1), 500)
        stars = None
        if kind == "reviews":
            m = _STARS.search(title)
            stars = int(m.group(1)) if m else None
            title = _STARS.sub("", title).strip()
        text = f"{title}. {body}" if body and not body.startswith(title) else (body or title)
        tags = []
        if is_negative(text, stars):
            tags.append("negative")
        tags += [f"event:{k}" for k in detect_events(text)]
        if mentions_paying(text):
            tags.append("paying")
        if replacement_intent(text):
            tags.append("intent")
        if kind == "support" and replies == 0:
            tags.append("unanswered")
        out.append(Evidence(
            source="wordpress", type="review" if kind == "reviews" else "support_thread", url=link, date_retrieved=ts,
            date_posted=iso(item.findtext("pubDate")), text=text, score=stars, subject=prod.name,
            product_ref=(prod.source, prod.source_id), tags=tags, extra={"replies": replies, "title": title},
        ))
    return out


class WordPressAdapter(Adapter):
    name = "wordpress"
    title = "WordPress.org plugin directory"
    docs_url = "https://codex.wordpress.org/WordPress.org_API"
    terms_url = "https://wordpress.org/about/privacy/"
    api_hosts = {"api.wordpress.org": 1.0}

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        core_version = None
        try:
            core, _ = ctx.http.get_json(CORE)
            core_version = (core.get("offers") or [{}])[0].get("current")
        except FetchError as exc:
            ctx.log.warning("wordpress: core version unavailable: %s", exc)

        seen: dict[str, tuple[dict, Product]] = {}
        queries = [{"browse": "popular", "page": n} for n in range(1, int(ctx.scan_cfg("wordpress_pages", 4)) + 1)]
        queries += [{"search": q, "page": 1} for q in ctx.scan_cfg("wordpress_extra_queries", [])]
        for q in queries:
            params = query_params(q)
            url = API + "?" + urllib.parse.urlencode(params)
            try:
                data, ts = ctx.http.get_json(url)
            except FetchError as exc:
                ctx.log.warning("wordpress: %s", exc)
                continue
            for raw in data.get("plugins") or []:
                if not isinstance(raw, dict) or raw.get("slug") in seen:
                    continue
                prod = plugin_to_product(raw)
                seen[raw["slug"]] = (raw, prod)
                yield prod
                yield from plugin_metrics(prod, raw, url, ts, core_version, CORE)

        limit = int(ctx.scan_cfg("wordpress_feed_limit", 40))
        ranked = sorted(seen.values(), key=lambda rp: suspicion(rp[0], core_version), reverse=True)[:limit]
        for raw, prod in ranked:
            for kind, path in (("support", "feed/"), ("reviews", "reviews/feed/")):
                feed_url = f"https://wordpress.org/support/plugin/{prod.source_id}/{path}"
                try:
                    text, ts = ctx.http.get_text(feed_url)
                except FetchError as exc:
                    ctx.log.info("wordpress: feed skipped: %s", exc)
                    continue
                yield from parse_feed(text, prod, kind, ts)
