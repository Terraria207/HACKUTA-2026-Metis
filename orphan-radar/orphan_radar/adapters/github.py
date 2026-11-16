"""GitHub REST API: archived or stale repositories with many stars, and their most-reacted open issues.

Docs read: https://docs.github.com/en/rest/search/search (repositories, issues; sort=reactions),
https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
Unauthenticated search allows 10 requests/minute, so searches are spaced 6.5 s apart unless
GITHUB_TOKEN is set. Issue author names are discarded. GitHub exposes no public "dependents"
count through the API, so stars are used as an audience proxy and labelled as such.
"""
from __future__ import annotations

from typing import Iterator

from ..config import env
from ..models import Evidence, Product, metric
from ..net import FetchError
from ..textutil import detect_events, iso, is_negative, mentions_paying, replacement_intent, snippet
from .base import Adapter, Record, ScanContext

SEARCH_REPOS = "https://api.github.com/search/repositories"
SEARCH_ISSUES = "https://api.github.com/search/issues"


def repo_to_product(r: dict) -> Product:
    lic = (r.get("license") or {}).get("spdx_id")
    return Product(
        source="github", source_id=r["full_name"], name=r["name"], url=r["html_url"],
        category=r.get("language") or "github-repo", user_count=None,
        last_updated=iso(r.get("pushed_at")), rating=None, rating_count=None, pricing_model="free",
        license=None if lic in (None, "NOASSERTION") else lic, description=snippet(r.get("description"), 400),
        tags=list(r.get("topics") or []), homepage=r.get("homepage") or None,
        extra={"stars": r.get("stargazers_count"), "forks": r.get("forks_count"), "archived": r.get("archived"),
               "open_issues": r.get("open_issues_count"), "pushed_at": r.get("pushed_at"), "full_name": r["full_name"]},
    )


def repo_evidence(p: Product, r: dict, url: str, ts: str) -> list[Evidence]:
    out = [
        metric("github", p, "github_stars", r.get("stargazers_count"), url, ts, f"GitHub stars on {p.url} (an audience proxy, not a user count)"),
        metric("github", p, "github_forks", r.get("forks_count"), url, ts, "Forks"),
        metric("github", p, "open_issues", r.get("open_issues_count"), url, ts, "Open issues and pull requests"),
        metric("github", p, "last_updated", iso(r.get("pushed_at")), url, ts, "Date of the last push to any branch"),
        metric("github", p, "license", p.license, url, ts, "SPDX license identifier detected by GitHub"),
    ]
    if r.get("archived"):
        out.append(Evidence(
            source="github", type="event", url=p.url, date_retrieved=ts, date_posted=None,
            text=f"The repository {r['full_name']} is archived by its owner: read-only, no further fixes.",
            subject=p.name, product_ref=(p.source, p.source_id), tags=["event:sunset", "archived"],
        ))
    return [e for e in out if e]


def issue_evidence(p: Product, item: dict, ts: str) -> Evidence:
    reactions = (item.get("reactions") or {}).get("total_count") or 0
    text = f"{item.get('title', '').strip()}. {snippet(item.get('body'), 400)}".strip(". ")
    tags = ["negative"] if is_negative(text) else []
    tags += [f"event:{k}" for k in detect_events(text)]
    if mentions_paying(text):
        tags.append("paying")
    if replacement_intent(text):
        tags.append("intent")
    if not item.get("comments"):
        tags.append("unanswered")
    return Evidence(
        source="github", type="issue", url=item["html_url"], date_retrieved=ts, date_posted=iso(item.get("created_at")),
        text=text, score=reactions, subject=p.name, product_ref=(p.source, p.source_id), tags=tags,
        extra={"reactions": reactions, "comments": item.get("comments"), "title": item.get("title")},
    )


class GitHubAdapter(Adapter):
    name = "github"
    title = "GitHub"
    docs_url = "https://docs.github.com/en/rest/search/search"
    terms_url = "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"
    api_hosts = {"api.github.com": 6.5}

    def prepare(self, http):
        super().prepare(http)
        if env("GITHUB_TOKEN"):
            http._host_intervals["api.github.com"] = 2.1  # 30 searches/minute when authenticated

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if env("GITHUB_TOKEN"):
            h["Authorization"] = f"Bearer {env('GITHUB_TOKEN')}"
        return h

    def collect(self, ctx: ScanContext) -> Iterator[Record]:
        min_stars = int(ctx.scan_cfg("github_min_stars", 3000))
        stale_before = ctx.scan_cfg("github_stale_before", "2024-06-01")
        queries = [f"archived:true stars:>{min_stars}", f"archived:false stars:>{min_stars} pushed:<{stale_before}"]
        repos: dict[str, tuple[dict, Product]] = {}
        for q in queries:
            for page in (1, 2):
                params = {"q": q, "sort": "stars", "order": "desc", "per_page": 50, "page": page}
                try:
                    data, ts = ctx.http.get_json(SEARCH_REPOS, params=params, headers=self._headers())
                except FetchError as exc:
                    ctx.log.warning("github: %s", exc)
                    break
                url = SEARCH_REPOS + f"?q={q.replace(' ', '+')}&sort=stars&order=desc&per_page=50&page={page}"
                for r in data.get("items") or []:
                    if r["full_name"] in repos:
                        continue
                    p = repo_to_product(r)
                    repos[r["full_name"]] = (r, p)
                    yield p
                    yield from repo_evidence(p, r, url, ts)

        top = sorted(repos.values(), key=lambda rp: rp[0].get("stargazers_count") or 0, reverse=True)
        for r, p in top[: int(ctx.scan_cfg("github_issue_repos", 12))]:
            params = {"q": f"repo:{r['full_name']} is:issue is:open", "sort": "reactions", "order": "desc", "per_page": 15}
            try:
                data, ts = ctx.http.get_json(SEARCH_ISSUES, params=params, headers=self._headers())
            except FetchError as exc:
                ctx.log.info("github: issues skipped: %s", exc)
                continue
            for item in data.get("items") or []:
                if "pull_request" not in item:
                    yield issue_evidence(p, item, ts)
