"""Stack Exchange API 2.3: high-view questions with no accepted answer.

Docs read: https://api.stackexchange.com/docs/advanced-search, https://api.stackexchange.com/docs/throttle
Without a key the quota is 300 requests/day per IP; with STACKEXCHANGE_KEY it is 10,000.
The API's `backoff` field is honoured. Asker names are discarded.
"""
from __future__ import annotations

import time
from typing import Iterator

from ..config import env
from ..models import Evidence
from ..net import FetchError
from ..textutil import detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

ADV = "https://api.stackexchange.com/2.3/search/advanced"
SITE_FOR_SOURCE = {"wordpress": "wordpress", "firefox": "superuser", "github": "stackoverflow", "openvsx": "stackoverflow", "atlassian": "stackoverflow"}


def item_to_evidence(item: dict, site: str, ts: str) -> Evidence:
    title = snippet(item.get("title"), 300)
    text = f"{title}. {snippet(item.get('body'), 400)}".strip(". ")
    tags = ["unanswered"] if not item.get("accepted_answer_id") else []
    tags += [f"event:{k}" for k in detect_events(text)]
    if is_negative(text):
        tags.append("negative")
    if replacement_intent(text):
        tags.append("intent")
    if mentions_paying(text):
        tags.append("paying")
    return Evidence(
        source="stackexchange", type="question", url=item["link"], date_retrieved=ts,
        date_posted=iso(item.get("creation_date")), text=text, score=item.get("score"),
        metric_key="view_count", metric_value=item.get("view_count"), tags=tags,
        extra={"site": site, "answer_count": item.get("answer_count"), "se_tags": item.get("tags"), "title": title},
    )


class StackExchangeAdapter(Adapter):
    name = "stackexchange"
    title = "Stack Exchange"
    docs_url = "https://api.stackexchange.com/docs"
    terms_url = "https://stackoverflow.com/legal/api-terms-of-use"
    api_hosts = {"api.stackexchange.com": 1.0}
    phase = 2

    def _get(self, ctx: ScanContext, params: dict):
        params = dict(params, filter="withbody")
        if env("STACKEXCHANGE_KEY"):
            params["key"] = env("STACKEXCHANGE_KEY")
        data, ts = ctx.http.get_json(ADV, params=params)
        if data.get("backoff"):
            time.sleep(min(int(data["backoff"]), 30))
        if data.get("quota_remaining") is not None and data["quota_remaining"] < 10:
            raise FetchError("Stack Exchange daily quota nearly exhausted")
        return data, ts

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        min_views = int(ctx.scan_cfg("stackexchange_min_views", 5000))
        # Pass 1: tool tags, highest-voted questions with no accepted answer.
        for site, tags in (ctx.scan_cfg("stackexchange_sites", {}) or {}).items():
            for tag in tags:
                try:
                    data, ts = self._get(ctx, {"site": site, "tagged": tag, "accepted": "False", "sort": "votes",
                                               "order": "desc", "pagesize": 50})
                except FetchError as exc:
                    ctx.log.warning("stackexchange: %s", exc)
                    return
                for item in data.get("items") or []:
                    if (item.get("view_count") or 0) >= min_views:
                        yield item_to_evidence(item, site, ts)
        # Pass 2: questions naming the top candidates in their title.
        rows = ctx.conn.execute("SELECT DISTINCT entity_id, source FROM products").fetchall()
        source_of = {}
        for r in rows:
            source_of.setdefault(r["entity_id"], r["source"])
        for cand in ctx.candidates(int(ctx.scan_cfg("autocomplete_top_products", 40)) // 2):
            if len(cand["norm_name"]) < 4:
                continue
            site = SITE_FOR_SOURCE.get(source_of.get(cand["id"]), "stackoverflow")
            try:
                data, ts = self._get(ctx, {"site": site, "intitle": cand["name"], "accepted": "False", "sort": "votes",
                                           "order": "desc", "pagesize": 20})
            except FetchError as exc:
                ctx.log.warning("stackexchange: %s", exc)
                return
            for item in data.get("items") or []:
                ev = item_to_evidence(item, site, ts)
                ev.subject = cand["name"]
                yield ev
