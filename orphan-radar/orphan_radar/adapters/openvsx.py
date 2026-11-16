"""Open VSX Registry (open-vsx.org): VS Code-compatible extensions used by VSCodium, Cursor,
Gitpod, Theia and others.

Stands in for the Visual Studio Code Marketplace, which is skipped: its query API lives under
/_apis/, which marketplace.visualstudio.com/robots.txt disallows, and the Marketplace terms limit
use to Microsoft's own products. Open VSX documents a public API (https://open-vsx.org/swagger-ui)
and its robots.txt allows everything with Crawl-delay: 2, which this adapter obeys.
Download counts are cumulative downloads, an audience proxy, not users.
"""
from __future__ import annotations

from typing import Iterator

from ..models import Evidence, Product, metric
from ..net import FetchError
from ..textutil import iso, snippet
from .base import Adapter, Record, ScanContext

SEARCH = "https://open-vsx.org/api/-/search"


def ext_to_product(e: dict) -> Product:
    sid = f"{e['namespace']}.{e['name']}"
    return Product(
        source="openvsx", source_id=sid, name=snippet(e.get("displayName") or e["name"], 120),
        url=f"https://open-vsx.org/extension/{e['namespace']}/{e['name']}", category="editor-extension",
        user_count=None, last_updated=iso(e.get("timestamp")), rating=e.get("averageRating"),
        rating_count=e.get("reviewCount"), pricing_model="unknown", license=None,
        description=snippet(e.get("description"), 400), tags=[],
        extra={"downloads": e.get("downloadCount"), "deprecated": e.get("deprecated"), "version": e.get("version")},
    )


def ext_evidence(p: Product, e: dict, url: str, ts: str) -> list[Evidence]:
    out = [
        metric("openvsx", p, "downloads", e.get("downloadCount"), url, ts, f"Cumulative downloads on {p.url} (an audience proxy, not users)"),
        metric("openvsx", p, "rating", e.get("averageRating"), url, ts, "Average rating out of 5"),
        metric("openvsx", p, "rating_count", e.get("reviewCount"), url, ts, "Number of reviews"),
        metric("openvsx", p, "last_updated", p.last_updated, url, ts, "Date of the latest published version"),
    ]
    if e.get("deprecated"):
        out.append(Evidence(source="openvsx", type="event", url=p.url, date_retrieved=ts,
                            text=f"{p.name} is marked deprecated on Open VSX.", subject=p.name,
                            product_ref=(p.source, p.source_id), tags=["event:sunset"]))
    return [x for x in out if x]


class OpenVSXAdapter(Adapter):
    name = "openvsx"
    title = "Open VSX Registry"
    docs_url = "https://open-vsx.org/swagger-ui/index.html"
    terms_url = "https://open-vsx.org/terms-of-use"

    def prepare(self, http):
        http.set_host_interval("open-vsx.org", 2.0)

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        min_dl = int(ctx.scan_cfg("vscode_min_installs", 100000))
        for page in range(int(ctx.scan_cfg("vscode_pages", 2))):
            params = {"sortBy": "downloadCount", "sortOrder": "desc", "size": 100, "offset": page * 100}
            try:
                data, ts = ctx.http.get_json(SEARCH, params=params)
            except FetchError as exc:
                ctx.log.warning("openvsx: %s", exc)
                return
            url = SEARCH + f"?sortBy=downloadCount&sortOrder=desc&size=100&offset={page * 100}"
            for e in data.get("extensions") or []:
                if (e.get("downloadCount") or 0) < min_dl:
                    continue
                p = ext_to_product(e)
                yield p
                yield from ext_evidence(p, e, url, ts)
