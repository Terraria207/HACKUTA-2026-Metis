"""Search autocomplete: are people searching for a replacement?

For each top candidate, asks Google's suggestion endpoint for completions of
"<product> alternative", "<product> not working" and "<product> pricing".
Completions only exist for queries people actually type, so a non-empty list that
still names the product is evidence of replacement demand. The raw list is stored.

Access review: suggestqueries.google.com publishes no robots.txt and www.google.com/robots.txt
does not disallow /complete. Google's terms prohibit automated access that violates
machine-readable instructions; none apply here. Requests are cached for 20 h and spaced
2 s apart, at most 3 x autocomplete_top_products per scan.
DuckDuckGo's endpoint (duckduckgo.com/ac/) is NOT used: its robots.txt disallows /*? and
ac.duckduckgo.com disallows /. Brave's /api is disallowed too. Bing's suggest API was retired.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Iterator

from ..models import Evidence, strip_tagline
from ..net import FetchError
from .base import Adapter, Record, ScanContext

SUGGEST = "https://suggestqueries.google.com/complete/search"
PATTERNS = {"alternative": "{} alternative", "not_working": "{} not working", "pricing": "{} pricing"}


def parse_suggestions(body: bytes) -> list[str]:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return []
    return [s for s in (data[1] if len(data) > 1 else []) if isinstance(s, str)]


def relevant(suggestions: list[str], norm: str) -> list[str]:
    """Keep only completions that still contain every identifying word of the product name."""
    words = [w for w in norm.split() if len(w) > 1]
    return [s for s in suggestions if all(re.search(rf"\b{re.escape(w)}", s.lower()) for w in words)]


class AutocompleteAdapter(Adapter):
    name = "autocomplete"
    title = "Search autocomplete (Google suggest)"
    docs_url = "https://www.google.com/robots.txt"
    terms_url = "https://policies.google.com/terms"
    phase = 2

    def prepare(self, http):
        http.set_host_interval("suggestqueries.google.com", 2.0)

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        failures = 0
        for cand in ctx.candidates(int(ctx.scan_cfg("autocomplete_top_products", 40))):
            # People search for the product's name, not its listing tagline.
            name = re.sub(r"\s+", " ", strip_tagline(cand["name"])).strip()[:60]
            if len(cand["norm_name"]) < 3 or not name:
                continue
            for kind, pattern in PATTERNS.items():
                q = pattern.format(name.lower())
                url = SUGGEST + "?" + urllib.parse.urlencode({"client": "firefox", "hl": "en", "q": q})
                try:
                    body, ts = ctx.http.get(url)
                    failures = 0
                except FetchError as exc:
                    failures += 1
                    ctx.log.warning("autocomplete: %s", exc)
                    if failures >= 3:  # repeated failures: stop rather than hammer the endpoint
                        ctx.log.warning("autocomplete: stopping after 3 consecutive failures")
                        return
                    continue
                kept = relevant(parse_suggestions(body), cand["norm_name"])
                tags = [f"search:{kind}"] + (["replacement_search"] if kept and kind == "alternative" else [])
                if kept and kind == "not_working":
                    tags.append("negative")
                yield Evidence(
                    source="autocomplete", type="search_suggestion", url=url, date_retrieved=ts,
                    text=("Suggested searches: " + "; ".join(kept)) if kept else f"No suggestions for '{q}'",
                    metric_key=f"suggestions_{kind}", metric_value=len(kept), subject=cand["name"], tags=tags,
                    extra={"query": q, "suggestions": kept, "entity_id": cand["id"]},
                )
