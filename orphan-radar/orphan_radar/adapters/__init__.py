"""Source adapters. Order matters: phase-1 adapters discover products, phase-2 adapters
enrich the current top candidates."""
from .atlassian import AtlassianAdapter
from .autocomplete import AutocompleteAdapter
from .base import Adapter, ScanContext
from .firefox import FirefoxAdapter
from .github import GitHubAdapter
from .hackernews import HackerNewsAdapter
from .openvsx import OpenVSXAdapter
from .reddit import RedditAdapter
from .stackexchange import StackExchangeAdapter
from .wordpress import WordPressAdapter

ADAPTERS: list[type[Adapter]] = [
    WordPressAdapter, FirefoxAdapter, AtlassianAdapter, GitHubAdapter, OpenVSXAdapter,
    HackerNewsAdapter, StackExchangeAdapter, RedditAdapter, AutocompleteAdapter,
]

# Sources reviewed and deliberately not implemented. Shown by `orphan-radar sources` and in the README.
SKIPPED_SOURCES = {
    "vscode-marketplace": "The only query API is under /_apis/, which marketplace.visualstudio.com/robots.txt disallows, "
                          "and the Marketplace terms restrict use to Microsoft products. Open VSX is used instead.",
    "chrome-web-store": "No public API for listings or reviews; only HTML pages, and robots.txt disallows /detail/*/reviews.",
    "shopify-app-store": "No public API for listings or reviews; HTML scraping would be the only route.",
    "apple-app-store-reviews": "The customer-review RSS feeds (/*/rss/*) and /lookup are disallowed by itunes.apple.com/robots.txt.",
    "google-play-reviews": "Reviews are only available through the Play Developer API for apps you own.",
    "duckduckgo-autocomplete": "duckduckgo.com/robots.txt disallows /*? and ac.duckduckgo.com disallows /. Google suggest is used instead.",
    "brave-suggest": "search.brave.com/robots.txt disallows /api.",
}


def get_adapters(names: list[str] | None = None) -> list[Adapter]:
    by_name = {a.name: a for a in ADAPTERS}
    if names:
        unknown = [n for n in names if n not in by_name]
        if unknown:
            raise SystemExit(f"unknown source(s): {', '.join(unknown)}. Known: {', '.join(by_name)}")
        return [by_name[n]() for n in names]
    return [a() for a in ADAPTERS]


__all__ = ["ADAPTERS", "SKIPPED_SOURCES", "Adapter", "ScanContext", "get_adapters"]
