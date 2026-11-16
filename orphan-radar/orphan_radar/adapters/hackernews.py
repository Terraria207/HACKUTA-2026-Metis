"""Hacker News via the Algolia search API.

Docs read: https://hn.algolia.com/api (search, search_by_date, tags, numericFilters).
Public, no key, 10,000 requests/hour per IP. Two passes:
  1. a sweep for displacement language ("shutting down", "price increase", "alternative to" ...);
     each hit is stored once and attached to a product later only if the product's name appears in it;
  2. targeted searches "<product> alternative" for the current top candidates.
Usernames are discarded; only the item link, title/text snippet, points and date are kept.
"""
from __future__ import annotations

import time
from typing import Iterator

from ..models import Evidence
from ..net import FetchError
from ..textutil import detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

SEARCH = "https://hn.algolia.com/api/v1/search"
SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"


def hit_to_evidence(hit: dict, ts: str, subject: str | None = None) -> Evidence | None:
    is_comment = bool(hit.get("comment_text"))
    title = hit.get("title") or hit.get("story_title") or ""
    body = snippet(hit.get("comment_text") or hit.get("story_text"), 500)
    text = (f"{title}. {body}" if body and not is_comment else body or title).strip()
    if not text:
        return None
    tags = [f"event:{k}" for k in detect_events(text)]
    if is_negative(text):
        tags.append("negative")
    if replacement_intent(text):
        tags.append("intent")
    if mentions_paying(text):
        tags.append("paying")
    points = hit.get("points")
    return Evidence(
        source="hackernews", type="discussion", url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
        date_retrieved=ts, date_posted=iso(hit.get("created_at")), text=text, score=points,
        metric_key="hn_points" if points is not None else None, metric_value=points,
        subject=subject, tags=tags,
        extra={"kind": "comment" if is_comment else "story", "num_comments": hit.get("num_comments"),
               "linked_url": hit.get("url"), "story_id": hit.get("story_id")},
    )


class HackerNewsAdapter(Adapter):
    name = "hackernews"
    title = "Hacker News (Algolia search API)"
    docs_url = "https://hn.algolia.com/api"
    terms_url = "https://www.ycombinator.com/legal/"
    api_hosts = {"hn.algolia.com": 0.5}
    phase = 2

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        days = int(ctx.scan_cfg("hn_days", 365))
        min_points = int(ctx.scan_cfg("hn_min_points", 40))
        since = int(time.time()) - days * 86400
        since = since - since % 86400  # day-aligned so the cached URL is stable within a day
        for q in ctx.scan_cfg("hn_queries", []):
            params = {"query": f'"{q}"', "tags": "story", "hitsPerPage": 50,
                      "numericFilters": f"created_at_i>{since},points>{min_points}"}
            try:
                data, ts = ctx.http.get_json(SEARCH, params=params)
            except FetchError as exc:
                ctx.log.warning("hackernews: %s", exc)
                continue
            for hit in data.get("hits") or []:
                ev = hit_to_evidence(hit, ts)
                if ev:
                    ev.extra["query"] = q
                    yield ev

        for cand in ctx.candidates(int(ctx.scan_cfg("autocomplete_top_products", 40))):
            name = cand["name"]
            if len(cand["norm_name"]) < 4:
                continue
            params = {"query": f'"{name}" alternative', "tags": "(story,comment)", "hitsPerPage": 20,
                      "numericFilters": f"created_at_i>{since - 365 * 86400}"}
            try:
                data, ts = ctx.http.get_json(SEARCH, params=params)
            except FetchError as exc:
                ctx.log.info("hackernews: %s", exc)
                continue
            for hit in data.get("hits") or []:
                ev = hit_to_evidence(hit, ts)
                if ev:
                    ev.extra["query"] = f"{name} alternative"
                    yield ev
