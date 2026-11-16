"""Reddit Data API, only with credentials you supply (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET /
REDDIT_USER_AGENT for a "script" app: https://www.reddit.com/prefs/apps).

Docs read: https://www.reddit.com/dev/api/#GET_search, https://github.com/reddit-archive/reddit/wiki/OAuth2
(application-only client-credentials flow), Data API terms https://redditinc.com/policies/data-api-terms
Unauthenticated access to reddit.com JSON is not used (robots.txt and the Data API terms require
registered access). Usernames are discarded. Free tier: 100 queries/minute; this adapter makes
at most one per top candidate, one second apart.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from typing import Iterator

from ..config import env
from ..models import Evidence
from ..net import FetchError
from ..textutil import detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH = "https://oauth.reddit.com/search"


def post_to_evidence(child: dict, ts: str, subject: str | None) -> Evidence | None:
    d = child.get("data") or {}
    if not d.get("permalink"):
        return None
    text = f"{d.get('title', '')}. {snippet(d.get('selftext'), 400)}".strip(". ")
    tags = [f"event:{k}" for k in detect_events(text)]
    if is_negative(text):
        tags.append("negative")
    if replacement_intent(text):
        tags.append("intent")
    if mentions_paying(text):
        tags.append("paying")
    return Evidence(
        source="reddit", type="discussion", url="https://www.reddit.com" + d["permalink"], date_retrieved=ts,
        date_posted=iso(d.get("created_utc")), text=text, score=d.get("score"), metric_key="reddit_score",
        metric_value=d.get("score"), subject=subject, tags=tags,
        extra={"subreddit": d.get("subreddit"), "num_comments": d.get("num_comments")},
    )


class RedditAdapter(Adapter):
    name = "reddit"
    title = "Reddit (with your API credentials)"
    docs_url = "https://www.reddit.com/dev/api/"
    terms_url = "https://redditinc.com/policies/data-api-terms"
    env_required = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
    api_hosts = {"oauth.reddit.com": 1.0}
    phase = 2

    def _token(self) -> str:
        auth = base64.b64encode(f"{env('REDDIT_CLIENT_ID')}:{env('REDDIT_CLIENT_SECRET')}".encode()).decode()
        req = urllib.request.Request(TOKEN_URL, data=b"grant_type=client_credentials", method="POST",
                                     headers={"Authorization": f"Basic {auth}", "User-Agent": env("REDDIT_USER_AGENT")})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        try:
            token = self._token()
        except Exception as exc:  # noqa: BLE001 - any auth failure just disables the source
            ctx.log.warning("reddit: authentication failed: %s", exc)
            return
        headers = {"Authorization": f"Bearer {token}", "User-Agent": env("REDDIT_USER_AGENT")}
        for cand in ctx.candidates(int(ctx.scan_cfg("autocomplete_top_products", 40))):
            q = f'"{cand["name"]}" (alternative OR replacement OR "shutting down" OR "not working")'
            try:
                data, ts = ctx.http.get_json(SEARCH, params={"q": q, "sort": "relevance", "t": "year", "limit": 25}, headers=headers)
            except FetchError as exc:
                ctx.log.warning("reddit: %s", exc)
                return
            for child in (data.get("data") or {}).get("children") or []:
                ev = post_to_evidence(child, ts, cand["name"])
                if ev:
                    yield ev
