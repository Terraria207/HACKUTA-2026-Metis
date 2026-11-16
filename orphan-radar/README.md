# Orphan Radar

Orphan Radar finds software whose users are stranded. The products it surfaces have proven demand, but they have been abandoned, displaced (shut down, sold, repriced) or are failing their users in specific, fixable ways. Those users are already looking for a replacement.

It does not brainstorm. Every opportunity is a real product with a measured audience, and every figure in a brief cites a stored evidence record with a URL and a retrieval date. An automated audit refuses to save a brief that breaks this rule.

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Scoring](#scoring)
- [The system-build prompt](#the-system-build-prompt)
- [The grounding rule and how it is enforced](#the-grounding-rule-and-how-it-is-enforced)
- [Sources](#sources), including [skipped sources and why](#skipped-sources)
- [Environment variables](#environment-variables)
- [CLI](#cli), [dashboard](#dashboard), [weekly digest](#weekly-digest), [outcome ledger](#outcome-ledger)
- [How to add an adapter](#how-to-add-an-adapter)
- [Tests](#tests)
- [Design decisions and changes from the brief](#design-decisions-and-changes-from-the-brief)
- [Top ten from the latest real scan](#top-ten-from-the-latest-real-scan)

## Quick start

Requirements: Python 3.11 or newer. Nothing else: the tool uses only the standard library (`sqlite3`, `urllib`, `http.server`, `unittest`).

```bash
cd orphan-radar
./setup.sh            # creates data/ and .env, installs ./bin/orphan-radar, runs the tests, runs a full scan, exports
./bin/orphan-radar serve   # dashboard on http://127.0.0.1:8765/
```

A full scan takes about 10 to 15 minutes. Most of that time is deliberate waiting between requests (rate limits, Crawl-delay). Responses are cached for 20 hours, so a rerun within that window is fast. Use `./setup.sh --no-scan` to install without scanning.

On Windows, use WSL, or run `python -m orphan_radar init` and `python -m orphan_radar scan` directly.

## How it works

```
collect ──> match ──> detect ──> cluster ──> score ──> filter ──> brief ──> present
(adapters)  (same product   (3 signals)  (rules, or   (0-100,     (hard      (12 sections,  (CLI, dashboard,
            across sources)              LLM if set)  breakdown)  filters)   audited)       digest, export)
```

1. **Collect.** Each source is an adapter that yields `Product` records (name, source, URL, category, user count, last update, rating, rating count, pricing model, license) and `Evidence` records (text, URL, date posted, date retrieved, type). Every figure is stored as an evidence row too (`metric_key` / `metric_value`), so scores and briefs can cite it. Scans are incremental and deduplicated: evidence has a stable key, metrics are refreshed in place, and rerunning a scan creates no duplicates.
2. **Match.** The same product is merged across sources by its canonical name. Generic names are handled conservatively: a single common word like "Gallery" stays separate per source, and free-text discussions attach only on a whole-word mention of a distinctive name (case-sensitive for common-word names such as "Dark Reader"). Ambiguous mentions stay unattached and appear on the **Leads** page.
3. **Detect** the three signals, each 0 to 1, with reasons that cite evidence:
   - **Abandonment:** months since the last update; unresolved share of recent support threads; threads with zero replies; WordPress releases behind the current version; archived repositories.
   - **Displacement:** shutdown, sunset or deprecation, acquisition, price increase, removed free tier, or a platform break, found in listings, maintainer notices, Hacker News stories and reviews. A single reviewer's claim counts as weak. Two or more independent mentions, or one from a listing, maintainer or HN story, count as strong.
   - **Pain density:** recent low-star reviews, negative support threads and issues; the most-reacted open issue; the last-year rating falling below the lifetime rating.
4. **Cluster** recent complaints into concrete, fixable problems: broken by a platform update, stopped working, paywall, data loss, crashes, slowness, ads or distrust of a new owner, a redesign that removed a feature, sync or login failures, import or export, no support, and a missing feature. Each cluster keeps links to its evidence. Rule-based clustering always runs. With a language model configured, the model may regroup and relabel the same complaints, under the grounding rule below.
5. **Score**, then apply the **hard filters** (below).
6. **Brief** every opportunity above `brief_min_score`.
7. **Present** the results in the CLI, the dashboard, the weekly digest and the Markdown/CSV export.

## Scoring

The score runs from 0 to 100, and the breakdown is always shown (CLI `show <id>`, dashboard detail page, and the end of each brief). Weights live in `config.toml` and must sum to 100. Each component is a fraction from 0 to 1 built from the sub-parts below, multiplied by its weight.

| Component | Default weight | Sub-parts (share of the component) |
|---|---|---|
| Proven demand | 20 | audience on a log scale from 10³ to 10⁷ (12/25 of the component; stars and downloads count only as a discounted proxy) · rating count (6/25) · Google suggests "‹product› alternative" (7/25), or partial credit for "not working" / "pricing" |
| Supply failure | 20 | months since the last update (8/25) · unresolved share of support threads (5/25) · last-year rating vs lifetime rating (4/25) · broken compatibility or archived (4/25) · displacement event (4/25) |
| Pain specificity | 12 | complaints fall into at most 5 fixable clusters, by share covered (9/15) · complaint volume (6/15) |
| Channel | 10 | a replacement can be listed in the same marketplace (8/15) · replacement searches exist (4/15) · public threads asking for an alternative (3/15) |
| **Potential profit** | **15** | revenue ceiling: audience on a log scale from 10³ to 10⁶ (5/15) · the incumbent charges money, declared on its listing (4/15) · users mention paying, refunds or subscriptions (3/15) · the listing names business buyers: e-commerce, agencies, teams, Jira, invoicing, ... (2/15) · people search for its pricing (1/15) |
| **Ease of development** | **15** | platform: Firefox and WordPress replacements are small, well-documented builds; Open VSX moderate; Atlassian and GitHub projects need hosting, auth or a large codebase (5/13) · the incumbent is open source, so its code and data formats can be studied (3/13) · the fixes are routine engineering: compatibility, crashes, speed, removed options (3/13) · narrow scope: three or fewer distinct problems (2/13) · **minus** up to 3 when the listing implies servers, accounts, payments, sync, AI or video |
| Timing | 8 | recency of the latest dated displacement event (7/10) · complaints are still arriving (3/10) · **minus 3** when at least 3 records say users already switched to another tool |

Potential profit and ease of development are weighted high on purpose: for a one-person studio, a modest audience that pays for a small build beats a huge audience that needs a platform. Both are read from evidence like everything else, so each sub-part cites the listing, license or complaint records it was derived from. The platform table, hard words, routine cluster list and audience ranges are in `config.toml` (`[ease]`, `[profit]`). The old "willingness to pay" component is folded into potential profit.

**Hard filters** exclude a product from the ranking and list it on the **Excluded** page with the reason:
- it handles health, financial-account or children's data (keyword lists in `config.toml`);
- it needs a license, partnership, hardware or regulatory approval (including coupon and cashback tools, which need affiliate partnerships);
- its name says it depends on another company's trademark or proprietary service (for example "for YouTube", "Meta pixel", "video downloader");
- the maintainers name a maintained successor ("deprecated, use X instead");
- the listing or a discussion says the platform now does it natively, or two or more users say so (a single user's claim becomes a risk note in the brief);
- its audience is below `min_users` (default 1,000). Products with no user count use stars or downloads as a proxy, and products with no figure at all are excluded.

You can also exclude a product by hand with `orphan-radar exclude <id> --reason "..."`.

## The system-build prompt

Each brief ends with a short build prompt. For an AI that builds whole systems, `orphan-radar buildprompt <id>` (or the dashboard button) writes a full specification from the same evidence:

1. **Mission**: what to replace, for whom, with the audience figure, last update and listing description cited.
2. **What went wrong**: the three signals and the dated quotes behind them.
3. **Product definition**: job to be done, platform, naming rules, explicit non-goals.
4. **Requirements and acceptance criteria**: Requirement A is parity with the incumbent's core job; every complaint cluster becomes a requirement with an acceptance criterion and the verbatim complaints as test cases (for example "Works on today's platform", "Core features stay free", "Never loses data or settings").
5. **Switching**: formats named in the evidence, and what a one-click, reversible import must do.
6. **Architecture and platform guidance** for WordPress plugins, WebExtensions, VS Code extensions, Atlassian Forge apps or standalone tools, plus the current platform version and the incumbent's license.
7. **Quality bar**: tests, accessibility, i18n, privacy, security, docs.
8. **Listing and launch**: where to publish, the exact searches people make, the public threads to answer.
9. **Pricing**: what the evidence says, and a default plan where it says nothing.
10. **Milestones and definition of done.**
11. **Unknowns to resolve before building**: everything the evidence could not establish.
12. **Effort and value signals**: the ease-of-development, potential-profit and demand scores with their reasons.

The prompt passes through the same citing writer and the same audit as the brief, so no figure appears without an evidence footnote and every template sentence is digit-free (a test checks that). `orphan-radar verify` audits stored build prompts too. They are exported to `report/build-prompts/` and shown at `/o/<id>/buildprompt` in the dashboard, with a copy box for the raw text.

## The grounding rule and how it is enforced

The rule from the spec: models may only summarize stored evidence, every number and claim must trace to an evidence record, anything unsupported is written as "unknown", and figures are never estimated.

How the code enforces it:

- **Figures are evidence.** Adapters store every number they read (users, ratings, versions, dates, views, points, suggestion counts) as an evidence row with the URL it came from and the time it was fetched.
- **Briefs cite.** Every figure in a brief is written through `Writer.cite()`, which appends a footnote. A footnote lists the evidence IDs behind the figure; derived counts list every record they were counted from. The brief ends with an evidence index giving each record's source, URL and retrieval date.
- **The audit refuses to save.** `audit_brief()` re-reads the finished Markdown and fails on any number that is not cited, any footnote that points at a missing record, and any record without a URL or retrieval date. `generate_brief()` raises instead of saving when the audit fails, and `orphan-radar verify` re-audits every stored brief. The tests in `tests/test_traceability.py` fail if a brief contains an uncited figure, an invented price, a citation to a missing record, or a record without a retrieval date. They also run a full pipeline over the recorded fixtures and audit every resulting brief.
- **Explicit exemptions**, each visible in the text:
  - verbatim quotes in “curly quotes” on a line that carries their citation;
  - product names, which are identifiers;
  - the `<!-- meta: ... -->` generation line;
  - config values written as `cfg:25`, which trace to `config.toml` rather than to the world.
- **Unknown, not estimated.** Prices, rivals' prices and export formats are written as "unknown" unless an evidence record states them. The one-click-import checklist is labelled "to verify, not established by the evidence".
- **Language models are fenced in.** The model receives only evidence text and must cite evidence IDs. Its output is discarded, and the rule-based result used instead, if a cluster cites an ID it was not given or contains a number that does not appear in the cited evidence.

## Sources

All adapters live in `orphan_radar/adapters/` behind the interface in `base.py`. Run `orphan-radar sources` to see live status.

**robots.txt policy.**
- Every HTML page and feed request checks robots.txt and honors `Crawl-delay`.
- Documented public APIs are used under their own published terms and rate limits, even where the host's robots.txt (written for crawlers) disallows the path. This applies to `api.wordpress.org` (`Disallow: /`) and `marketplace.atlassian.com/rest/`. Pass `scan --strict-robots` to apply robots.txt to APIs as well; those two sources are then skipped.
- Nothing is ever fetched behind a login.
- Usernames, author names and profile links are dropped by every adapter. The tests check this on recorded data.

| Source | What it gives | Access basis | Politeness |
|---|---|---|---|
| `wordpress`: WordPress.org plugin directory | active installs, last updated, tested-up-to vs current WordPress, rating, ratings by star, support threads opened vs resolved, business model, author; support and review RSS feeds (reply counts, star ratings, text) | documented API `api.wordpress.org/plugins/info/1.2`; feeds on `wordpress.org/support/` (allowed by robots.txt) | 1 s per request; feeds only for the 40 most suspicious plugins |
| `firefox`: Firefox Add-ons | daily users, rating, rating count, last updated, license, "requires payment"; recent reviews with text; recent vs lifetime rating | AMO API v5 (public; robots.txt allows) | 1 s |
| `atlassian`: Atlassian Marketplace | installs (sites), rating, review count, last modified, paid apps; recent reviews | documented REST API v2 | 1.5 s |
| `github`: GitHub | archived or stale repositories above 3,000 stars; open issues by reactions | REST search API | 6.5 s between searches without `GITHUB_TOKEN` (10/min limit) |
| `openvsx`: Open VSX Registry | VS Code-compatible extensions: downloads, rating, deprecation | documented public API; robots.txt `Crawl-delay: 2` honored | 2 s |
| `hackernews`: Hacker News | stories about shutdowns, sunsets, price increases, "alternative to", "is there a tool that"; targeted "‹product› alternative" for top candidates | Algolia HN Search API | 0.5 s |
| `stackexchange`: Stack Exchange | high-view questions without an accepted answer in tool tags; questions naming top candidates | API 2.3; `backoff` honored; stops before the daily quota runs out | 1 s |
| `autocomplete`: Google suggest | completions for "‹product› alternative", "‹product› not working", "‹product› pricing", kept only if they still name the product | `suggestqueries.google.com` publishes no robots.txt and `www.google.com/robots.txt` does not disallow `/complete`; Google's terms prohibit automated access that violates machine-readable instructions, and none apply here | 2 s, top 40 candidates only, cached 20 h |
| `reddit`: Reddit | posts about the top candidates | **only with your credentials** (Data API, client-credentials flow); off by default | 1 s |

### Skipped sources

| Source | Why it was skipped |
|---|---|
| VS Code Marketplace | The only query API is under `/_apis/`, which `marketplace.visualstudio.com/robots.txt` disallows. It is not documented for third parties, and the Marketplace terms limit use to Microsoft products. Open VSX is used instead. |
| Chrome Web Store | No public API for listings or reviews, only HTML, and robots.txt disallows `/detail/*/reviews`. |
| Shopify App Store | No public API for listings or reviews; HTML scraping would be the only route. |
| Apple App Store review feeds | `itunes.apple.com/robots.txt` disallows `/*/rss/*` and `/lookup`. |
| Google Play reviews | Only available through the Play Developer API, for apps you own. |
| DuckDuckGo autocomplete | `duckduckgo.com/robots.txt` disallows `/*?` and `ac.duckduckgo.com` disallows `/`. |
| Brave suggest | `search.brave.com/robots.txt` disallows `/api`. |

## Environment variables

Copy `.env.example` to `.env` (`setup.sh` does this). All variables are optional.

| Variable | Purpose |
|---|---|
| `ORPHAN_RADAR_LLM_PROVIDER` | `anthropic`, `openai` or `none` (default). With no provider set, everything runs except model-written cluster labels: clustering uses rules and briefs come from templates. |
| `ANTHROPIC_API_KEY` | Uses the official `anthropic` SDK (`pip install anthropic`, or `pip install .[claude]`). The default model is `claude-opus-5-5`, with structured JSON output and server-side refusal fallback enabled. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Any OpenAI-compatible `/chat/completions` endpoint, including a local server. |
| `ORPHAN_RADAR_LLM_MODEL` | Overrides the model name. |
| `GITHUB_TOKEN` | Raises GitHub's limit from 60 to 5,000 requests/hour. A token with no scopes is enough. |
| `STACKEXCHANGE_KEY` | Raises the Stack Exchange quota from 300 to 10,000 requests/day. |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | Turns on the Reddit adapter ("script" app from reddit.com/prefs/apps). |
| `ORPHAN_RADAR_DATA_DIR` | Where the SQLite database, digests and exports go (default `./data`). |
| `ORPHAN_RADAR_CONFIG` | An alternative `config.toml`. |

## CLI

```
orphan-radar scan [--source wordpress --source firefox ...] [--offline] [--strict-robots] [--no-llm] [--no-briefs]
orphan-radar analyze            # recompute signals, clusters, scores and filters from stored evidence (no network)
orphan-radar list [--top 20] [--excluded [--all]]
orphan-radar show <id>          # score breakdown with evidence ids
orphan-radar brief <id> [--out file.md] | brief --all
orphan-radar buildprompt <id> [--out file.md] | buildprompt --all   # full system-build specification
orphan-radar verify             # re-audit every stored brief and build prompt
orphan-radar export [--format md|csv|both] [--out dir]
orphan-radar digest [--days 7] [--out file.md]
orphan-radar state <id> watching|building|dismissed|new
orphan-radar exclude <id> --reason "..."
orphan-radar ledger add --name NewTool --entity <id> [--url ...] [--launched YYYY-MM-DD]
orphan-radar ledger update <ledger-id> --visitors 900 --trials 40 --paying 3 --revenue 87
orphan-radar ledger list
orphan-radar sources
orphan-radar serve [--port 8765]
```

`./bin/orphan-radar` is the launcher that `setup.sh` installs. `python3 -m orphan_radar` works too.

## Dashboard

`orphan-radar serve` runs a local dashboard (standard-library HTTP server bound to 127.0.0.1; POSTs are accepted only from its own origin). Pages:

- **Opportunities:** the ranked table with a meter per score component, filtered by source, category, signal, state, minimum score and name.
- **Detail page** per opportunity:
  - listings, score breakdown, signals and complaint clusters with quotes;
  - every evidence record with its tags, posted and retrieved dates and URL;
  - buttons to mark it watching, building or dismissed, and to (re)generate its brief and build prompt.
- **Brief:** the rendered brief with clickable footnotes.
- **Build prompt:** the full specification, with a copy box for pasting into an AI builder.
- **Excluded:** every hard-filtered product and its reason.
- **Leads:** displacement events naming no product the tool tracks yet. Useful for deciding which source to add next.
- **Ledger:** record launches and 30-day results, plus what the winners had in common.
- **Digest** and **Sources** (adapter status, skipped sources, recent scans).

## Weekly digest

Every `scan` writes `data/digests/digest-YYYY-MM-DD.md`. The digest lists new opportunities above the brief threshold, score changes of 3 points or more over the last 7 days, and the current top ten. To run it weekly:

```cron
0 7 * * 1  cd /path/to/orphan-radar && ./bin/orphan-radar scan >> data/scan.log 2>&1
```

## Outcome ledger

Record what you launched from a brief (`ledger add`, or the form on the Ledger page). The tool snapshots the opportunity's score and signals at that moment. After 30 days, record visitors, trials, paying customers and revenue. A launch counts as a winner if it has any paying customer or any revenue at 30 days. The Ledger page compares winners with the other launches: average points per score component, and the share that had each signal. Use that comparison to adjust the weights in `config.toml` by hand.

## How to add an adapter

1. Read the source's documentation, terms and robots.txt. If there is no legitimate access path, add the source to `SKIPPED_SOURCES` in `adapters/__init__.py` with the reason instead of writing an adapter.
2. Create `orphan_radar/adapters/<name>.py`:

```python
from .base import Adapter, ScanContext, Record
from ..models import Product, Evidence, metric

class ExampleAdapter(Adapter):
    name = "example"                       # used by: scan --source example
    title = "Example Marketplace"
    docs_url = "https://example.com/api/docs"
    terms_url = "https://example.com/terms"
    api_hosts = {"api.example.com": 1.0}   # documented API host -> seconds between requests
    env_required = ()                      # e.g. ("EXAMPLE_TOKEN",) to stay off until configured
    phase = 1                              # 1 = discovers products, 2 = enriches top candidates

    def collect(self, ctx: ScanContext):
        data, retrieved_at = ctx.http.get_json("https://api.example.com/apps", params={"sort": "popular"})
        for app in data["apps"]:
            p = Product(source=self.name, source_id=app["id"], name=app["name"], url=app["url"],
                        user_count=app["installs"], last_updated=app["updated"])
            yield p
            yield metric(self.name, p, "user_count", app["installs"], "https://api.example.com/apps", retrieved_at)
            # reviews, notices, ... -> Evidence(type="review", url=..., date_retrieved=retrieved_at, text=..., tags=[...])
```

3. Add the class to `ADAPTERS` in `adapters/__init__.py`. If listings there are a launch channel, add the source to `MARKETPLACES` in `facts.py` and `LISTING_MARKETPLACES` in `score.py`.
4. Record a real response into `tests/fixtures/` and add a test in `tests/test_adapters.py` that runs `collect()` through `FixtureClient`. Make sure the test also checks that no personal data survives.

Always fetch through `ctx.http`: it applies robots.txt, rate limits, retries and caching. Drop author names and profile links. Store every figure with `metric()`.

## Tests

```bash
python3 -m unittest discover -s tests -t .      # or: pytest
```

The suite covers:

- `test_adapters.py`: every adapter against responses recorded from the live APIs (`tests/fixtures/`), including rerun safety and personal-data removal.
- `test_scoring.py`: score components, config weights, the penalty, signals, hard filters, cross-source matching and clustering.
- `test_traceability.py`: the grounding rule (see above).
- `test_buildprompt.py`: the build prompt has every section, one requirement per cluster, digit-free templates, passes the audit, refuses when it cannot be traced.
- `test_web.py`: pages render, HTML is escaped, actions work, cross-origin POSTs are refused.

## Design decisions and changes from the brief

- **Standard library only.** The target machine had no `pip`, and a research tool that installs with one command and nothing to download is easier to trust and keep running. The Claude SDK is the only optional dependency.
- **Clustering and briefs work without a key.** The spec said to skip clustering and briefs without a language-model key. Instead, rule-based clustering always runs, and briefs are assembled from evidence by templates; a model only improves cluster grouping and labels. This keeps "ten well-evidenced opportunities" available on day one and makes the grounding rule easier to enforce.
- **Briefs are audited, not trusted.** A brief that cannot cite a figure is never saved.
- **Audience proxies are labelled and discounted.** GitHub stars and Open VSX downloads are not users. They count for 60% in the demand score and are labelled "proxy" everywhere.
- **Leads page.** Hacker News announcements about products the tool does not track are kept as leads, not invented as opportunities: they have no verifiable user count.
- **Extra sources** where access is legitimate: Atlassian Marketplace (paid apps make willingness to pay visible) and Open VSX (standing in for the VS Code Marketplace).
- **Two gauges for a one-person studio.** Potential profit and ease of development are scored explicitly and weighted at 15 each, so the ranking favours small, routine builds for audiences that already pay. They are heuristics read from listings, licenses and complaint types, not estimates: every sub-part cites its evidence.
- **Platform-owned incumbents** (for example plugins authored by WordPress.org or Automattic) are flagged as a risk in the brief rather than excluded.

Known limits:

- Hard-filter keyword lists and complaint rules are heuristics; check the Excluded page.
- "A maintained replacement already dominates" is only detected when the maintainers name a successor. Every brief says this remains to be checked.
- Prices are almost always "unknown", because no source used here publishes them in a reusable form.

<!-- TOP10:START -->
## Top ten from the latest real scan

Live data collected on this machine with `./setup.sh` (full scan), followed by an incremental rerun of the autocomplete source after a bug fix. No language model was configured, so clusters are rule-based and briefs come from templates.

- Scan #1, 2026-11-16T23:08:48+00:00 to 2026-11-16T23:15:23+00:00: atlassian (152 products, 1558 new evidence), autocomplete (27 new evidence), firefox (150 products, 1517 new evidence), github (200 products, 1138 new evidence), hackernews (113 new evidence), openvsx (200 products, 704 new evidence), stackexchange (252 new evidence), wordpress (948 products, 13448 new evidence). Skipped: reddit: needs environment variable(s): REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT.
- Scan #2, 2026-11-16T23:16:16+00:00 to 2026-11-16T23:19:42+00:00: autocomplete (99 new evidence).

The database holds 1,650 product listings, merged into 1,620 products, and 20,542 evidence records. 194 products were excluded by hard filters; the full list is in `report/opportunities.md` and on the dashboard's Excluded page.

Every brief below passed the traceability audit (`orphan-radar verify`). Footnote numbers are prefixed per brief so they stay unique on this page. The same briefs are in `report/briefs/`, and the full system-build specification for each is in `report/build-prompts/`.

| # | Product | Score | Signals | Sources | Top complaint cluster | Build prompt |
|---|---|---|---|---|---|---|
| 1 | [I don't care about cookies](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/) | 69.6 | abandonment, displacement, pain | firefox | Stopped doing its core job on many sites or setups (9) | [spec](report/build-prompts/249.md) |
| 2 | [ClearURLs](https://addons.mozilla.org/en-US/firefox/addon/clearurls/) | 65.5 | abandonment, displacement, pain | firefox | Crashes, errors and broken pages (2) | [spec](report/build-prompts/132.md) |
| 3 | [AMP](https://wordpress.org/plugins/amp/) | 65.5 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (4) | [spec](report/build-prompts/217.md) |
| 4 | [WooSidebars](https://wordpress.org/plugins/woosidebars/) | 65.1 | abandonment, displacement | wordpress | Broken by a platform, browser or PHP update (2) | [spec](report/build-prompts/504.md) |
| 5 | [Cookie AutoDelete](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/) | 63.0 | abandonment, displacement, pain | firefox | Stopped doing its core job on many sites or setups (3) | [spec](report/build-prompts/352.md) |
| 6 | [Health Check & Troubleshooting](https://wordpress.org/plugins/health-check/) | 62.6 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (2) | [spec](report/build-prompts/265.md) |
| 7 | [WebP Express](https://wordpress.org/plugins/webp-express/) | 62.4 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (7) | [spec](report/build-prompts/208.md) |
| 8 | [Image Optimizer – Compress Images and Convert to WebP or AVIF](https://wordpress.org/plugins/image-optimization/) | 61.6 | pain | wordpress | Features moved behind a paywall or subscription (5) | [spec](report/build-prompts/70.md) |
| 9 | [Full Page Screen Capture — FireShot](https://addons.mozilla.org/en-US/firefox/addon/fireshot/) | 61.5 | abandonment, pain | firefox | Features moved behind a paywall or subscription (3) | [spec](report/build-prompts/342.md) |
| 10 | [One Click Demo Import](https://wordpress.org/plugins/one-click-demo-import/) | 61.1 | displacement | wordpress | Cannot import, export or migrate data (2) | [spec](report/build-prompts/74.md) |

<details><summary><b>1. I don't care about cookies</b>, score 69.6</summary>

### I don't care about cookies

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 249; Orphan Radar brief -->

Score **69.6[^b1-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

I don't care about cookies on Firefox Add-ons (addons.mozilla.org) has 239,122[^b1-1] users, was last updated 2023-12-06[^b1-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “stopped doing its core job on many sites or setups”[^b1-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2023-12-06[^b1-2]; 35[^b1-2] months ago
- **Displacement event** (present):
  - acquisition mentioned: acquisition[^b1-5]; in 1[^b1-5] records; latest dated mention 2025-12-27[^b1-5]
  - sunset mentioned: sunset[^b1-6]; in 1[^b1-6] records; latest dated mention 2026-07-14[^b1-6]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 15[^b1-7] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 3.11[^b1-8] stars; recent rating 2.31[^b1-9] stars

Dated sources for the events:
- “This addon has been abandoned for three years now. Reporting broken websites doesn't work. The original author told me he sold the addon to the company behind …” (2[^b1-6]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2728251/)[^b1-6], 2026-07-14[^b1-6]
- “Keeps getting worse since croatian developer Daniel Kladnik sold the popular "I don't care about cookies" browser extension to Avast (now part of Gen Digital, …” (1[^b1-5]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2546572/)[^b1-5], 2025-12-27[^b1-5]

#### 3. Stranded users

- 239,122[^b1-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/>), read from addons.mozilla.org on 2026-11-16[^b1-1]

#### 4. Top complaints

**Stopped doing its core job on many sites or setups** (9[^b1-3] complaints)
> “Doesn't work” (1[^b1-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2776040/)[^b1-10], 2026-10-24[^b1-10]
>
> “doesn't work” (1[^b1-11]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2770500/)[^b1-11], 2026-10-16[^b1-11]
>
> “Last updated 3 years ago, owned by Avast which is part of Gen Digital. Doesn't work on lots of sites now..” (1[^b1-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2766872/)[^b1-12], 2026-10-12[^b1-12]

**Ads, tracking, or distrust of a new owner** (3[^b1-13] complaints)
> “Kill this piece of shit with fire, get "I still don't care about cookies" which is an actual non-invasive FOSS fork of this program now owned by disgusting corporations 🔥🔥” (1[^b1-14]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2785644/)[^b1-14], 2026-11-16[^b1-14]
>
> “He sold his soul and our data.” (1[^b1-15]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2739996/)[^b1-15], 2026-08-26[^b1-15]
>
> “Keeps getting worse since croatian developer Daniel Kladnik sold the popular "I don't care about cookies" browser extension to Avast (now part of Gen Digital, former Symantec). Many users became wary of their data being …” (1[^b1-5]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2546572/)[^b1-5], 2025-12-27[^b1-5]

Plus 3[^b1-16] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Get rid of cookie warnings from almost all websites!”[^b1-17]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b1-3]
- No ads, no tracking, transparent ownership, open source (fixes: ads, tracking, or distrust of a new owner)[^b1-13]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/>[^b1-17]
- Replacement searches to target (Google autocomplete):
  - `i don t care about cookies alternatives`[^b1-18]
  - `i still don t care about cookies alternative`[^b1-18]
  - `i don t care about cookies alternative reddit`[^b1-18]
  - `i don t care about cookies firefox alternative`[^b1-18]
  - `alternative zu i don't care about cookies`[^b1-18]
  - `i don't care about cookies not working`[^b1-19]
  - `i still don t care about cookies not working`[^b1-19]
- Public threads where people asked for an alternative (links only):
  - [This addon has been abandoned for three years now. Reporting broken websites doesn't …](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2728251/)[^b1-6]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: “GNU General Public License v3.0 only”[^b1-20].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “I don't care about cookies”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b1-1] |
| Abandonment | well evidenced (listing metrics) | [^b1-2] |
| Displacement event | thin (single reviewer claims) | [^b1-21] |
| Top complaints | well evidenced | [^b1-22] |
| Replacement demand in search | well evidenced | [^b1-18] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): I don't care about cookies, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “Get rid of cookie warnings from almost all websites!”[^b1-17]

Build the smallest product that fixes what its users complain about, and nothing else:
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- No ads, no tracking, transparent ownership, open source (users of the incumbent complain: ads, tracking, or distrust of a new owner)
- A one-click import of the incumbent's settings and data

Distribution: publish it on Firefox Add-ons (addons.mozilla.org), in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 16.1[^b1-23] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 9.4[^b1-24] | cfg:20 | months since last update; last-year rating below lifetime rating; displacement event: acquisition mentioned |
| pain specificity | 10.6[^b1-7] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 10[^b1-25] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| potential profit | 4[^b1-26] | cfg:15 | revenue ceiling: audience on a log scale |
| ease of development | 11.5[^b1-27] | cfg:15 | platform: a firefox replacement is a small, well-documented build; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 8[^b1-6] | cfg:8 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b1-1]: #14679 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-2]: #14682 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-3]: derived from 9 evidence records: #15369, #15370, #15371, #15374, #15377, #15378, #15380, #15381, #15384
[^b1-4]: derived from 24 evidence records: #14679, #14680, #14681, #14682, #14683, #15368, #15369, #15370, #15371, #15372, #15373, #15374, #15377, #15378, #15380, #15381, #15382, #15383, #15384, #15385, #15397, #16002, #20423, #20425
[^b1-5]: #15385 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2546572/>, retrieved 2026-11-16
[^b1-6]: #15374 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2728251/>, retrieved 2026-11-16
[^b1-7]: derived from 15 evidence records: #15368, #15369, #15370, #15371, #15372, #15373, #15374, #15377, #15378, #15380, #15381, #15382, #15383, #15384, #15385
[^b1-8]: #14680 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-9]: #15397 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=i-dont-care-about-cookies&sort=created&page_size=50>, retrieved 2026-11-16
[^b1-10]: #15369 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2776040/>, retrieved 2026-11-16
[^b1-11]: #15370 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2770500/>, retrieved 2026-11-16
[^b1-12]: #15371 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2766872/>, retrieved 2026-11-16
[^b1-13]: derived from 3 evidence records: #15368, #15373, #15385
[^b1-14]: #15368 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2785644/>, retrieved 2026-11-16
[^b1-15]: #15373 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2739996/>, retrieved 2026-11-16
[^b1-16]: derived from 3 evidence records: #15372, #15382, #15383
[^b1-17]: #16002 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/>, retrieved 2026-11-16
[^b1-18]: #20423 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+alternative>, retrieved 2026-11-16
[^b1-19]: #20424 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+not+working>, retrieved 2026-11-16
[^b1-20]: #14683 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-21]: derived from 2 evidence records: #15374, #15385
[^b1-22]: derived from 12 evidence records: #15368, #15369, #15370, #15371, #15373, #15374, #15377, #15378, #15380, #15381, #15384, #15385
[^b1-23]: derived from 3 evidence records: #14679, #14681, #20423
[^b1-24]: derived from 4 evidence records: #14680, #14682, #15385, #15397
[^b1-25]: derived from 3 evidence records: #15374, #16002, #20423
[^b1-26]: derived from 2 evidence records: #14679, #20425
[^b1-27]: derived from 14 evidence records: #14683, #15368, #15369, #15370, #15371, #15373, #15374, #15377, #15378, #15380, #15381, #15384, #15385, #16002

##### Evidence index

- #14679 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14680 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14681 addons.mozilla.org rating_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14682 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14683 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #15368 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2785644/>, retrieved 2026-11-16
- #15369 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2776040/>, retrieved 2026-11-16
- #15370 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2770500/>, retrieved 2026-11-16
- #15371 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2766872/>, retrieved 2026-11-16
- #15372 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2747698/>, retrieved 2026-11-16
- #15373 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2739996/>, retrieved 2026-11-16
- #15374 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2728251/>, retrieved 2026-11-16
- #15377 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2711157/>, retrieved 2026-11-16
- #15378 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2638227/>, retrieved 2026-11-16
- #15380 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2609697/>, retrieved 2026-11-16
- #15381 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2599425/>, retrieved 2026-11-16
- #15382 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2597188/>, retrieved 2026-11-16
- #15383 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2556633/>, retrieved 2026-11-16
- #15384 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2548069/>, retrieved 2026-11-16
- #15385 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2546572/>, retrieved 2026-11-16
- #15397 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=i-dont-care-about-cookies&sort=created&page_size=50>, retrieved 2026-11-16
- #16002 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/>, retrieved 2026-11-16
- #20423 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+alternative>, retrieved 2026-11-16
- #20424 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+not+working>, retrieved 2026-11-16
- #20425 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>2. ClearURLs</b>, score 65.5</summary>

### ClearURLs

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 132; Orphan Radar brief -->

Score **65.5[^b2-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

ClearURLs on Firefox Add-ons (addons.mozilla.org) has 513,754[^b2-1] users, was last updated 2025-02-14[^b2-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b2-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2025-02-14[^b2-2]; 21[^b2-2] months ago
- **Displacement event** (present):
  - sunset mentioned: sunset[^b2-5]; in 1[^b2-5] records; latest dated mention 2026-08-16[^b2-5]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 10[^b2-6] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.24[^b2-7] stars; recent rating 3.68[^b2-8] stars

Dated sources for the events:
- “This add-on seems to work (Firefox-ESR 140) but no longer be maintained: - On Mozilla / Add-ons / ClearURLs - "Last updated 2 years ago (Feb 5, 2025)" - "Write …” (3[^b2-5]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2737389/)[^b2-5], 2026-08-16[^b2-5]

#### 3. Stranded users

- 513,754[^b2-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/clearurls/>), read from addons.mozilla.org on 2026-11-16[^b2-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (2[^b2-3] complaints)
> “Breaks Google search AI mode (gives error message "Can't generate an AI overview right now. Try again later.")” (1[^b2-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2738839/)[^b2-9], 2026-08-22[^b2-9]
>
> “made logging in via google impossible with error 400 somehow. dont use this” (1[^b2-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736654/)[^b2-10], 2026-08-14[^b2-10]

**Stopped doing its core job on many sites or setups** (2[^b2-11] complaints)
> “Stopped working for about two months.” (1[^b2-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2750655/)[^b2-12], 2026-09-23[^b2-12]
>
> “it's useless” (1[^b2-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736934/)[^b2-13], 2026-08-14[^b2-13]

**Breaks or fails at sign-in, sync or accounts** (2[^b2-14] complaints)
> “DO NOT DOWNLOAD this extension if you use Google to log in to anything. This breaks every and any Google login. I spent so long trying to figure out the problem when it was this extension the whole time. Fix this crap …” (1[^b2-15]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2785514/)[^b2-15], 2026-11-16[^b2-15]
>
> “Broke my Google account. Getting error 400 everywhere whenever try to login via Google.” (1[^b2-16]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2765534/)[^b2-16], 2026-10-10[^b2-16]

Plus 4[^b2-17] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Automatically removes tracking parameters from URLs”[^b2-18]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b2-3]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b2-11]
- Never breaks sign-in or sync (its own or on the sites it touches); no account needed (fixes: breaks or fails at sign-in, sync or accounts)[^b2-14]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/clearurls/>[^b2-18]
- Replacement searches to target (Google autocomplete):
  - `clearurls alternative`[^b2-19]
  - `clearurls alternative chrome`[^b2-19]
- Public threads asking for an alternative: none found.

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: “GNU Lesser General Public License v3.0 only”[^b2-20].
- Forking: Forking is permitted; changes to the library itself must stay under the LGPL.
- Use a new name and new branding. Do not use “ClearURLs”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b2-1] |
| Abandonment | well evidenced (listing metrics) | [^b2-2] |
| Displacement event | thin (single reviewer claims) | [^b2-5] |
| Top complaints | thin | [^b2-21] |
| Replacement demand in search | well evidenced | [^b2-19] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): ClearURLs, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “Automatically removes tracking parameters from URLs”[^b2-18]

Build the smallest product that fixes what its users complain about, and nothing else:
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- Never breaks sign-in or sync (its own or on the sites it touches); no account needed (users of the incumbent complain: breaks or fails at sign-in, sync or accounts)
- A one-click import of the incumbent's settings and data

Distribution: publish it on Firefox Add-ons (addons.mozilla.org), in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 16.6[^b2-22] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 8.9[^b2-23] | cfg:20 | months since last update; last-year rating below lifetime rating; displacement event: sunset mentioned |
| pain specificity | 9.1[^b2-6] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 8[^b2-24] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target |
| potential profit | 4.5[^b2-25] | cfg:15 | revenue ceiling: audience on a log scale |
| ease of development | 10.4[^b2-26] | cfg:15 | platform: a firefox replacement is a small, well-documented build; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 8[^b2-5] | cfg:8 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b2-1]: #14554 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-2]: #14557 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-3]: derived from 2 evidence records: #15877, #15880
[^b2-4]: derived from 20 evidence records: #14554, #14555, #14556, #14557, #14558, #15858, #15863, #15865, #15866, #15867, #15869, #15877, #15878, #15879, #15880, #15882, #15886, #15978, #20429, #20431
[^b2-5]: #15878 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2737389/>, retrieved 2026-11-16
[^b2-6]: derived from 10 evidence records: #15858, #15863, #15865, #15866, #15867, #15869, #15877, #15879, #15880, #15882
[^b2-7]: #14555 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-8]: #15886 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=clearurls&sort=created&page_size=50>, retrieved 2026-11-16
[^b2-9]: #15877 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2738839/>, retrieved 2026-11-16
[^b2-10]: #15880 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736654/>, retrieved 2026-11-16
[^b2-11]: derived from 2 evidence records: #15869, #15879
[^b2-12]: #15869 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2750655/>, retrieved 2026-11-16
[^b2-13]: #15879 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736934/>, retrieved 2026-11-16
[^b2-14]: derived from 2 evidence records: #15858, #15866
[^b2-15]: #15858 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2785514/>, retrieved 2026-11-16
[^b2-16]: #15866 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2765534/>, retrieved 2026-11-16
[^b2-17]: derived from 4 evidence records: #15863, #15865, #15867, #15882
[^b2-18]: #15978 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/>, retrieved 2026-11-16
[^b2-19]: #20429 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=clearurls+alternative>, retrieved 2026-11-16
[^b2-20]: #14558 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-21]: derived from 6 evidence records: #15858, #15866, #15869, #15877, #15879, #15880
[^b2-22]: derived from 3 evidence records: #14554, #14556, #20429
[^b2-23]: derived from 4 evidence records: #14555, #14557, #15878, #15886
[^b2-24]: derived from 2 evidence records: #15978, #20429
[^b2-25]: derived from 2 evidence records: #14554, #20431
[^b2-26]: derived from 8 evidence records: #14558, #15858, #15866, #15869, #15877, #15879, #15880, #15978

##### Evidence index

- #14554 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14555 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14556 addons.mozilla.org rating_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14557 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #14558 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
- #15858 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2785514/>, retrieved 2026-11-16
- #15863 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2773209/>, retrieved 2026-11-16
- #15865 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2770718/>, retrieved 2026-11-16
- #15866 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2765534/>, retrieved 2026-11-16
- #15867 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2762696/>, retrieved 2026-11-16
- #15869 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2750655/>, retrieved 2026-11-16
- #15877 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2738839/>, retrieved 2026-11-16
- #15878 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2737389/>, retrieved 2026-11-16
- #15879 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736934/>, retrieved 2026-11-16
- #15880 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736654/>, retrieved 2026-11-16
- #15882 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2727672/>, retrieved 2026-11-16
- #15886 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=clearurls&sort=created&page_size=50>, retrieved 2026-11-16
- #15978 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/>, retrieved 2026-11-16
- #20429 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=clearurls+alternative>, retrieved 2026-11-16
- #20431 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=clearurls+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>3. AMP</b>, score 65.5</summary>

### AMP

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 217; Orphan Radar brief -->

Score **65.5[^b3-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

AMP on WordPress.org plugin directory has 300,000[^b3-1] users, was last updated 2025-04-10[^b3-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b3-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2025-04-10[^b3-2]; 19[^b3-2] months ago
  - recent support threads with zero replies: 3[^b3-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.8.12[^b3-6]; current WordPress is 7.1.4[^b3-7]; 3[^b3-8] major releases behind
- **Displacement event** (present):
  - platform break mentioned: platform break[^b3-9]; in 2[^b3-9] records; latest dated mention 2023-12-08[^b3-10]
  - sunset mentioned: sunset[^b3-11]; in 2[^b3-11] records; latest dated mention 2026-08-28[^b3-12]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 9[^b3-13] complaints in the last twelve months

Dated sources for the events:
- “PHP 8 deprecation warning in AMP PairedUrl.php. Hi, I’m seeing repeated PHP 8 deprecation warnings in the AMP plugin: preg_match(): Passing null to parameter …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/)[^b3-12], 2026-08-28[^b3-12]
- “PHP Deprecation and Warning Errors in AMP Plugin Logs. Issue Summary: I am seeing recurring PHP errors in my server logs related to the AMP plugin. over 170 MB …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/)[^b3-14], 2026-07-09[^b3-14]
- “I hate it! AMP is Malware!!!. 1 star AMP acts like malware. I have tried multiple times to deactivate it and delete it from my site and it keeps coming back. I …” (1[^b3-10]★) — [WordPress.org review](https://wordpress.org/support/topic/i-hate-it-amp-is-malware/)[^b3-10], 2023-12-08[^b3-10]
- “Not compatible with many plugins or themes. 2 stars When you active this plugin and each other plugin, it performs a check for compatibility with other plugins …” (2[^b3-15]★) — [WordPress.org review](https://wordpress.org/support/topic/not-compatible-with-many-plugins-or-themes/)[^b3-15], 2023-07-20[^b3-15]

#### 3. Stranded users

- 300,000[^b3-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/amp/>), read from WordPress.org on 2026-11-16[^b3-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (4[^b3-3] complaints)
> “Can’t Open AMP Setting. Hello, after a long time without using this plugin, now I want to use it but can’t. AMP Settings Something went wrong. Check your connection and open your browser console to see if there are any …” — [WordPress.org support thread](https://wordpress.org/support/topic/cant-open-amp-setting/)[^b3-16], 2026-03-04[^b3-16]
>
> “How to solve "Browser error logged in console". Hello sir, How to solve "Browser error logged in console"? Access to script at ‘ https://cdn.ampproject.org/rtv/012308181609000/v0/amp-ad-network-adsense-impl-0.1.mjs’ ; …” — [WordPress.org support thread](https://wordpress.org/support/topic/how-to-solve-browser-error-logged-in-console/)[^b3-17], 2026-07-11[^b3-17]
>
> “The AMP Site Scanner has experienced an error.. Received this error when installing a new plugin, and the popup message told me to submit to this forum. 🙂 { "message": "u(…) is not a function", "stack": "TypeError: u(…) …” — [WordPress.org support thread](https://wordpress.org/support/topic/the-amp-site-scanner-has-experienced-an-error-2/)[^b3-18], 2026-01-08[^b3-18]

**Broken by a platform, browser or PHP update** (3[^b3-19] complaints)
> “PHP 8 deprecation warning in AMP PairedUrl.php. Hi, I’m seeing repeated PHP 8 deprecation warnings in the AMP plugin: preg_match(): Passing null to parameter #2 ($subject) of type string is deprecated The warning …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/)[^b3-12], 2026-08-28[^b3-12]
>
> “PHP Deprecation and Warning Errors in AMP Plugin Logs. Issue Summary: I am seeing recurring PHP errors in my server logs related to the AMP plugin. over 170 MB log text[09-Jul-2026 11:11:41 UTC] PHP Deprecated: …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/)[^b3-14], 2026-07-09[^b3-14]
>
> “AMP conflict with block editor. Hi, I couldn’t open any article because it was giving an error, once I deactivate the AMP it all worked. The error is: TypeError: Class extends value …” — [WordPress.org support thread](https://wordpress.org/support/topic/amp-conflict-with-block-editor/)[^b3-20], 2026-03-17[^b3-20]

**Slow, heavy or resource-hungry** (1[^b3-21] complaints)
> “AMP on Woodmart Theme. Hello, I installed AMP on my website with a Woodmart theme. It looks as if my theme is not fully compatible with AMP. Also, after having checked my Page Speed on Google, the mobile aspect scored …” — [WordPress.org support thread](https://wordpress.org/support/topic/amp-on-woodmart-theme/)[^b3-21], 2026-04-16[^b3-21]

Plus 1[^b3-22] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “An easier path to great Page Experience for everyone. Powered by AMP.”[^b3-23]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b3-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b3-19]
- Lightweight and fast: lazy work, no bloat (fixes: slow, heavy or resource-hungry)[^b3-21]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/amp/>[^b3-23]
- Replacement searches: none found for the alternative / not working / pricing queries[^b3-24].
- Public threads where people asked for an alternative (links only):
  - [Most Outstanding AMP](https://wordpress.org/support/topic/most-outstanding-amp/)[^b3-25]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b3-26].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “AMP”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Nobody's autocomplete suggests searching for an alternative yet.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b3-1] |
| Abandonment | well evidenced (listing metrics) | [^b3-27] |
| Displacement event | well evidenced | [^b3-28] |
| Top complaints | well evidenced | [^b3-29] |
| Replacement demand in search | checked, none found | [^b3-30] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): AMP, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “An easier path to great Page Experience for everyone. Powered by AMP.”[^b3-23]

Build the smallest product that fixes what its users complain about, and nothing else:
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- Lightweight and fast: lazy work, no bloat (users of the incumbent complain: slow, heavy or resource-hungry)
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 9.7[^b3-31] | cfg:20 | audience on a log scale; rating count |
| supply failure | 14[^b3-32] | cfg:20 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 10.4[^b3-13] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 7.3[^b3-33] | cfg:10 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| potential profit | 4.1[^b3-34] | cfg:15 | revenue ceiling: audience on a log scale |
| ease of development | 14.4[^b3-35] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 5.6[^b3-12] | cfg:8 | recency of the latest displacement event |

#### Evidence

[^b3-1]: #2152 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b3-2]: #2155 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b3-3]: derived from 4 evidence records: #12224, #12230, #12232, #12233
[^b3-4]: derived from 19 evidence records: #2152, #2154, #2155, #2156, #2159, #2163, #12223, #12224, #12225, #12228, #12229, #12230, #12231, #12232, #12233, #12273, #13625, #20417, #20419
[^b3-5]: derived from 3 evidence records: #12225, #12228, #12229
[^b3-6]: #2156 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b3-7]: #2163 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b3-8]: derived from 2 evidence records: #2156, #2163
[^b3-9]: derived from 2 evidence records: #12261, #12269
[^b3-10]: #12261 WordPress.org review, <https://wordpress.org/support/topic/i-hate-it-amp-is-malware/>, retrieved 2026-11-16
[^b3-11]: derived from 2 evidence records: #12223, #12225
[^b3-12]: #12223 WordPress.org support thread, <https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/>, retrieved 2026-11-16
[^b3-13]: derived from 9 evidence records: #12223, #12224, #12225, #12228, #12229, #12230, #12231, #12232, #12233
[^b3-14]: #12225 WordPress.org support thread, <https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/>, retrieved 2026-11-16
[^b3-15]: #12269 WordPress.org review, <https://wordpress.org/support/topic/not-compatible-with-many-plugins-or-themes/>, retrieved 2026-11-16
[^b3-16]: #12230 WordPress.org support thread, <https://wordpress.org/support/topic/cant-open-amp-setting/>, retrieved 2026-11-16
[^b3-17]: #12224 WordPress.org support thread, <https://wordpress.org/support/topic/how-to-solve-browser-error-logged-in-console/>, retrieved 2026-11-16
[^b3-18]: #12232 WordPress.org support thread, <https://wordpress.org/support/topic/the-amp-site-scanner-has-experienced-an-error-2/>, retrieved 2026-11-16
[^b3-19]: derived from 3 evidence records: #12223, #12225, #12229
[^b3-20]: #12229 WordPress.org support thread, <https://wordpress.org/support/topic/amp-conflict-with-block-editor/>, retrieved 2026-11-16
[^b3-21]: #12228 WordPress.org support thread, <https://wordpress.org/support/topic/amp-on-woodmart-theme/>, retrieved 2026-11-16
[^b3-22]: #12231 WordPress.org support thread, <https://wordpress.org/support/topic/function-amp_has_paired_endpoint-was-called-incorrectly/>, retrieved 2026-11-16
[^b3-23]: #13625 WordPress.org description, <https://wordpress.org/plugins/amp/>, retrieved 2026-11-16
[^b3-24]: derived from 3 evidence records: #20417, #20418, #20419
[^b3-25]: #12273 WordPress.org review, <https://wordpress.org/support/topic/most-outstanding-amp/>, retrieved 2026-11-16
[^b3-26]: #2159 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b3-27]: derived from 6 evidence records: #2155, #2156, #2163, #12225, #12228, #12229
[^b3-28]: derived from 4 evidence records: #12223, #12225, #12261, #12269
[^b3-29]: derived from 8 evidence records: #12223, #12224, #12225, #12228, #12229, #12230, #12232, #12233
[^b3-30]: #20417 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=amp+alternative>, retrieved 2026-11-16
[^b3-31]: derived from 3 evidence records: #2152, #2154, #20417
[^b3-32]: derived from 7 evidence records: #2155, #2156, #2163, #12223, #12225, #12228, #12229
[^b3-33]: derived from 3 evidence records: #12273, #13625, #20417
[^b3-34]: derived from 2 evidence records: #2152, #20419
[^b3-35]: derived from 10 evidence records: #2159, #12223, #12224, #12225, #12228, #12229, #12230, #12232, #12233, #13625

##### Evidence index

- #2152 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2154 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2155 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2156 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2159 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #2163 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #12223 WordPress.org support thread, <https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/>, retrieved 2026-11-16
- #12224 WordPress.org support thread, <https://wordpress.org/support/topic/how-to-solve-browser-error-logged-in-console/>, retrieved 2026-11-16
- #12225 WordPress.org support thread, <https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/>, retrieved 2026-11-16
- #12228 WordPress.org support thread, <https://wordpress.org/support/topic/amp-on-woodmart-theme/>, retrieved 2026-11-16
- #12229 WordPress.org support thread, <https://wordpress.org/support/topic/amp-conflict-with-block-editor/>, retrieved 2026-11-16
- #12230 WordPress.org support thread, <https://wordpress.org/support/topic/cant-open-amp-setting/>, retrieved 2026-11-16
- #12231 WordPress.org support thread, <https://wordpress.org/support/topic/function-amp_has_paired_endpoint-was-called-incorrectly/>, retrieved 2026-11-16
- #12232 WordPress.org support thread, <https://wordpress.org/support/topic/the-amp-site-scanner-has-experienced-an-error-2/>, retrieved 2026-11-16
- #12233 WordPress.org support thread, <https://wordpress.org/support/topic/error-message-upon-submitting-contact-form/>, retrieved 2026-11-16
- #12261 WordPress.org review, <https://wordpress.org/support/topic/i-hate-it-amp-is-malware/>, retrieved 2026-11-16
- #12269 WordPress.org review, <https://wordpress.org/support/topic/not-compatible-with-many-plugins-or-themes/>, retrieved 2026-11-16
- #12273 WordPress.org review, <https://wordpress.org/support/topic/most-outstanding-amp/>, retrieved 2026-11-16
- #13625 WordPress.org description, <https://wordpress.org/plugins/amp/>, retrieved 2026-11-16
- #20417 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=amp+alternative>, retrieved 2026-11-16
- #20418 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=amp+not+working>, retrieved 2026-11-16
- #20419 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=amp+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>4. WooSidebars</b>, score 65.1</summary>

### WooSidebars

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 504; Orphan Radar brief -->

Score **65.1[^b4-4]** of cfg:100 · signals: abandonment, displacement

#### 1. Summary

WooSidebars on WordPress.org plugin directory has 100,000[^b4-1] users, was last updated 2024-04-03[^b4-2], and shows abandonment, displacement; its users' most common fixable complaint is “broken by a platform, browser or php update”[^b4-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2024-04-03[^b4-2]; 31[^b4-2] months ago
  - recent support threads with zero replies: 5[^b4-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.5.14[^b4-6]; current WordPress is 7.1.4[^b4-7]; 6[^b4-8] major releases behind
- **Displacement event** (present):
  - platform break mentioned: platform break[^b4-9]; in 5[^b4-9] records; latest dated mention 2023-07-20[^b4-10]
  - sunset mentioned: sunset[^b4-11]; in 4[^b4-11] records; latest dated mention 2026-05-24[^b4-12]
- **Pain density** (weak):
  - recent complaints (low-star reviews, negative threads, issues): 2[^b4-3] complaints in the last twelve months

Dated sources for the events:
- “Is this plugin abandoned?. Is it compatible with PHP 8.3? …etc… Thanks!” — [WordPress.org support thread](https://wordpress.org/support/topic/is-this-plugin-abandoned-131/)[^b4-12], 2026-05-24[^b4-12]
- “Is the plugin support abandoned?. Please bump the version. We are getting abandonment notices. @mattyza @woothemes @automattic” — [WordPress.org support thread](https://wordpress.org/support/topic/is-the-plugin-support-abandoned-2/)[^b4-13], 2024-03-12[^b4-13]
- “Compatibility with PHP 8.2. Hi. I understood that this plugin is no longer maintained but is there any way to make it works with PHP 8.2 ? It is currently in …” — [WordPress.org support thread](https://wordpress.org/support/topic/compatibility-with-php-8-2-11/)[^b4-10], 2023-07-20[^b4-10]
- “Error with PHP 8.0. Hello, I have try to set a website to PHP 8.0 but have this error : Unknown format specifier "a" in …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-with-php-8-0/)[^b4-14], 2022-03-03[^b4-14]
- “PHP 8.0 Error. 5 stars There is a problem with line 170 in class-woo-sidebars.php which can be fixed by changing the %a to a %s. From this: 'search_items' => …” (5[^b4-15]★) — [WordPress.org review](https://wordpress.org/support/topic/php-8-0-error-4/)[^b4-15], 2021-09-19[^b4-15]

#### 3. Stranded users

- 100,000[^b4-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/woosidebars/>), read from WordPress.org on 2026-11-16[^b4-1]

#### 4. Top complaints

**Broken by a platform, browser or PHP update** (2[^b4-3] complaints)
> “Is this plugin abandoned?. Is it compatible with PHP 8.3? …etc… Thanks!” — [WordPress.org support thread](https://wordpress.org/support/topic/is-this-plugin-abandoned-131/)[^b4-12], 2026-05-24[^b4-12]
>
> “Errors with PHP 8.3: translation too early. Hello, PHP 8.3 is logging errors : The bug in woosidebars – class-woo-conditions.php:57 : public function __construct () { $this->meta_box_settings['title'] = __( …” — [WordPress.org support thread](https://wordpress.org/support/topic/errors-with-php-8-3-translation-too-early/)[^b4-16], 2025-12-15[^b4-16]


#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “WooSidebars adds functionality to display different widgets in a sidebar, according to a context (for example, a specific page or a category).”[^b4-17]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b4-3]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/woosidebars/>[^b4-17]
- Replacement searches: none found for the alternative / not working / pricing queries[^b4-18].
- Public threads where people asked for an alternative (links only):
  - [“Compatibility with PHP 8.2”](https://wordpress.org/support/topic/compatibility-with-php-8-2-11/)[^b4-10]
  - [WooSidebars breaking the layout of WooCommerce Products page](https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page/)[^b4-19]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Lots of great features and works amazing!!!. 5 stars For being a free plugin it almost feels like one I paid for. Where to start so many features and customization things that I …” (5[^b4-20]★) — [WordPress.org review](https://wordpress.org/support/topic/lots-of-great-features-and-works-amazing/)[^b4-20], 2015-08-28[^b4-20]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b4-21].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “WooSidebars”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Few recent complaints, so the problem list may be incomplete or unrepresentative.
- Nobody's autocomplete suggests searching for an alternative yet.
- Maintained by the platform's own organisation (author: “WooThemes”[^b4-22]): it may be fixed or folded into the platform, and users may distrust a third-party replacement.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b4-1] |
| Abandonment | well evidenced (listing metrics) | [^b4-23] |
| Displacement event | well evidenced | [^b4-24] |
| Top complaints | thin | [^b4-3] |
| Replacement demand in search | checked, none found | [^b4-25] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): WooSidebars, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “WooSidebars adds functionality to display different widgets in a sidebar, according to a context (for example, a specific page or a category).”[^b4-17]

Build the smallest product that fixes what its users complain about, and nothing else:
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 7.3[^b4-26] | cfg:20 | audience on a log scale; rating count |
| supply failure | 16.8[^b4-27] | cfg:20 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 8.4[^b4-3] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 7.3[^b4-28] | cfg:10 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| potential profit | 5.3[^b4-29] | cfg:15 | revenue ceiling: audience on a log scale; users mention paying, refunds or subscriptions |
| ease of development | 14.4[^b4-30] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 5.6[^b4-12] | cfg:8 | recency of the latest displacement event |

#### Evidence

[^b4-1]: #4790 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-2]: #4793 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-3]: derived from 2 evidence records: #11666, #11670
[^b4-4]: derived from 36 evidence records: #4790, #4792, #4793, #4794, #4797, #4801, #11665, #11666, #11667, #11668, #11669, #11670, #11671, #11672, #11673, #11674, #11675, #11676, #11677, #11678, #11680, #11682, #11683, #11684, #11686, #11687, #11688, #11689, #11690, #11692, #11693, #11694, #11719, #13844, #20420, #20422
[^b4-5]: derived from 5 evidence records: #11665, #11667, #11668, #11669, #11670
[^b4-6]: #4794 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-7]: #4801 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b4-8]: derived from 2 evidence records: #4794, #4801
[^b4-9]: derived from 5 evidence records: #11675, #11679, #11685, #11698, #11700
[^b4-10]: #11675 WordPress.org support thread, <https://wordpress.org/support/topic/compatibility-with-php-8-2-11/>, retrieved 2026-11-16
[^b4-11]: derived from 4 evidence records: #11666, #11671, #11675, #11688
[^b4-12]: #11666 WordPress.org support thread, <https://wordpress.org/support/topic/is-this-plugin-abandoned-131/>, retrieved 2026-11-16
[^b4-13]: #11671 WordPress.org support thread, <https://wordpress.org/support/topic/is-the-plugin-support-abandoned-2/>, retrieved 2026-11-16
[^b4-14]: #11679 WordPress.org support thread, <https://wordpress.org/support/topic/error-with-php-8-0/>, retrieved 2026-11-16
[^b4-15]: #11698 WordPress.org review, <https://wordpress.org/support/topic/php-8-0-error-4/>, retrieved 2026-11-16
[^b4-16]: #11670 WordPress.org support thread, <https://wordpress.org/support/topic/errors-with-php-8-3-translation-too-early/>, retrieved 2026-11-16
[^b4-17]: #13844 WordPress.org description, <https://wordpress.org/plugins/woosidebars/>, retrieved 2026-11-16
[^b4-18]: derived from 3 evidence records: #20420, #20421, #20422
[^b4-19]: #11689 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page/>, retrieved 2026-11-16
[^b4-20]: #11719 WordPress.org review, <https://wordpress.org/support/topic/lots-of-great-features-and-works-amazing/>, retrieved 2026-11-16
[^b4-21]: #4797 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b4-22]: #4798 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-23]: derived from 8 evidence records: #4793, #4794, #4801, #11665, #11667, #11668, #11669, #11670
[^b4-24]: derived from 8 evidence records: #11666, #11671, #11675, #11679, #11685, #11688, #11698, #11700
[^b4-25]: #20420 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=woosidebars+alternative>, retrieved 2026-11-16
[^b4-26]: derived from 3 evidence records: #4790, #4792, #20420
[^b4-27]: derived from 29 evidence records: #4793, #4794, #4801, #11665, #11666, #11667, #11668, #11669, #11670, #11671, #11672, #11673, #11674, #11675, #11676, #11677, #11678, #11680, #11682, #11683, #11684, #11686, #11687, #11688, #11689, #11690, #11692, #11693, #11694
[^b4-28]: derived from 4 evidence records: #11675, #11689, #13844, #20420
[^b4-29]: derived from 3 evidence records: #4790, #11719, #20422
[^b4-30]: derived from 4 evidence records: #4797, #11666, #11670, #13844

##### Evidence index

- #4790 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #4792 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #4793 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #4794 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #4797 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #4798 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #4801 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #11665 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-php-8-5-wordpress-7-1-compatibility/>, retrieved 2026-11-16
- #11666 WordPress.org support thread, <https://wordpress.org/support/topic/is-this-plugin-abandoned-131/>, retrieved 2026-11-16
- #11667 WordPress.org support thread, <https://wordpress.org/support/topic/wordpress-6-7-notice-woosidebars-translation-loading-triggered-too-early/>, retrieved 2026-11-16
- #11668 WordPress.org support thread, <https://wordpress.org/support/topic/wordfence-detect-a-security-issues/>, retrieved 2026-11-16
- #11669 WordPress.org support thread, <https://wordpress.org/support/topic/translation-loading-triggered-too-early-2/>, retrieved 2026-11-16
- #11670 WordPress.org support thread, <https://wordpress.org/support/topic/errors-with-php-8-3-translation-too-early/>, retrieved 2026-11-16
- #11671 WordPress.org support thread, <https://wordpress.org/support/topic/is-the-plugin-support-abandoned-2/>, retrieved 2026-11-16
- #11672 WordPress.org support thread, <https://wordpress.org/support/topic/is-the-plugin-still-supported-11/>, retrieved 2026-11-16
- #11673 WordPress.org support thread, <https://wordpress.org/support/topic/theres-no-sidebar-on-shop-page/>, retrieved 2026-11-16
- #11674 WordPress.org support thread, <https://wordpress.org/support/topic/woosidbar-plug-in/>, retrieved 2026-11-16
- #11675 WordPress.org support thread, <https://wordpress.org/support/topic/compatibility-with-php-8-2-11/>, retrieved 2026-11-16
- #11676 WordPress.org support thread, <https://wordpress.org/support/topic/work-with-elementor-8/>, retrieved 2026-11-16
- #11677 WordPress.org support thread, <https://wordpress.org/support/topic/nothing-happened-did-not-work/>, retrieved 2026-11-16
- #11678 WordPress.org support thread, <https://wordpress.org/support/topic/current-version-of-plugin-some-pages-work-some-dont/>, retrieved 2026-11-16
- #11679 WordPress.org support thread, <https://wordpress.org/support/topic/error-with-php-8-0/>, retrieved 2026-11-16
- #11680 WordPress.org support thread, <https://wordpress.org/support/topic/different-sidebar-for-too-level-woocommerce-categories/>, retrieved 2026-11-16
- #11682 WordPress.org support thread, <https://wordpress.org/support/topic/sidebar-title-wont-change/>, retrieved 2026-11-16
- #11683 WordPress.org support thread, <https://wordpress.org/support/topic/odd-issue-when-refreshing-page/>, retrieved 2026-11-16
- #11684 WordPress.org support thread, <https://wordpress.org/support/topic/widget-areas-not-showing-up/>, retrieved 2026-11-16
- #11685 WordPress.org support thread, <https://wordpress.org/support/topic/not-compatible-with-php8-2/>, retrieved 2026-11-16
- #11686 WordPress.org support thread, <https://wordpress.org/support/topic/incompatibility-with-wpml-plugin-3/>, retrieved 2026-11-16
- #11687 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page-2/>, retrieved 2026-11-16
- #11688 WordPress.org support thread, <https://wordpress.org/support/topic/can-someone-from-woocommerce-be-bothered/>, retrieved 2026-11-16
- #11689 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page/>, retrieved 2026-11-16
- #11690 WordPress.org support thread, <https://wordpress.org/support/topic/update-plz/>, retrieved 2026-11-16
- #11692 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-dead/>, retrieved 2026-11-16
- #11693 WordPress.org support thread, <https://wordpress.org/support/topic/do-not-work-30/>, retrieved 2026-11-16
- #11694 WordPress.org support thread, <https://wordpress.org/support/topic/trying-to-remove-sidebar-from-some-pages/>, retrieved 2026-11-16
- #11698 WordPress.org review, <https://wordpress.org/support/topic/php-8-0-error-4/>, retrieved 2026-11-16
- #11700 WordPress.org review, <https://wordpress.org/support/topic/does-not-support-php-8-0/>, retrieved 2026-11-16
- #11719 WordPress.org review, <https://wordpress.org/support/topic/lots-of-great-features-and-works-amazing/>, retrieved 2026-11-16
- #13844 WordPress.org description, <https://wordpress.org/plugins/woosidebars/>, retrieved 2026-11-16
- #20420 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=woosidebars+alternative>, retrieved 2026-11-16
- #20421 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=woosidebars+not+working>, retrieved 2026-11-16
- #20422 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=woosidebars+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>5. Cookie AutoDelete</b>, score 63.0</summary>

### Cookie AutoDelete

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 352; Orphan Radar brief -->

Score **63[^b5-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

Cookie AutoDelete on Firefox Add-ons (addons.mozilla.org) has 157,821[^b5-1] users, was last updated 2022-12-12[^b5-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “stopped doing its core job on many sites or setups”[^b5-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2022-12-12[^b5-2]; 47[^b5-2] months ago
- **Displacement event** (present):
  - sunset mentioned: sunset[^b5-5]; in 1[^b5-5] records; latest dated mention 2025-09-10[^b5-5]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 6[^b5-6] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.54[^b5-7] stars; recent rating 4.04[^b5-8] stars

Dated sources for the events:
- “This was probably a good extension as of the last update (3 years ago). Now it's abandoned, unmantained, obsolete and maybe even dangerous. The list of domains …” (2[^b5-5]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2515531/)[^b5-5], 2025-09-10[^b5-5]

#### 3. Stranded users

- 157,821[^b5-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>), read from addons.mozilla.org on 2026-11-16[^b5-1]

#### 4. Top complaints

**Stopped doing its core job on many sites or setups** (3[^b5-3] complaints)
> “This extension hasn't been updated for 4 years and no longer works with Firefox. I now use "Auto-Delete Cookies for Privacy".” (1[^b5-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2775517/)[^b5-9], 2026-10-23[^b5-9]
>
> “It seems to me it no longer works.” (1[^b5-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2573927/)[^b5-10], 2026-01-25[^b5-10]
>
> “Unfortunately no longer works. Says it deleted cookies but the cookies are still there, very deceiving. GitHub Issues ignored, project dead. What a shame, this is a much needed extension.” (1[^b5-11]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2541886/)[^b5-11], 2025-12-08[^b5-11]

**Broken by a platform, browser or PHP update** (1[^b5-12] complaints)
> “Windows 11 / Firefox 159.0.1 (64-Bit): Cookie AutoDelete reports "cookie deleted," but the cookie is still present in the website data. This is misleading because users may rely on the confirmation and assume the cookie …” (1[^b5-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2781120/)[^b5-12], 2026-11-05[^b5-12]

**A specific feature is missing** (1[^b5-13] complaints)
> “Does not work......... No blacklist. No setting to delete everything by default unless whitelisted. wtf is this garbage?” (1[^b5-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2633438/)[^b5-13], 2026-04-06[^b5-13]

Plus 1[^b5-14] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Control your cookies! This WebExtension is inspired by Self Destructing Cookies. When a tab closes, any cookies not being used are automatically deleted. Keep the ones you trust (forever/until …”[^b5-15]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b5-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b5-12]
- Adds the requested feature (fixes: a specific feature is missing)[^b5-13]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>[^b5-15]
- Replacement searches to target (Google autocomplete):
  - `cookie autodelete alternative`[^b5-16]
  - `cookie autodelete alternative reddit`[^b5-16]
  - `cookie autodelete alternative chrome`[^b5-16]
  - `cookie autodelete not working`[^b5-17]
- Public threads where people asked for an alternative (links only):
  - [I’ve been looking for an extension that gives flexible control over cookies, and Cookie …](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2721751/)[^b5-18]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: MIT License[^b5-19].
- Forking: Forking is permitted; keep the copyright and license notice.
- Use a new name and new branding. Do not use “Cookie AutoDelete”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b5-1] |
| Abandonment | well evidenced (listing metrics) | [^b5-2] |
| Displacement event | thin (single reviewer claims) | [^b5-5] |
| Top complaints | thin | [^b5-20] |
| Replacement demand in search | well evidenced | [^b5-16] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Cookie AutoDelete, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “Control your cookies! This WebExtension is inspired by Self Destructing Cookies. When a tab closes, any cookies not being used are automatically deleted. Keep the ones you trust (forever/until …”[^b5-15]

Build the smallest product that fixes what its users complain about, and nothing else:
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- Adds the requested feature (users of the incumbent complain: a specific feature is missing)
- A one-click import of the incumbent's settings and data

Distribution: publish it on Firefox Add-ons (addons.mozilla.org), in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 15.5[^b5-21] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 8.7[^b5-22] | cfg:20 | months since last update; last-year rating below lifetime rating; displacement event: sunset mentioned |
| pain specificity | 7.2[^b5-6] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 10[^b5-23] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| potential profit | 3.7[^b5-24] | cfg:15 | revenue ceiling: audience on a log scale |
| ease of development | 13.8[^b5-25] | cfg:15 | platform: a firefox replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 4.1[^b5-5] | cfg:8 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b5-1]: #14807 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b5-2]: #14810 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b5-3]: derived from 3 evidence records: #15549, #15558, #15559
[^b5-4]: derived from 17 evidence records: #14807, #14808, #14809, #14810, #14811, #15548, #15549, #15550, #15553, #15556, #15558, #15559, #15565, #15571, #16027, #20468, #20470
[^b5-5]: #15565 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2515531/>, retrieved 2026-11-16
[^b5-6]: derived from 6 evidence records: #15548, #15549, #15550, #15556, #15558, #15559
[^b5-7]: #14808 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b5-8]: #15571 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=cookie-autodelete&sort=created&page_size=50>, retrieved 2026-11-16
[^b5-9]: #15549 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2775517/>, retrieved 2026-11-16
[^b5-10]: #15558 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2573927/>, retrieved 2026-11-16
[^b5-11]: #15559 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2541886/>, retrieved 2026-11-16
[^b5-12]: #15548 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2781120/>, retrieved 2026-11-16
[^b5-13]: #15556 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2633438/>, retrieved 2026-11-16
[^b5-14]: #15550 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2774981/>, retrieved 2026-11-16
[^b5-15]: #16027 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>, retrieved 2026-11-16
[^b5-16]: #20468 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+alternative>, retrieved 2026-11-16
[^b5-17]: #20469 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+not+working>, retrieved 2026-11-16
[^b5-18]: #15553 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2721751/>, retrieved 2026-11-16
[^b5-19]: #14811 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b5-20]: derived from 5 evidence records: #15548, #15549, #15556, #15558, #15559
[^b5-21]: derived from 3 evidence records: #14807, #14809, #20468
[^b5-22]: derived from 4 evidence records: #14808, #14810, #15565, #15571
[^b5-23]: derived from 3 evidence records: #15553, #16027, #20468
[^b5-24]: derived from 2 evidence records: #14807, #20470
[^b5-25]: derived from 7 evidence records: #14811, #15548, #15549, #15556, #15558, #15559, #16027

##### Evidence index

- #14807 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14808 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14809 addons.mozilla.org rating_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14810 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14811 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #15548 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2781120/>, retrieved 2026-11-16
- #15549 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2775517/>, retrieved 2026-11-16
- #15550 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2774981/>, retrieved 2026-11-16
- #15553 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2721751/>, retrieved 2026-11-16
- #15556 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2633438/>, retrieved 2026-11-16
- #15558 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2573927/>, retrieved 2026-11-16
- #15559 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2541886/>, retrieved 2026-11-16
- #15565 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2515531/>, retrieved 2026-11-16
- #15571 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=cookie-autodelete&sort=created&page_size=50>, retrieved 2026-11-16
- #16027 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>, retrieved 2026-11-16
- #20468 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+alternative>, retrieved 2026-11-16
- #20469 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+not+working>, retrieved 2026-11-16
- #20470 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>6. Health Check & Troubleshooting</b>, score 62.6</summary>

### Health Check & Troubleshooting

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 265; Orphan Radar brief -->

Score **62.6[^b6-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

Health Check & Troubleshooting on WordPress.org plugin directory has 200,000[^b6-1] users, was last updated 2024-07-25[^b6-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b6-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2024-07-25[^b6-2]; 28[^b6-2] months ago
  - recent support threads with zero replies: 3[^b6-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.6.11[^b6-6]; current WordPress is 7.1.4[^b6-7]; 5[^b6-8] major releases behind
- **Displacement event** (present):
  - sunset mentioned: sunset[^b6-9]; in 2[^b6-9] records; latest dated mention 2026-07-26[^b6-10]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 8[^b6-11] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 3.6[^b6-12] stars; recent rating 3[^b6-13] stars

Dated sources for the events:
- “Plugin contains an unpatched security vulnerability.. I received a security message from WordFence about this plugin. Is it still being maintained or should I …” — [WordPress.org support thread](https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/)[^b6-10], 2026-07-26[^b6-10]
- “This plugin hasn’t been tested with the latest 3 major releases of WordPress.. This plugin hasn’t been tested with the latest 3 major releases of WordPress . …” — [WordPress.org support thread](https://wordpress.org/support/topic/this-plugin-hasnt-been-tested-with-the-latest-3-major-releases-of-wordpress-29/)[^b6-14], 2026-06-18[^b6-14]

#### 3. Stranded users

- 200,000[^b6-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/health-check/>), read from WordPress.org on 2026-11-16[^b6-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (2[^b6-3] complaints)
> “PLEASE fix the security. There is no plugin that does what this does. And I did read this. https://wordpress.org/support/topic/are-you-going-to-fix-the-vulnerability/#post-18772118 But coincidence or no, very recently …” — [WordPress.org support thread](https://wordpress.org/support/topic/please-fix-the-security/)[^b6-15], 2026-06-26[^b6-15]
>
> “health-check There is a plugins_loaded error. 函数 _load_textdomain_just_in_time 调用不正确。 Translation loading for the health-check domain was triggered too early. This is usually an indicator for some code in the plugin or …” — [WordPress.org support thread](https://wordpress.org/support/topic/health-check-there-is-a-plugins_loaded-error/)[^b6-16], 2026-04-10[^b6-16]

**No answer from the developer or support** (2[^b6-17] complaints)
> “Plugin contains an unpatched security vulnerability.. I received a security message from WordFence about this plugin. Is it still being maintained or should I delete it? Critical Problems: * The Plugin "Health Check & …” — [WordPress.org support thread](https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/)[^b6-10], 2026-07-26[^b6-10]
>
> “Vulnerability found. According to WordFence and Jetpack, a vulnerability was found on December 21st in Site Health. Are you aware and when will it be resolved? I see that the plugin is not tested for compatibility since …” — [WordPress.org support thread](https://wordpress.org/support/topic/vulnerability-found-12/)[^b6-18], 2025-12-21[^b6-18]

**Broken by a platform, browser or PHP update** (1[^b6-19] complaints)
> “Bug report: _load_textdomain_just_in_time warning in Health Check on WordPress 6. I’m seeing the following notice with WP_DEBUG enabled on WordPress 6.7+: Function _load_textdomain_just_in_time was called incorrectly. …” — [WordPress.org support thread](https://wordpress.org/support/topic/bug-report-_load_textdomain_just_in_time-warning-in-health-check-on-wordpress-6/)[^b6-19], 2026-09-27[^b6-19]

**A specific feature is missing** (1[^b6-20] complaints)
> “I can’t believe that. 1 star I can’t believe anyone gave this plugin 5 stars. Troubleshooting mode will break your site. It disables ALL plugins and it says that this will only affect you and NOT your other site …” (1[^b6-20]★) — [WordPress.org review](https://wordpress.org/support/topic/i-cant-believe-that/)[^b6-20], 2026-04-04[^b6-20]

Plus 2[^b6-21] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Health Check identifies common problems, and helps you troubleshoot plugin and theme conflicts.”[^b6-22]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b6-3]
- Responsive public issue tracker (fixes: no answer from the developer or support)[^b6-17]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b6-19]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

What users say about import, export or migration:
- “HEED ALL THE WARNINGS! THIS DESTROYED MY SITE!. 5 stars What other people are saying this plugin does, it did to me. As so many people describe, I used it once, and when I exited …” (5[^b6-23]★) — [WordPress.org review](https://wordpress.org/support/topic/heed-all-the-warnings-this-destroyed-my-site/)[^b6-23], 2024-11-28[^b6-23]
- “A disaster!. 1 star A disaster! The plugin deactivated and deleted most of my plugins. Impossible to restore without restoring the site from a backup. I’ve been an experienced …” (1[^b6-24]★) — [WordPress.org review](https://wordpress.org/support/topic/a-disaster-7/)[^b6-24], 2024-08-27[^b6-24]
- “Troubleshooting mode will screw your website. 1 star I needed to use this plugin to troubleshoot a plugin conflict on my website, it ended up screwing my website. I had to restore …” (1[^b6-25]★) — [WordPress.org review](https://wordpress.org/support/topic/troubleshooting-mode-will-screw-your-website/)[^b6-25], 2024-05-24[^b6-25]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/health-check/>[^b6-22]
- Replacement searches: not checked (unknown).
- Public threads where people asked for an alternative (links only):
  - [“Why i cannot use 2025 theme on diagnose mode?”](https://wordpress.org/support/topic/why-i-cannot-use-2025-theme-on-diagnose-mode/)[^b6-26]

#### 8. Price anchor

- Incumbent: the listing's business model is 'community'[^b6-27], i.e. it declares no commercial offering. Exact prices: unknown.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b6-28].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “Health Check & Troubleshooting”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- All evidence comes from a single source.
- Replacement searches were not checked.
- Maintained by the platform's own organisation (author: “WordPress.org”[^b6-29]): it may be fixed or folded into the platform, and users may distrust a third-party replacement.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b6-1] |
| Abandonment | well evidenced (listing metrics) | [^b6-30] |
| Displacement event | well evidenced | [^b6-9] |
| Top complaints | thin | [^b6-31] |
| Replacement demand in search | unknown |  |
| Price anchor | thin (no prices, only that the incumbent charges) | [^b6-27] |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Health Check & Troubleshooting, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Health Check identifies common problems, and helps you troubleshoot plugin and theme conflicts.”[^b6-22]

Build the smallest product that fixes what its users complain about, and nothing else:
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- Responsive public issue tracker (users of the incumbent complain: no answer from the developer or support)
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 8.8[^b6-32] | cfg:20 | audience on a log scale; rating count |
| supply failure | 15.7[^b6-33] | cfg:20 | months since last update; recent issues/threads with no reply; last-year rating below lifetime rating; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 8.4[^b6-11] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 7.3[^b6-34] | cfg:10 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| potential profit | 3.8[^b6-1] | cfg:15 | revenue ceiling: audience on a log scale |
| ease of development | 13[^b6-35] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 5.6[^b6-10] | cfg:8 | recency of the latest displacement event |

#### Evidence

[^b6-1]: #2551 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-2]: #2554 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-3]: derived from 2 evidence records: #11787, #11795
[^b6-4]: derived from 24 evidence records: #2551, #2552, #2553, #2554, #2555, #2558, #2563, #11785, #11786, #11787, #11790, #11793, #11795, #11801, #11802, #11804, #11814, #11815, #11816, #11817, #11818, #11819, #11820, #13658
[^b6-5]: derived from 3 evidence records: #11790, #11793, #11802
[^b6-6]: #2555 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-7]: #2563 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b6-8]: derived from 2 evidence records: #2555, #2563
[^b6-9]: derived from 2 evidence records: #11786, #11790
[^b6-10]: #11786 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/>, retrieved 2026-11-16
[^b6-11]: derived from 8 evidence records: #11785, #11786, #11787, #11795, #11801, #11815, #11816, #11817
[^b6-12]: #2552 WordPress.org rating, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-13]: derived from 6 evidence records: #11815, #11816, #11817, #11818, #11819, #11820
[^b6-14]: #11790 WordPress.org support thread, <https://wordpress.org/support/topic/this-plugin-hasnt-been-tested-with-the-latest-3-major-releases-of-wordpress-29/>, retrieved 2026-11-16
[^b6-15]: #11787 WordPress.org support thread, <https://wordpress.org/support/topic/please-fix-the-security/>, retrieved 2026-11-16
[^b6-16]: #11795 WordPress.org support thread, <https://wordpress.org/support/topic/health-check-there-is-a-plugins_loaded-error/>, retrieved 2026-11-16
[^b6-17]: derived from 2 evidence records: #11786, #11801
[^b6-18]: #11801 WordPress.org support thread, <https://wordpress.org/support/topic/vulnerability-found-12/>, retrieved 2026-11-16
[^b6-19]: #11785 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-_load_textdomain_just_in_time-warning-in-health-check-on-wordpress-6/>, retrieved 2026-11-16
[^b6-20]: #11816 WordPress.org review, <https://wordpress.org/support/topic/i-cant-believe-that/>, retrieved 2026-11-16
[^b6-21]: derived from 2 evidence records: #11815, #11817
[^b6-22]: #13658 WordPress.org description, <https://wordpress.org/plugins/health-check/>, retrieved 2026-11-16
[^b6-23]: #11830 WordPress.org review, <https://wordpress.org/support/topic/heed-all-the-warnings-this-destroyed-my-site/>, retrieved 2026-11-16
[^b6-24]: #11832 WordPress.org review, <https://wordpress.org/support/topic/a-disaster-7/>, retrieved 2026-11-16
[^b6-25]: #11834 WordPress.org review, <https://wordpress.org/support/topic/troubleshooting-mode-will-screw-your-website/>, retrieved 2026-11-16
[^b6-26]: #11804 WordPress.org support thread, <https://wordpress.org/support/topic/why-i-cannot-use-2025-theme-on-diagnose-mode/>, retrieved 2026-11-16
[^b6-27]: #2560 WordPress.org business_model, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-28]: #2558 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b6-29]: #2559 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b6-30]: derived from 6 evidence records: #2554, #2555, #2563, #11790, #11793, #11802
[^b6-31]: derived from 6 evidence records: #11785, #11786, #11787, #11795, #11801, #11816
[^b6-32]: derived from 2 evidence records: #2551, #2553
[^b6-33]: derived from 15 evidence records: #2552, #2554, #2555, #2563, #11786, #11790, #11793, #11802, #11814, #11815, #11816, #11817, #11818, #11819, #11820
[^b6-34]: derived from 2 evidence records: #11804, #13658
[^b6-35]: derived from 8 evidence records: #2558, #11785, #11786, #11787, #11795, #11801, #11816, #13658

##### Evidence index

- #2551 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2552 WordPress.org rating, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2553 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2554 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2555 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2558 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #2559 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2560 WordPress.org business_model, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2563 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #11785 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-_load_textdomain_just_in_time-warning-in-health-check-on-wordpress-6/>, retrieved 2026-11-16
- #11786 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/>, retrieved 2026-11-16
- #11787 WordPress.org support thread, <https://wordpress.org/support/topic/please-fix-the-security/>, retrieved 2026-11-16
- #11790 WordPress.org support thread, <https://wordpress.org/support/topic/this-plugin-hasnt-been-tested-with-the-latest-3-major-releases-of-wordpress-29/>, retrieved 2026-11-16
- #11793 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-is-vulnerable-6/>, retrieved 2026-11-16
- #11795 WordPress.org support thread, <https://wordpress.org/support/topic/health-check-there-is-a-plugins_loaded-error/>, retrieved 2026-11-16
- #11801 WordPress.org support thread, <https://wordpress.org/support/topic/vulnerability-found-12/>, retrieved 2026-11-16
- #11802 WordPress.org support thread, <https://wordpress.org/support/topic/need-help-with-performance-lab-plugin-2/>, retrieved 2026-11-16
- #11804 WordPress.org support thread, <https://wordpress.org/support/topic/why-i-cannot-use-2025-theme-on-diagnose-mode/>, retrieved 2026-11-16
- #11814 WordPress.org support thread, <https://wordpress.org/support/topic/critical-autoloaded-message-even-if-autoload-is-total-786kb/>, retrieved 2026-11-16
- #11815 WordPress.org review, <https://wordpress.org/support/topic/nobody-seems-to-care/>, retrieved 2026-11-16
- #11816 WordPress.org review, <https://wordpress.org/support/topic/i-cant-believe-that/>, retrieved 2026-11-16
- #11817 WordPress.org review, <https://wordpress.org/support/topic/very-helpful-tool-for-developers-2/>, retrieved 2026-11-16
- #11818 WordPress.org review, <https://wordpress.org/support/topic/service-recommended-5/>, retrieved 2026-11-16
- #11819 WordPress.org review, <https://wordpress.org/support/topic/absolute-life-saver-on-my-agency-sub-sites/>, retrieved 2026-11-16
- #11820 WordPress.org review, <https://wordpress.org/support/topic/good-9054/>, retrieved 2026-11-16
- #11830 WordPress.org review, <https://wordpress.org/support/topic/heed-all-the-warnings-this-destroyed-my-site/>, retrieved 2026-11-16
- #11832 WordPress.org review, <https://wordpress.org/support/topic/a-disaster-7/>, retrieved 2026-11-16
- #11834 WordPress.org review, <https://wordpress.org/support/topic/troubleshooting-mode-will-screw-your-website/>, retrieved 2026-11-16
- #13658 WordPress.org description, <https://wordpress.org/plugins/health-check/>, retrieved 2026-11-16

</details>

<details><summary><b>7. WebP Express</b>, score 62.4</summary>

### WebP Express

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 208; Orphan Radar brief -->

Score **62.4[^b7-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

WebP Express on WordPress.org plugin directory has 300,000[^b7-1] users, was last updated 2026-10-18[^b7-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b7-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2026-10-18[^b7-2]; 1[^b7-2] months ago
  - support threads opened vs resolved in the last two months: 4[^b7-5] support threads opened in the last two months; 0[^b7-6] resolved; 100%[^b7-7] unresolved
  - recent support threads with zero replies: 13[^b7-8] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.9.11[^b7-9]; current WordPress is 7.1.4[^b7-10]; 2[^b7-11] major releases behind
- **Displacement event** (present):
  - sunset mentioned: sunset[^b7-12]; in 1[^b7-12] records; latest dated mention 2025-03-12[^b7-12]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 13[^b7-13] complaints in the last twelve months

Dated sources for the events:
- “abandoned plugin: Guys, this plugin was very good, but it seems that its developer abandoned it, what could have happened?” — [WordPress.org support thread](https://wordpress.org/support/topic/abandoned-plugin-107/)[^b7-12], 2025-03-12[^b7-12]

#### 3. Stranded users

- 300,000[^b7-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/webp-express/>), read from WordPress.org on 2026-11-16[^b7-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (7[^b7-3] complaints)
> “Path is outside resolved document root. Hi there I’m getting the following error which I am told comes from Webp Express when it tries to convert during a WPAllImport import Path is outside resolved document root …” — [WordPress.org support thread](https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/)[^b7-14], 2026-09-24[^b7-14]
>
> “WPBakery Bug. Hello, With the standard WPBakery settings, many photos are no longer displaying. I don’t know if the issue exists without WPBakery, but it’s not reassuring. Best Regards, Pierre” — [WordPress.org support thread](https://wordpress.org/support/topic/wpbakery-bug/)[^b7-15], 2026-09-15[^b7-15]
>
> “Error: timeout. When I click Bulk Convert, it shows ‘Receiving list of files to convert…’, and after a while, it shows ‘Error: timeout’ I set max_execution_time=50000 in php.ini, but it doesn’t working.” — [WordPress.org support thread](https://wordpress.org/support/topic/error-timeout-3/)[^b7-16], 2026-07-28[^b7-16]

**Broken by a platform, browser or PHP update** (1[^b7-17] complaints)
> “500 error: unescaped space in absolute path breaks .htaccess RewriteCond. Hi, when the WordPress path contains a space, WebP Express writes .htaccess rules that Apache cannot parse. Every request to wp-content/uploads …” — [WordPress.org support thread](https://wordpress.org/support/topic/500-error-unescaped-space-in-absolute-path-breaks-htaccess-rewritecond/)[^b7-17], 2026-11-09[^b7-17]

**Cannot import, export or migrate data** (1[^b7-18] complaints)
> “Deleting Plugin Breaks Images. I’ve gotten a lot of value from WebP Express, but it’s now redundant with an image conversion function offered by my web host. So I deactivated the plugin, which didn’t cause any issues. …” — [WordPress.org support thread](https://wordpress.org/support/topic/deleting-plugin-breaks-images/)[^b7-18], 2026-05-26[^b7-18]

**A specific feature is missing** (1[^b7-19] complaints)
> “Exclude gravity forms uploads from conversion. Hi this is a feature request. it would be great to exclude gravity forms uploads (uploads > gravity_forms) from bulk conversion. those will never be displayed on the front …” — [WordPress.org support thread](https://wordpress.org/support/topic/exclude-gravity-forms-uploads-from-conversion/)[^b7-19], 2025-12-17[^b7-19]

**Stopped doing its core job on many sites or setups** (1[^b7-20] complaints)
> “Create webp files upon request – broken. In the latest version the ‘Create webp files upon request’ does not work. The Error in the Self test is: x-webp-express-error: Sanity check FAILED for WebP Express content dir: …” — [WordPress.org support thread](https://wordpress.org/support/topic/create-webp-files-upon-request-broken/)[^b7-20], 2025-12-22[^b7-20]

Plus 2[^b7-21] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Serve autogenerated WebP images instead of jpeg/png to browsers that supports WebP.”[^b7-22]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b7-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b7-17]
- Open formats with one-click import and export (fixes: cannot import, export or migrate data)[^b7-18]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Formats named in the evidence: JSON[^b7-23], XML[^b7-24], HTML[^b7-24].

What users say about import, export or migration:
- “Path is outside resolved document root. Hi there I’m getting the following error which I am told comes from Webp Express when it tries to convert during a WPAllImport import Path …” — [WordPress.org support thread](https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/)[^b7-14], 2026-09-24[^b7-14]
- “Deleting Plugin Breaks Images. I’ve gotten a lot of value from WebP Express, but it’s now redundant with an image conversion function offered by my web host. So I deactivated the …” — [WordPress.org support thread](https://wordpress.org/support/topic/deleting-plugin-breaks-images/)[^b7-18], 2026-05-26[^b7-18]
- “wod-options.json error for auto generating images. When testing the "redirection to converter" and "WebP Realizer" we see the following error: - x-webp-express-error: Error …” — [WordPress.org support thread](https://wordpress.org/support/topic/wod-options-json-error-for-auto-generating-images/)[^b7-23], 2026-01-05[^b7-23]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/webp-express/>[^b7-22]
- Replacement searches to target (Google autocomplete):
  - `webp express alternative`[^b7-25]
- Public threads where people asked for an alternative (links only):
  - [Path is outside resolved document root](https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/)[^b7-14]
  - [webp express yoast seo bug solved](https://wordpress.org/support/topic/webp-express-yoast-seo-bug-solved/)[^b7-26]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Amazing. 5 stars This stuff is the real deal: just an app that works, no hassling like premium versions or special features. Thank you.” (5[^b7-27]★) — [WordPress.org review](https://wordpress.org/support/topic/amazing-4053/)[^b7-27], 2024-11-11[^b7-27]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b7-28].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “WebP Express”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- The incumbent was updated recently (2026-10-18[^b7-2]): it may be recovering rather than abandoned.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b7-1] |
| Abandonment | well evidenced (listing metrics) | [^b7-29] |
| Displacement event | thin (single reviewer claims) | [^b7-12] |
| Top complaints | well evidenced | [^b7-30] |
| Replacement demand in search | well evidenced | [^b7-25] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): WebP Express, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Serve autogenerated WebP images instead of jpeg/png to browsers that supports WebP.”[^b7-22]

Build the smallest product that fixes what its users complain about, and nothing else:
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- Open formats with one-click import and export (users of the incumbent complain: cannot import, export or migrate data)
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 14.8[^b7-31] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 7.8[^b7-32] | cfg:20 | months since last update; share of recent support threads unresolved; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 8.7[^b7-13] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 10[^b7-33] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| potential profit | 6.1[^b7-34] | cfg:15 | revenue ceiling: audience on a log scale; users mention paying, refunds or subscriptions |
| ease of development | 12.6[^b7-35] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 2.4[^b7-12] | cfg:8 | complaints are still arriving |

#### Evidence

[^b7-1]: #2043 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-2]: #2046 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-3]: derived from 7 evidence records: #13291, #13292, #13293, #13296, #13302, #13303, #13307
[^b7-4]: derived from 27 evidence records: #2043, #2045, #2046, #2047, #2048, #2049, #2050, #2054, #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307, #13311, #13316, #13319, #13321, #13324, #13616, #20471, #20473
[^b7-5]: #2048 WordPress.org support_threads_recent, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-6]: #2049 WordPress.org support_threads_resolved, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-7]: derived from 2 evidence records: #2048, #2049
[^b7-8]: derived from 13 evidence records: #13289, #13290, #13291, #13292, #13293, #13294, #13295, #13296, #13298, #13300, #13303, #13306, #13307
[^b7-9]: #2047 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-10]: #2054 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b7-11]: derived from 2 evidence records: #2047, #2054
[^b7-12]: #13316 WordPress.org support thread, <https://wordpress.org/support/topic/abandoned-plugin-107/>, retrieved 2026-11-16
[^b7-13]: derived from 13 evidence records: #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307, #13319, #13321
[^b7-14]: #13292 WordPress.org support thread, <https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/>, retrieved 2026-11-16
[^b7-15]: #13293 WordPress.org support thread, <https://wordpress.org/support/topic/wpbakery-bug/>, retrieved 2026-11-16
[^b7-16]: #13296 WordPress.org support thread, <https://wordpress.org/support/topic/error-timeout-3/>, retrieved 2026-11-16
[^b7-17]: #13289 WordPress.org support thread, <https://wordpress.org/support/topic/500-error-unescaped-space-in-absolute-path-breaks-htaccess-rewritecond/>, retrieved 2026-11-16
[^b7-18]: #13298 WordPress.org support thread, <https://wordpress.org/support/topic/deleting-plugin-breaks-images/>, retrieved 2026-11-16
[^b7-19]: #13306 WordPress.org support thread, <https://wordpress.org/support/topic/exclude-gravity-forms-uploads-from-conversion/>, retrieved 2026-11-16
[^b7-20]: #13305 WordPress.org support thread, <https://wordpress.org/support/topic/create-webp-files-upon-request-broken/>, retrieved 2026-11-16
[^b7-21]: derived from 2 evidence records: #13319, #13321
[^b7-22]: #13616 WordPress.org description, <https://wordpress.org/plugins/webp-express/>, retrieved 2026-11-16
[^b7-23]: #13302 WordPress.org support thread, <https://wordpress.org/support/topic/wod-options-json-error-for-auto-generating-images/>, retrieved 2026-11-16
[^b7-24]: derived from 2 evidence records: #13307, #13311
[^b7-25]: #20471 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=webp+express+alternative>, retrieved 2026-11-16
[^b7-26]: #13311 WordPress.org support thread, <https://wordpress.org/support/topic/webp-express-yoast-seo-bug-solved/>, retrieved 2026-11-16
[^b7-27]: #13324 WordPress.org review, <https://wordpress.org/support/topic/amazing-4053/>, retrieved 2026-11-16
[^b7-28]: #2050 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b7-29]: derived from 18 evidence records: #2046, #2047, #2048, #2049, #2054, #13289, #13290, #13291, #13292, #13293, #13294, #13295, #13296, #13298, #13300, #13303, #13306, #13307
[^b7-30]: derived from 11 evidence records: #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307
[^b7-31]: derived from 3 evidence records: #2043, #2045, #20471
[^b7-32]: derived from 6 evidence records: #2046, #2047, #2048, #2049, #2054, #13316
[^b7-33]: derived from 4 evidence records: #13292, #13311, #13616, #20471
[^b7-34]: derived from 3 evidence records: #2043, #13324, #20473
[^b7-35]: derived from 13 evidence records: #2050, #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307, #13616

##### Evidence index

- #2043 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2045 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2046 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2047 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2048 WordPress.org support_threads_recent, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2049 WordPress.org support_threads_resolved, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #2050 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #2054 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #13289 WordPress.org support thread, <https://wordpress.org/support/topic/500-error-unescaped-space-in-absolute-path-breaks-htaccess-rewritecond/>, retrieved 2026-11-16
- #13290 WordPress.org support thread, <https://wordpress.org/support/topic/tested-6-9-11-update-planned-wordpress-7-1-4/>, retrieved 2026-11-16
- #13291 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-converted-webp-is-written-to-the-main-uploads-folder-not-the-folde/>, retrieved 2026-11-16
- #13292 WordPress.org support thread, <https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/>, retrieved 2026-11-16
- #13293 WordPress.org support thread, <https://wordpress.org/support/topic/wpbakery-bug/>, retrieved 2026-11-16
- #13294 WordPress.org support thread, <https://wordpress.org/support/topic/webp-express-constant-hdom_-already-defined-warnings-flood-log-86-gb/>, retrieved 2026-11-16
- #13295 WordPress.org support thread, <https://wordpress.org/support/topic/files-flagged-for-known-vulnerabilities/>, retrieved 2026-11-16
- #13296 WordPress.org support thread, <https://wordpress.org/support/topic/error-timeout-3/>, retrieved 2026-11-16
- #13298 WordPress.org support thread, <https://wordpress.org/support/topic/deleting-plugin-breaks-images/>, retrieved 2026-11-16
- #13300 WordPress.org support thread, <https://wordpress.org/support/topic/using-webp-express-with-bedrock-git-deploy/>, retrieved 2026-11-16
- #13302 WordPress.org support thread, <https://wordpress.org/support/topic/wod-options-json-error-for-auto-generating-images/>, retrieved 2026-11-16
- #13303 WordPress.org support thread, <https://wordpress.org/support/topic/webp-files-are-not-deleted-after-deleting-the-original-file/>, retrieved 2026-11-16
- #13305 WordPress.org support thread, <https://wordpress.org/support/topic/create-webp-files-upon-request-broken/>, retrieved 2026-11-16
- #13306 WordPress.org support thread, <https://wordpress.org/support/topic/exclude-gravity-forms-uploads-from-conversion/>, retrieved 2026-11-16
- #13307 WordPress.org support thread, <https://wordpress.org/support/topic/yoast-post-xml-parse-error/>, retrieved 2026-11-16
- #13311 WordPress.org support thread, <https://wordpress.org/support/topic/webp-express-yoast-seo-bug-solved/>, retrieved 2026-11-16
- #13316 WordPress.org support thread, <https://wordpress.org/support/topic/abandoned-plugin-107/>, retrieved 2026-11-16
- #13319 WordPress.org review, <https://wordpress.org/support/topic/unterdruckt-anzeige-neuer-bilder/>, retrieved 2026-11-16
- #13321 WordPress.org review, <https://wordpress.org/support/topic/causes-conflicts-2/>, retrieved 2026-11-16
- #13324 WordPress.org review, <https://wordpress.org/support/topic/amazing-4053/>, retrieved 2026-11-16
- #13616 WordPress.org description, <https://wordpress.org/plugins/webp-express/>, retrieved 2026-11-16
- #20471 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=webp+express+alternative>, retrieved 2026-11-16
- #20473 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=webp+express+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>8. Image Optimizer – Compress Images and Convert to WebP or AVIF</b>, score 61.6</summary>

### Image Optimizer – Compress Images and Convert to WebP or AVIF

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 70; Orphan Radar brief -->

Score **61.6[^b8-4]** of cfg:100 · signals: pain

#### 1. Summary

Image Optimizer – Compress Images and Convert to WebP or AVIF on WordPress.org plugin directory has 1,000,000[^b8-1] users, was last updated 2026-09-22[^b8-2], and shows pain; its users' most common fixable complaint is “features moved behind a paywall or subscription”[^b8-3].

#### 2. What happened

- **Abandonment** (weak):
  - months since last update: last updated 2026-09-22[^b8-2]; 2[^b8-2] months ago
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 7.0.8[^b8-5]; current WordPress is 7.1.4[^b8-6]; 1[^b8-7] major releases behind
- **Displacement event** (weak):
  - platform break mentioned: platform break[^b8-8]; in 1[^b8-8] records; latest dated mention 2024-10-06[^b8-8]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 13[^b8-9] complaints in the last twelve months

Dated sources for the events:
- “Heads up: Not compatible with media cloud offload. Just in case anyone else might try to mix this with the cloud offload plugin https://mediacloud.press/ It …” — [WordPress.org support thread](https://wordpress.org/support/topic/heads-up-not-compatible-with-media-cloud-offload/)[^b8-8], 2024-10-06[^b8-8]

#### 3. Stranded users

- 1,000,000[^b8-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/image-optimization/>), read from WordPress.org on 2026-11-16[^b8-1]

#### 4. Top complaints

**Features moved behind a paywall or subscription** (5[^b8-3] complaints)
> “Cry for Credit Upgrade.. 1 star Barely cuts the image size by 50% – deactivating.” (1[^b8-10]★) — [WordPress.org review](https://wordpress.org/support/topic/cry-for-credit-upgrade/)[^b8-10], 2026-10-09[^b8-10]
>
> “Another Bait and Switch Plugin. 1 star This is another bait and switch plugin where they offer a service for free for a limited time, then stop providing the service because they want you to go pro. No thank you. I can …” (1[^b8-11]★) — [WordPress.org review](https://wordpress.org/support/topic/another-bait-and-switch-plugin/)[^b8-11], 2026-06-19[^b8-11]
>
> “Including all photo sizes in the 200 free photo limit. 1 star Including all photo sizes in the 200 free photo limit really makes one feel cheated. It’s a disgraceful tactic to get people to upgrade to a paid package. …” (1[^b8-12]★) — [WordPress.org review](https://wordpress.org/support/topic/including-all-photo-sizes-in-the-200-free-photo-limit/)[^b8-12], 2026-02-12[^b8-12]

**Broken by a platform, browser or PHP update** (3[^b8-13] complaints)
> “Fatal Error on Deactivation. Plugin was not running because of missing exif and filinfo. Attempting to deactivate results in the following error: Fatal error: Uncaught TypeError: call_user_func_array(): Argument #1 …” — [WordPress.org support thread](https://wordpress.org/support/topic/fatal-error-on-deactivation-2/)[^b8-14], 2026-06-11[^b8-14]
>
> “Breaks Post Editing with Javascript Console Errors. 1 star We were upgraded to WordPress 6.9 and our post editing capabilities broke because of this plugin. There were numerous console errors and we could not use the …” (1[^b8-15]★) — [WordPress.org review](https://wordpress.org/support/topic/breaks-post-editing-with-javascript-console-errors/)[^b8-15], 2026-01-06[^b8-15]
>
> “Fatals with 1.7.0 Update. Seeing this fatal on a large number of sites: PHP Fatal error: Uncaught TypeError: ImageOptimization\Modules\Connect\Module::get_connect(): Return value must be of type …” — [WordPress.org support thread](https://wordpress.org/support/topic/fatals-with-1-7-0-update/)[^b8-16], 2026-01-20[^b8-16]

**Stopped doing its core job on many sites or setups** (2[^b8-17] complaints)
> “Don’t use. 1 star Don’t use broke my website, very bad code. This topic was modified 9 months, 4 weeks ago by hacktronics .” (1[^b8-18]★) — [WordPress.org review](https://wordpress.org/support/topic/dont-use-29/)[^b8-18], 2026-01-21[^b8-18]
>
> “Subscription fees are non-refundable. 1 star Be prepared that if after purchasing a subscription the plugin does not work, no one will refund your money. Instead of a refund, they ask for access to the site to see why …” (1[^b8-19]★) — [WordPress.org review](https://wordpress.org/support/topic/subscription-fees-are-non-refundable/)[^b8-19], 2025-12-15[^b8-19]

**Crashes, errors and broken pages** (1[^b8-20] complaints)
> “Poor user experience. 1 star Extremely poor experience. This plugin ruined my homepage layout immediately after activation. To make matters worse, I encountered an error when trying to deactivate it. I deeply regret …” (1[^b8-20]★) — [WordPress.org review](https://wordpress.org/support/topic/poor-user-experience-6/)[^b8-20], 2026-04-27[^b8-20]

**Slow, heavy or resource-hungry** (1[^b8-21] complaints)
> “Don’t Use. 1 star With a jpeg quality 11 image quality ca 4% memory is saved – a total waste of money … Bulk optimisation fails completely …” (1[^b8-21]★) — [WordPress.org review](https://wordpress.org/support/topic/dont-use-28/)[^b8-21], 2025-12-16[^b8-21]

Plus 1[^b8-22] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Image Optimizer is an easy-to-use WordPress plugin that reduces image size through various compression and resizing techniques – all of which preserve …”[^b8-23]
- Core features free, or a fair one-time price (fixes: features moved behind a paywall or subscription)[^b8-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b8-13]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b8-17]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

What users say about import, export or migration:
- “crash my site. When you activate the plugin although all the images are on the server, most have disappeared from the posts where they should be. Deactivating the plugin did not …” — [WordPress.org support thread](https://wordpress.org/support/topic/crash-my-site-13/)[^b8-24], 2024-02-05[^b8-24]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/image-optimization/>[^b8-23]
- Replacement searches to target (Google autocomplete):
  - `ewww image optimizer alternative`[^b8-25]
  - `elementor image optimizer not working`[^b8-26]
  - `ewww image optimizer webp not working`[^b8-26]
  - `ewww image optimizer pricing`[^b8-27]
  - `elementor image optimizer pricing`[^b8-27]
  - `fastly image optimizer pricing`[^b8-27]
  - `image optimizer increase size`[^b8-27]
- Public threads where people asked for an alternative (links only):
  - [Before switch from imagify to Elementor image optimize](https://wordpress.org/support/topic/before-switch-from-imagify-to-elementor-image-option/)[^b8-28]
  - [Restore original image not working](https://wordpress.org/support/topic/restore-original-image-not-working/)[^b8-29]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “It works for some. 3 stars Optimized some of our media, only hundreds out of thousands. I guess that’s what I get for not paying for it?” (3[^b8-30]★) — [WordPress.org review](https://wordpress.org/support/topic/it-works-for-some/)[^b8-30], 2026-10-28[^b8-30]
  - “Another Bait and Switch Plugin. 1 star This is another bait and switch plugin where they offer a service for free for a limited time, then stop providing the service because they …” (1[^b8-11]★) — [WordPress.org review](https://wordpress.org/support/topic/another-bait-and-switch-plugin/)[^b8-11], 2026-06-19[^b8-11]
  - “Cheated by this company. 1 star A couple days ago, I Paid $60 to purchase an upgrade for Elementor as part of my WordPress. It had a feature called Image Optimizer in side it. I …” (1[^b8-31]★) — [WordPress.org review](https://wordpress.org/support/topic/cheated-by-this-company/)[^b8-31], 2026-06-07[^b8-31]
  - “Subscription fees are non-refundable. 1 star Be prepared that if after purchasing a subscription the plugin does not work, no one will refund your money. Instead of a refund, they …” (1[^b8-19]★) — [WordPress.org review](https://wordpress.org/support/topic/subscription-fees-are-non-refundable/)[^b8-19], 2025-12-15[^b8-19]
- People search for “Image Optimizer – Compress Images and Convert to WebP or AVIF pricing”[^b8-27].
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b8-32].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “Image Optimizer – Compress Images and Convert to WebP or AVIF”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- The incumbent was updated recently (2026-09-22[^b8-2]): it may be recovering rather than abandoned.
- Fewer than two of the three signals are present; the opportunity rests on one kind of evidence.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b8-1] |
| Abandonment | thin | [^b8-33] |
| Displacement event | thin (single reviewer claims) | [^b8-8] |
| Top complaints | well evidenced | [^b8-34] |
| Replacement demand in search | well evidenced | [^b8-25] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Image Optimizer – Compress Images and Convert to WebP or AVIF, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Image Optimizer is an easy-to-use WordPress plugin that reduces image size through various compression and resizing techniques – all of which preserve …”[^b8-23]

Build the smallest product that fixes what its users complain about, and nothing else:
- Core features free, or a fair one-time price (users of the incumbent complain: features moved behind a paywall or subscription)
- Works on the current platform release and PHP version (users of the incumbent complain: broken by a platform, browser or php update)
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 15.6[^b8-35] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 4.1[^b8-36] | cfg:20 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: platform break mentioned |
| pain specificity | 10.3[^b8-9] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 10[^b8-37] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| potential profit | 9[^b8-38] | cfg:15 | revenue ceiling: audience on a log scale; users mention paying, refunds or subscriptions; people search for its pricing |
| ease of development | 12.6[^b8-39] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | none | cfg:8 | nothing |

#### Evidence

[^b8-1]: #701 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-2]: #704 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-3]: derived from 5 evidence records: #11967, #11969, #11970, #11972, #11978
[^b8-4]: derived from 31 evidence records: #701, #703, #704, #705, #708, #712, #11942, #11943, #11952, #11954, #11955, #11959, #11960, #11965, #11967, #11969, #11970, #11972, #11974, #11978, #11979, #11980, #11981, #11982, #11983, #11987, #11989, #11992, #13506, #20480, #20482
[^b8-5]: #705 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-6]: #712 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b8-7]: derived from 2 evidence records: #705, #712
[^b8-8]: #11952 WordPress.org support thread, <https://wordpress.org/support/topic/heads-up-not-compatible-with-media-cloud-offload/>, retrieved 2026-11-16
[^b8-9]: derived from 13 evidence records: #11942, #11943, #11967, #11969, #11970, #11972, #11974, #11978, #11979, #11980, #11981, #11982, #11983
[^b8-10]: #11967 WordPress.org review, <https://wordpress.org/support/topic/cry-for-credit-upgrade/>, retrieved 2026-11-16
[^b8-11]: #11970 WordPress.org review, <https://wordpress.org/support/topic/another-bait-and-switch-plugin/>, retrieved 2026-11-16
[^b8-12]: #11978 WordPress.org review, <https://wordpress.org/support/topic/including-all-photo-sizes-in-the-200-free-photo-limit/>, retrieved 2026-11-16
[^b8-13]: derived from 3 evidence records: #11942, #11943, #11981
[^b8-14]: #11942 WordPress.org support thread, <https://wordpress.org/support/topic/fatal-error-on-deactivation-2/>, retrieved 2026-11-16
[^b8-15]: #11981 WordPress.org review, <https://wordpress.org/support/topic/breaks-post-editing-with-javascript-console-errors/>, retrieved 2026-11-16
[^b8-16]: #11943 WordPress.org support thread, <https://wordpress.org/support/topic/fatals-with-1-7-0-update/>, retrieved 2026-11-16
[^b8-17]: derived from 2 evidence records: #11980, #11983
[^b8-18]: #11980 WordPress.org review, <https://wordpress.org/support/topic/dont-use-29/>, retrieved 2026-11-16
[^b8-19]: #11983 WordPress.org review, <https://wordpress.org/support/topic/subscription-fees-are-non-refundable/>, retrieved 2026-11-16
[^b8-20]: #11974 WordPress.org review, <https://wordpress.org/support/topic/poor-user-experience-6/>, retrieved 2026-11-16
[^b8-21]: #11982 WordPress.org review, <https://wordpress.org/support/topic/dont-use-28/>, retrieved 2026-11-16
[^b8-22]: #11979 WordPress.org review, <https://wordpress.org/support/topic/its-just-bad/>, retrieved 2026-11-16
[^b8-23]: #13506 WordPress.org description, <https://wordpress.org/plugins/image-optimization/>, retrieved 2026-11-16
[^b8-24]: #11964 WordPress.org support thread, <https://wordpress.org/support/topic/crash-my-site-13/>, retrieved 2026-11-16
[^b8-25]: #20480 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+alternative>, retrieved 2026-11-16
[^b8-26]: #20481 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+not+working>, retrieved 2026-11-16
[^b8-27]: #20482 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+pricing>, retrieved 2026-11-16
[^b8-28]: #11955 WordPress.org support thread, <https://wordpress.org/support/topic/before-switch-from-imagify-to-elementor-image-option/>, retrieved 2026-11-16
[^b8-29]: #11960 WordPress.org support thread, <https://wordpress.org/support/topic/restore-original-image-not-working/>, retrieved 2026-11-16
[^b8-30]: #11965 WordPress.org review, <https://wordpress.org/support/topic/it-works-for-some/>, retrieved 2026-11-16
[^b8-31]: #11972 WordPress.org review, <https://wordpress.org/support/topic/cheated-by-this-company/>, retrieved 2026-11-16
[^b8-32]: #708 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b8-33]: derived from 3 evidence records: #704, #705, #712
[^b8-34]: derived from 12 evidence records: #11942, #11943, #11967, #11969, #11970, #11972, #11974, #11978, #11980, #11981, #11982, #11983
[^b8-35]: derived from 3 evidence records: #701, #703, #20480
[^b8-36]: derived from 8 evidence records: #704, #705, #712, #11952, #11954, #11955, #11959, #11960
[^b8-37]: derived from 4 evidence records: #11955, #11960, #13506, #20480
[^b8-38]: derived from 9 evidence records: #701, #11965, #11970, #11972, #11983, #11987, #11989, #11992, #20482
[^b8-39]: derived from 14 evidence records: #708, #11942, #11943, #11967, #11969, #11970, #11972, #11974, #11978, #11980, #11981, #11982, #11983, #13506

##### Evidence index

- #701 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #703 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #704 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #705 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #708 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #712 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #11942 WordPress.org support thread, <https://wordpress.org/support/topic/fatal-error-on-deactivation-2/>, retrieved 2026-11-16
- #11943 WordPress.org support thread, <https://wordpress.org/support/topic/fatals-with-1-7-0-update/>, retrieved 2026-11-16
- #11952 WordPress.org support thread, <https://wordpress.org/support/topic/heads-up-not-compatible-with-media-cloud-offload/>, retrieved 2026-11-16
- #11954 WordPress.org support thread, <https://wordpress.org/support/topic/optimize-not-working-id-same-name/>, retrieved 2026-11-16
- #11955 WordPress.org support thread, <https://wordpress.org/support/topic/before-switch-from-imagify-to-elementor-image-option/>, retrieved 2026-11-16
- #11959 WordPress.org support thread, <https://wordpress.org/support/topic/media-library-now-not-working/>, retrieved 2026-11-16
- #11960 WordPress.org support thread, <https://wordpress.org/support/topic/restore-original-image-not-working/>, retrieved 2026-11-16
- #11964 WordPress.org support thread, <https://wordpress.org/support/topic/crash-my-site-13/>, retrieved 2026-11-16
- #11965 WordPress.org review, <https://wordpress.org/support/topic/it-works-for-some/>, retrieved 2026-11-16
- #11967 WordPress.org review, <https://wordpress.org/support/topic/cry-for-credit-upgrade/>, retrieved 2026-11-16
- #11969 WordPress.org review, <https://wordpress.org/support/topic/poor-image-quality-s-l-o-w-processing-high-resource-usage-frequent-failures/>, retrieved 2026-11-16
- #11970 WordPress.org review, <https://wordpress.org/support/topic/another-bait-and-switch-plugin/>, retrieved 2026-11-16
- #11972 WordPress.org review, <https://wordpress.org/support/topic/cheated-by-this-company/>, retrieved 2026-11-16
- #11974 WordPress.org review, <https://wordpress.org/support/topic/poor-user-experience-6/>, retrieved 2026-11-16
- #11978 WordPress.org review, <https://wordpress.org/support/topic/including-all-photo-sizes-in-the-200-free-photo-limit/>, retrieved 2026-11-16
- #11979 WordPress.org review, <https://wordpress.org/support/topic/its-just-bad/>, retrieved 2026-11-16
- #11980 WordPress.org review, <https://wordpress.org/support/topic/dont-use-29/>, retrieved 2026-11-16
- #11981 WordPress.org review, <https://wordpress.org/support/topic/breaks-post-editing-with-javascript-console-errors/>, retrieved 2026-11-16
- #11982 WordPress.org review, <https://wordpress.org/support/topic/dont-use-28/>, retrieved 2026-11-16
- #11983 WordPress.org review, <https://wordpress.org/support/topic/subscription-fees-are-non-refundable/>, retrieved 2026-11-16
- #11987 WordPress.org review, <https://wordpress.org/support/topic/no-refund-policy-for-not-working-plugin-is-absurd/>, retrieved 2026-11-16
- #11989 WordPress.org review, <https://wordpress.org/support/topic/no-way-13/>, retrieved 2026-11-16
- #11992 WordPress.org review, <https://wordpress.org/support/topic/messy-app-3/>, retrieved 2026-11-16
- #13506 WordPress.org description, <https://wordpress.org/plugins/image-optimization/>, retrieved 2026-11-16
- #20480 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+alternative>, retrieved 2026-11-16
- #20481 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+not+working>, retrieved 2026-11-16
- #20482 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>9. Full Page Screen Capture — FireShot</b>, score 61.5</summary>

### Full Page Screen Capture — FireShot

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 342; Orphan Radar brief -->

Score **61.5[^b9-4]** of cfg:100 · signals: abandonment, pain

#### 1. Summary

Full Page Screen Capture — FireShot on Firefox Add-ons (addons.mozilla.org) has 175,676[^b9-1] users, was last updated 2023-06-21[^b9-2], and shows abandonment, pain; its users' most common fixable complaint is “features moved behind a paywall or subscription”[^b9-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2023-06-21[^b9-2]; 41[^b9-2] months ago
- **Displacement event**: none found.
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 7[^b9-5] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.63[^b9-6] stars; recent rating 3.92[^b9-7] stars

#### 3. Stranded users

- 175,676[^b9-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/fireshot/>), read from addons.mozilla.org on 2026-11-16[^b9-1]

#### 4. Top complaints

**Features moved behind a paywall or subscription** (3[^b9-3] complaints)
> “A pity to not offer for free or at a reasonable price this basic tool. To get a screenshot of the full web page, including the section that needs to be scrolled down, it can be done natively in firefox: …” (2[^b9-8]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/)[^b9-8], 2026-10-03[^b9-8]
>
> “Always auto updating for nothing except to force you to try the pro version (with a badge in the icon), even if the update parameter is off. Need the paid version for text selection in the saved pdf. Was good, now …” (1[^b9-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/)[^b9-9], 2026-09-16[^b9-9]
>
> “It requires a paid subscription to get proper links in a PDF snapshot. It also gets updated way too frequently, without any new features, but just ask from the user to pay for a subscription. It is not worth it.” (1[^b9-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/)[^b9-10], 2026-07-07[^b9-10]

**Stopped doing its core job on many sites or setups** (2[^b9-11] complaints)
> “Used to be good, now useless without paid subscription. Away with it!” (1[^b9-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/)[^b9-12], 2026-09-23[^b9-12]
>
> “stopped working. i now use "awesome screenshot"” (2[^b9-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2720187/)[^b9-13], 2026-06-13[^b9-13]

Plus 2[^b9-14] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “FireShot is a Full page screen capture tool that also makes precise Selections even that extend beyond the screen — unlike the standard tool. Fast, simple, private, offline, reliable for research, …”[^b9-15]
- Core features free, or a fair one-time price (fixes: features moved behind a paywall or subscription)[^b9-3]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b9-11]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/fireshot/>[^b9-15]
- Replacement searches to target (Google autocomplete):
  - `gofullpage full page screen capture alternative`[^b9-16]
  - `how to use go full page screen capture`[^b9-16]
  - `full page screen capture shortcut key`[^b9-16]
  - `how to take a full page screen capture on windows`[^b9-16]
  - `chrome capture full page screenshot not working`[^b9-17]
  - `capture full page screenshot edge not working`[^b9-17]
  - `how to use go full page screen capture`[^b9-17]
  - `how to take a full page screen capture on windows`[^b9-17]
- Public threads asking for an alternative: none found.

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Totally worth the price, there is no other PDF screenshot tool of this quality. I paid for the lifetime license in 2022 and use it every single day! Highly recommend!” (5[^b9-18]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2780439/)[^b9-18], 2026-11-03[^b9-18]
  - “Used to be good, now useless without paid subscription. Away with it!” (1[^b9-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/)[^b9-12], 2026-09-23[^b9-12]
  - “Always auto updating for nothing except to force you to try the pro version (with a badge in the icon), even if the update parameter is off. Need the paid version for text …” (1[^b9-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/)[^b9-9], 2026-09-16[^b9-9]
  - “It requires a paid subscription to get proper links in a PDF snapshot. It also gets updated way too frequently, without any new features, but just ask from the user to pay for a …” (1[^b9-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/)[^b9-10], 2026-07-07[^b9-10]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: Custom License[^b9-19].
- Forking: unknown; the license is not a recognised open-source license, so assume forking is not permitted without permission.
- Use a new name and new branding. Do not use “Full Page Screen Capture — FireShot”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- A user says the platform already does this natively: “A pity to not offer for free or at a reasonable price this basic tool. To get a screenshot of the full web page, including the section that needs to be …” (2[^b9-8]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/)[^b9-8], 2026-10-03[^b9-8]. Check before building.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b9-1] |
| Abandonment | well evidenced (listing metrics) | [^b9-2] |
| Displacement event | none found |  |
| Top complaints | thin | [^b9-20] |
| Replacement demand in search | well evidenced | [^b9-16] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Full Page Screen Capture — FireShot, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “FireShot is a Full page screen capture tool that also makes precise Selections even that extend beyond the screen — unlike the standard tool. Fast, simple, private, offline, reliable for research, …”[^b9-15]

Build the smallest product that fixes what its users complain about, and nothing else:
- Core features free, or a fair one-time price (users of the incumbent complain: features moved behind a paywall or subscription)
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- A one-click import of the incumbent's settings and data

Distribution: publish it on Firefox Add-ons (addons.mozilla.org), in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 15.8[^b9-21] | cfg:20 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 7.9[^b9-22] | cfg:20 | months since last update; last-year rating below lifetime rating |
| pain specificity | 9.3[^b9-5] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 8[^b9-23] | cfg:10 | a replacement can be listed in the same marketplace; replacement searches to target |
| potential profit | 6.7[^b9-24] | cfg:15 | revenue ceiling: audience on a log scale; users mention paying, refunds or subscriptions |
| ease of development | 9.8[^b9-25] | cfg:15 | platform: a firefox replacement is a small, well-documented build; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | unscored | cfg:8 | slow-burn abandonment, no dated event; complaints are still arriving |

#### Evidence

[^b9-1]: #14756 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b9-2]: #14759 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b9-3]: derived from 3 evidence records: #15574, #15578, #15589
[^b9-4]: derived from 17 evidence records: #14756, #14757, #14758, #14759, #14760, #15572, #15574, #15575, #15577, #15578, #15580, #15589, #15590, #15599, #16017, #20450, #20452
[^b9-5]: derived from 7 evidence records: #15574, #15575, #15577, #15578, #15580, #15589, #15590
[^b9-6]: #14757 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b9-7]: #15599 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=fireshot&sort=created&page_size=50>, retrieved 2026-11-16
[^b9-8]: #15574 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/>, retrieved 2026-11-16
[^b9-9]: #15578 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/>, retrieved 2026-11-16
[^b9-10]: #15589 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/>, retrieved 2026-11-16
[^b9-11]: derived from 2 evidence records: #15575, #15590
[^b9-12]: #15575 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/>, retrieved 2026-11-16
[^b9-13]: #15590 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2720187/>, retrieved 2026-11-16
[^b9-14]: derived from 2 evidence records: #15577, #15580
[^b9-15]: #16017 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/>, retrieved 2026-11-16
[^b9-16]: #20450 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+alternative>, retrieved 2026-11-16
[^b9-17]: #20451 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+not+working>, retrieved 2026-11-16
[^b9-18]: #15572 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2780439/>, retrieved 2026-11-16
[^b9-19]: #14760 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b9-20]: derived from 5 evidence records: #15574, #15575, #15578, #15589, #15590
[^b9-21]: derived from 3 evidence records: #14756, #14758, #20450
[^b9-22]: derived from 3 evidence records: #14757, #14759, #15599
[^b9-23]: derived from 2 evidence records: #16017, #20450
[^b9-24]: derived from 6 evidence records: #14756, #15572, #15575, #15578, #15589, #20452
[^b9-25]: derived from 7 evidence records: #14760, #15574, #15575, #15578, #15589, #15590, #16017

##### Evidence index

- #14756 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14757 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14758 addons.mozilla.org rating_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14759 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #14760 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
- #15572 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2780439/>, retrieved 2026-11-16
- #15574 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/>, retrieved 2026-11-16
- #15575 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/>, retrieved 2026-11-16
- #15577 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2748876/>, retrieved 2026-11-16
- #15578 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/>, retrieved 2026-11-16
- #15580 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2746417/>, retrieved 2026-11-16
- #15589 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/>, retrieved 2026-11-16
- #15590 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2720187/>, retrieved 2026-11-16
- #15599 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=fireshot&sort=created&page_size=50>, retrieved 2026-11-16
- #16017 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/>, retrieved 2026-11-16
- #20450 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+alternative>, retrieved 2026-11-16
- #20451 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+not+working>, retrieved 2026-11-16
- #20452 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+pricing>, retrieved 2026-11-16

</details>

<details><summary><b>10. One Click Demo Import</b>, score 61.1</summary>

### One Click Demo Import

<!-- meta: generated 2026-11-16T23:49:57+00:00; entity id 74; Orphan Radar brief -->

Score **61.1[^b10-4]** of cfg:100 · signals: displacement

#### 1. Summary

One Click Demo Import on WordPress.org plugin directory has 1,000,000[^b10-1] users, was last updated 2026-04-22[^b10-2], and shows displacement; its users' most common fixable complaint is “cannot import, export or migrate data”[^b10-3].

#### 2. What happened

- **Abandonment** (weak):
  - months since last update: last updated 2026-04-22[^b10-2]; 7[^b10-2] months ago
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.9.11[^b10-5]; current WordPress is 7.1.4[^b10-6]; 2[^b10-7] major releases behind
- **Displacement event** (present):
  - platform break mentioned: platform break[^b10-8]; in 2[^b10-8] records; latest dated mention 2024-08-31[^b10-9]
  - sunset mentioned: sunset[^b10-10]; in 2[^b10-10] records; latest dated mention 2026-06-30[^b10-11]
- **Pain density** (weak):
  - recent complaints (low-star reviews, negative threads, issues): 3[^b10-12] complaints in the last twelve months

Dated sources for the events:
- “Error 500 – import failed. [30-Jun-2026 08:40:32 UTC] PHP Deprecated: Using null as an array offset is deprecated, use an empty string instead in …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-500-import-failed/)[^b10-11], 2026-06-30[^b10-11]
- “Deprecated: preg_replace(): Passing null to parameter #3 ($subject) of type arra. I am getting the error below on my server PHP version 8.3+ when on the demo …” — [WordPress.org support thread](https://wordpress.org/support/topic/deprecated-preg_replace-passing-null-to-parameter-3-subject-of-type-arra/)[^b10-13], 2024-10-09[^b10-13]
- “PHP Fatal error: Uncaught TypeError: array_key_exists(). I want to import the demo data for the "Blazin Demo Import". I am using WordPress 6.6.1 | PHP 8.2.18 | …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-fatal-error-uncaught-typeerror-array_key_exists/)[^b10-9], 2024-08-31[^b10-9]
- “Crashes site everytime. 1 star It’s not compatible with the new WP, and is not being maintained. Make sure you have a backup, as it will lock you out of your …” (1[^b10-14]★) — [WordPress.org review](https://wordpress.org/support/topic/crashes-site-everytime/)[^b10-14], 2021-03-10[^b10-14]

#### 3. Stranded users

- 1,000,000[^b10-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/one-click-demo-import/>), read from WordPress.org on 2026-11-16[^b10-1]

#### 4. Top complaints

**Cannot import, export or migrate data** (2[^b10-3] complaints)
> “Import Failed. {"status":"newAJAX","message":"Time for new AJAX request!: 25.597708940506″}” — [WordPress.org support thread](https://wordpress.org/support/topic/import-failed-15/)[^b10-15], 2026-03-11[^b10-15]
>
> “Cost Calculator Plugin Activation and XML Import Issue. Hello Support Team, We are facing an issue during the demo import setup process. The Cost Calculator Builder plugin is not activating properly during the plugin …” — [WordPress.org support thread](https://wordpress.org/support/topic/cost-calculator-plugin-activation-and-xml-import-issue/)[^b10-16], 2026-05-18[^b10-16]

**Crashes, errors and broken pages** (1[^b10-11] complaints)
> “Error 500 – import failed. [30-Jun-2026 08:40:32 UTC] PHP Deprecated: Using null as an array offset is deprecated, use an empty string instead in …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-500-import-failed/)[^b10-11], 2026-06-30[^b10-11]


#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Import your demo content, widgets and theme settings with one click. Theme authors! Enable simple theme demo import for your users.”[^b10-17]
- Open formats with one-click import and export (fixes: cannot import, export or migrate data)[^b10-3]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b10-11]
- Works on the current WordPress release[^b10-7]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Formats named in the evidence: JSON[^b10-18], XML[^b10-19], ZIP[^b10-20].

What users say about import, export or migration:
- “Active installations as shown on https://wordpress.org/plugins/one-click-demo-import/” — [WordPress.org listing](https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1)[^b10-1]
- “How can I include pages, etc., built with Divi Builder?. How can I include pages, etc., built with Divi Builder (similar but different from Elementor)? When I create a package of …” — [WordPress.org support thread](https://wordpress.org/support/topic/how-can-i-include-pages-etc-built-with-divi-builder/)[^b10-21], 2026-07-28[^b10-21]
- “Error 500 – import failed. [30-Jun-2026 08:40:32 UTC] PHP Deprecated: Using null as an array offset is deprecated, use an empty string instead in …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-500-import-failed/)[^b10-11], 2026-06-30[^b10-11]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/one-click-demo-import/>[^b10-17]
- Replacement searches to target (Google autocomplete):
  - `one click demo import not working`[^b10-22]
- Public threads where people asked for an alternative (links only):
  - [Ongoing Demo Import Failure / One Click Demo Import](https://wordpress.org/support/topic/ongoing-demo-import-failure-one-click-demo-import/)[^b10-23]
  - [Remove recommended plugins](https://wordpress.org/support/topic/remove-recommended-plugins/)[^b10-24]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “The new update is mind-blowing :). 5 stars Hey guys, just wanted to say thank you for the amazing plugin and recent update. I couldn’t believe the features that you’ve added at …” (5[^b10-25]★) — [WordPress.org review](https://wordpress.org/support/topic/the-new-update-is-mind-blowing/)[^b10-25], 2021-04-01[^b10-25]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b10-26].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “One Click Demo Import”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Fewer than two of the three signals are present; the opportunity rests on one kind of evidence.
- Few recent complaints, so the problem list may be incomplete or unrepresentative.
- Nobody's autocomplete suggests searching for an alternative yet.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b10-1] |
| Abandonment | thin | [^b10-27] |
| Displacement event | well evidenced | [^b10-28] |
| Top complaints | thin | [^b10-12] |
| Replacement demand in search | checked, none found | [^b10-29] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

A short prompt follows. For the full system-build specification (requirements with acceptance criteria, architecture, import path, milestones and unknowns), run `orphan-radar buildprompt <id>` with this opportunity's id, or use the dashboard button.

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): One Click Demo Import, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Import your demo content, widgets and theme settings with one click. Theme authors! Enable simple theme demo import for your users.”[^b10-17]

Build the smallest product that fixes what its users complain about, and nothing else:
- Open formats with one-click import and export (users of the incumbent complain: cannot import, export or migrate data)
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- Works on the current WordPress release
- A one-click import of the incumbent's settings and data

Distribution: publish it on WordPress.org plugin directory, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
```

#### Score breakdown

| Component | Points | Max (cfg) | What counted |
|---|---|---|---|
| demand | 12.4[^b10-30] | cfg:20 | audience on a log scale; rating count; people search for '‹product› not working' / '‹product› pricing' |
| supply failure | 7.8[^b10-31] | cfg:20 | months since last update; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 6.6[^b10-12] | cfg:12 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 7.3[^b10-32] | cfg:10 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| potential profit | 7[^b10-33] | cfg:15 | revenue ceiling: audience on a log scale; users mention paying, refunds or subscriptions |
| ease of development | 14.4[^b10-34] | cfg:15 | platform: a wordpress replacement is a small, well-documented build; incumbent is open source: its code and data formats can be studied; fixes are routine engineering (share of complaint clusters); narrow scope: few distinct problems to fix |
| timing | 5.6[^b10-11] | cfg:8 | recency of the latest displacement event |

#### Evidence

[^b10-1]: #750 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-2]: #753 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-3]: derived from 2 evidence records: #12594, #12595
[^b10-4]: derived from 17 evidence records: #750, #752, #753, #754, #757, #761, #12593, #12594, #12595, #12596, #12607, #12617, #12633, #13510, #20447, #20448, #20449
[^b10-5]: #754 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-6]: #761 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b10-7]: derived from 2 evidence records: #754, #761
[^b10-8]: derived from 2 evidence records: #12620, #12636
[^b10-9]: #12620 WordPress.org support thread, <https://wordpress.org/support/topic/php-fatal-error-uncaught-typeerror-array_key_exists/>, retrieved 2026-11-16
[^b10-10]: derived from 2 evidence records: #12593, #12617
[^b10-11]: #12593 WordPress.org support thread, <https://wordpress.org/support/topic/error-500-import-failed/>, retrieved 2026-11-16
[^b10-12]: derived from 3 evidence records: #12593, #12594, #12595
[^b10-13]: #12617 WordPress.org support thread, <https://wordpress.org/support/topic/deprecated-preg_replace-passing-null-to-parameter-3-subject-of-type-arra/>, retrieved 2026-11-16
[^b10-14]: #12636 WordPress.org review, <https://wordpress.org/support/topic/crashes-site-everytime/>, retrieved 2026-11-16
[^b10-15]: #12595 WordPress.org support thread, <https://wordpress.org/support/topic/import-failed-15/>, retrieved 2026-11-16
[^b10-16]: #12594 WordPress.org support thread, <https://wordpress.org/support/topic/cost-calculator-plugin-activation-and-xml-import-issue/>, retrieved 2026-11-16
[^b10-17]: #13510 WordPress.org description, <https://wordpress.org/plugins/one-click-demo-import/>, retrieved 2026-11-16
[^b10-18]: derived from 5 evidence records: #12592, #12594, #12603, #12609, #12630
[^b10-19]: derived from 3 evidence records: #12594, #12599, #12613
[^b10-20]: #12616 WordPress.org support thread, <https://wordpress.org/support/topic/updated-failed-3/>, retrieved 2026-11-16
[^b10-21]: #12592 WordPress.org support thread, <https://wordpress.org/support/topic/how-can-i-include-pages-etc-built-with-divi-builder/>, retrieved 2026-11-16
[^b10-22]: #20448 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=one+click+demo+import+not+working>, retrieved 2026-11-16
[^b10-23]: #12596 WordPress.org support thread, <https://wordpress.org/support/topic/ongoing-demo-import-failure-one-click-demo-import/>, retrieved 2026-11-16
[^b10-24]: #12607 WordPress.org support thread, <https://wordpress.org/support/topic/remove-recommended-plugins/>, retrieved 2026-11-16
[^b10-25]: #12633 WordPress.org review, <https://wordpress.org/support/topic/the-new-update-is-mind-blowing/>, retrieved 2026-11-16
[^b10-26]: #757 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b10-27]: derived from 3 evidence records: #753, #754, #761
[^b10-28]: derived from 4 evidence records: #12593, #12617, #12620, #12636
[^b10-29]: #20447 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=one+click+demo+import+alternative>, retrieved 2026-11-16
[^b10-30]: derived from 3 evidence records: #750, #752, #20448
[^b10-31]: derived from 5 evidence records: #753, #754, #761, #12593, #12617
[^b10-32]: derived from 4 evidence records: #12596, #12607, #13510, #20447
[^b10-33]: derived from 3 evidence records: #750, #12633, #20449
[^b10-34]: derived from 5 evidence records: #757, #12593, #12594, #12595, #13510

##### Evidence index

- #750 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #752 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #753 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #754 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #757 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #761 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #12592 WordPress.org support thread, <https://wordpress.org/support/topic/how-can-i-include-pages-etc-built-with-divi-builder/>, retrieved 2026-11-16
- #12593 WordPress.org support thread, <https://wordpress.org/support/topic/error-500-import-failed/>, retrieved 2026-11-16
- #12594 WordPress.org support thread, <https://wordpress.org/support/topic/cost-calculator-plugin-activation-and-xml-import-issue/>, retrieved 2026-11-16
- #12595 WordPress.org support thread, <https://wordpress.org/support/topic/import-failed-15/>, retrieved 2026-11-16
- #12596 WordPress.org support thread, <https://wordpress.org/support/topic/ongoing-demo-import-failure-one-click-demo-import/>, retrieved 2026-11-16
- #12599 WordPress.org support thread, <https://wordpress.org/support/topic/installation-failed-could-not-copy-file-one-click-demo-import-assets-demo-cont/>, retrieved 2026-11-16
- #12603 WordPress.org support thread, <https://wordpress.org/support/topic/mega-main-menu-integration/>, retrieved 2026-11-16
- #12607 WordPress.org support thread, <https://wordpress.org/support/topic/remove-recommended-plugins/>, retrieved 2026-11-16
- #12609 WordPress.org support thread, <https://wordpress.org/support/topic/acf-integration-9/>, retrieved 2026-11-16
- #12613 WordPress.org support thread, <https://wordpress.org/support/topic/leverage-theme-demo-not-importing/>, retrieved 2026-11-16
- #12616 WordPress.org support thread, <https://wordpress.org/support/topic/updated-failed-3/>, retrieved 2026-11-16
- #12617 WordPress.org support thread, <https://wordpress.org/support/topic/deprecated-preg_replace-passing-null-to-parameter-3-subject-of-type-arra/>, retrieved 2026-11-16
- #12620 WordPress.org support thread, <https://wordpress.org/support/topic/php-fatal-error-uncaught-typeerror-array_key_exists/>, retrieved 2026-11-16
- #12630 WordPress.org review, <https://wordpress.org/support/topic/works-perfectly-2517/>, retrieved 2026-11-16
- #12633 WordPress.org review, <https://wordpress.org/support/topic/the-new-update-is-mind-blowing/>, retrieved 2026-11-16
- #12636 WordPress.org review, <https://wordpress.org/support/topic/crashes-site-everytime/>, retrieved 2026-11-16
- #13510 WordPress.org description, <https://wordpress.org/plugins/one-click-demo-import/>, retrieved 2026-11-16
- #20447 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=one+click+demo+import+alternative>, retrieved 2026-11-16
- #20448 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=one+click+demo+import+not+working>, retrieved 2026-11-16
- #20449 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=one+click+demo+import+pricing>, retrieved 2026-11-16

</details>

<!-- TOP10:END -->
