# Orphan Radar

Orphan Radar finds software whose users are stranded. The products it surfaces have proven demand, but they have been abandoned, displaced (shut down, sold, repriced) or are failing their users in specific, fixable ways. Those users are already looking for a replacement.

It does not brainstorm. Every opportunity is a real product with a measured audience, and every figure in a brief cites a stored evidence record with a URL and a retrieval date. An automated audit refuses to save a brief that breaks this rule.

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Scoring](#scoring)
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
| Proven demand | 25 | audience on a log scale from 10³ to 10⁷ (12/25; stars and downloads count only as a discounted proxy) · rating count (6/25) · Google suggests "‹product› alternative" (7/25), or partial credit for "not working" / "pricing" |
| Supply failure | 25 | months since the last update (8/25) · unresolved share of support threads (5/25) · last-year rating vs lifetime rating (4/25) · broken compatibility or archived (4/25) · displacement event (4/25) |
| Pain specificity | 15 | complaints fall into at most 5 fixable clusters, by share covered (9/15) · complaint volume (6/15) |
| Channel | 15 | a replacement can be listed in the same marketplace (8/15) · replacement searches exist (4/15) · public threads asking for an alternative (3/15) |
| Willingness to pay | 10 | the incumbent charges (5/10) · users mention paying (3/10) · people search for its pricing (2/10) |
| Timing | 10 | recency of the latest dated displacement event (7/10) · complaints still arriving (3/10) · **minus 3** when at least 3 records say users already switched to another tool |

**Hard filters** exclude a product from the ranking and list it on the **Excluded** page with the reason:
- it handles health, financial-account or children's data (keyword lists in `config.toml`);
- it needs a license, partnership, hardware or regulatory approval (including coupon and cashback tools, which need affiliate partnerships);
- its name says it depends on another company's trademark or proprietary service (for example "for YouTube", "Meta pixel", "video downloader");
- the maintainers name a maintained successor ("deprecated, use X instead");
- the listing or a discussion says the platform now does it natively, or two or more users say so (a single user's claim becomes a risk note in the brief);
- its audience is below `min_users` (default 1,000). Products with no user count use stars or downloads as a proxy, and products with no figure at all are excluded.

You can also exclude a product by hand with `orphan-radar exclude <id> --reason "..."`.

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
orphan-radar verify             # re-audit every stored brief
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
  - buttons to mark it watching, building or dismissed, and to (re)generate its brief.
- **Brief:** the rendered brief with clickable footnotes.
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
- `test_web.py`: pages render, HTML is escaped, actions work, cross-origin POSTs are refused.

## Design decisions and changes from the brief

- **Standard library only.** The target machine had no `pip`, and a research tool that installs with one command and nothing to download is easier to trust and keep running. The Claude SDK is the only optional dependency.
- **Clustering and briefs work without a key.** The spec said to skip clustering and briefs without a language-model key. Instead, rule-based clustering always runs, and briefs are assembled from evidence by templates; a model only improves cluster grouping and labels. This keeps "ten well-evidenced opportunities" available on day one and makes the grounding rule easier to enforce.
- **Briefs are audited, not trusted.** A brief that cannot cite a figure is never saved.
- **Audience proxies are labelled and discounted.** GitHub stars and Open VSX downloads are not users. They count for 60% in the demand score and are labelled "proxy" everywhere.
- **Leads page.** Hacker News announcements about products the tool does not track are kept as leads, not invented as opportunities: they have no verifiable user count.
- **Extra sources** where access is legitimate: Atlassian Marketplace (paid apps make willingness to pay visible) and Open VSX (standing in for the VS Code Marketplace).
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

The database holds 1,650 product listings, merged into 1,620 products, and 20,542 evidence records. 175 products were excluded by hard filters; the full list is in `report/opportunities.md` and on the dashboard's Excluded page.

Every brief below passed the traceability audit (`orphan-radar verify`). Footnote numbers are prefixed per brief so they stay unique on this page. The same briefs are in `report/briefs/`.

| # | Product | Score | Signals | Sources | Top complaint cluster |
|---|---|---|---|---|---|
| 1 | [I don't care about cookies](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/) | 70.0 | abandonment, displacement, pain | firefox | Stopped doing its core job on many sites or setups (9) |
| 2 | [ClearURLs](https://addons.mozilla.org/en-US/firefox/addon/clearurls/) | 65.2 | abandonment, displacement, pain | firefox | Crashes, errors and broken pages (2) |
| 3 | [Full Page Screen Capture — FireShot](https://addons.mozilla.org/en-US/firefox/addon/fireshot/) | 61.3 | abandonment, pain | firefox | Features moved behind a paywall or subscription (3) |
| 4 | [AMP](https://wordpress.org/plugins/amp/) | 60.6 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (4) |
| 5 | [WooSidebars](https://wordpress.org/plugins/woosidebars/) | 60.6 | abandonment, displacement | wordpress | Broken by a platform, browser or PHP update (2) |
| 6 | [Cookie AutoDelete](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/) | 59.4 | abandonment, displacement, pain | firefox | Stopped doing its core job on many sites or setups (3) |
| 7 | [Health Check & Troubleshooting](https://wordpress.org/plugins/health-check/) | 59.1 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (2) |
| 8 | [WebP Express](https://wordpress.org/plugins/webp-express/) | 59.0 | abandonment, displacement, pain | wordpress | Crashes, errors and broken pages (7) |
| 9 | [Image Optimizer – Compress Images and Convert to WebP or AVIF](https://wordpress.org/plugins/image-optimization/) | 57.5 | pain | wordpress | Features moved behind a paywall or subscription (5) |
| 10 | [Duplicate Page](https://wordpress.org/plugins/duplicate-page/) | 57.1 | displacement, pain | wordpress | Stopped doing its core job on many sites or setups (4) |

<details><summary><b>1. I don't care about cookies</b>, score 70.0</summary>

### I don't care about cookies

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 249; Orphan Radar brief -->

Score **70[^b1-4]** of cfg:100 · signals: abandonment, displacement, pain

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
> “It doesn't work anymore, I keep having Cookies I need to take care of...” (1[^b1-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2548069/)[^b1-10], 2026-01-02[^b1-10]
>
> “Has stopped working on many websites” (1[^b1-11]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2599425/)[^b1-11], 2026-02-28[^b1-11]
>
> “Une application QOL de qualité qui malheureusement aujourd’hui manque de suivie et n'est plus aussi efficace que jadis. Tourné vous vers "I still don't care about cookies"” (2[^b1-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2609697/)[^b1-12], 2026-03-22[^b1-12]

**Ads, tracking, or distrust of a new owner** (3[^b1-13] complaints)
> “He sold his soul and our data.” (1[^b1-14]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2739996/)[^b1-14], 2026-08-26[^b1-14]
>
> “Kill this piece of shit with fire, get "I still don't care about cookies" which is an actual non-invasive FOSS fork of this program now owned by disgusting corporations 🔥🔥” (1[^b1-15]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2785644/)[^b1-15], 2026-11-16[^b1-15]
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
| demand | 20.1[^b1-23] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 11.7[^b1-24] | cfg:25 | months since last update; last-year rating below lifetime rating; displacement event: acquisition mentioned |
| pain specificity | 13.2[^b1-7] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 15[^b1-25] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| willingness to pay | none | cfg:10 | nothing |
| timing | 10[^b1-6] | cfg:10 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b1-1]: #14679 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-2]: #14682 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-3]: derived from 9 evidence records: #15369, #15370, #15371, #15374, #15377, #15378, #15380, #15381, #15384
[^b1-4]: derived from 22 evidence records: #14679, #14680, #14681, #14682, #15368, #15369, #15370, #15371, #15372, #15373, #15374, #15377, #15378, #15380, #15381, #15382, #15383, #15384, #15385, #15397, #20423, #20425
[^b1-5]: #15385 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2546572/>, retrieved 2026-11-16
[^b1-6]: #15374 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2728251/>, retrieved 2026-11-16
[^b1-7]: derived from 15 evidence records: #15368, #15369, #15370, #15371, #15372, #15373, #15374, #15377, #15378, #15380, #15381, #15382, #15383, #15384, #15385
[^b1-8]: #14680 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-9]: #15397 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=i-dont-care-about-cookies&sort=created&page_size=50>, retrieved 2026-11-16
[^b1-10]: #15384 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2548069/>, retrieved 2026-11-16
[^b1-11]: #15381 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2599425/>, retrieved 2026-11-16
[^b1-12]: #15380 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2609697/>, retrieved 2026-11-16
[^b1-13]: derived from 3 evidence records: #15368, #15373, #15385
[^b1-14]: #15373 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2739996/>, retrieved 2026-11-16
[^b1-15]: #15368 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/reviews/2785644/>, retrieved 2026-11-16
[^b1-16]: derived from 3 evidence records: #15372, #15382, #15383
[^b1-17]: #16002 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/i-dont-care-about-cookies/>, retrieved 2026-11-16
[^b1-18]: #20423 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+alternative>, retrieved 2026-11-16
[^b1-19]: #20424 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=i+don%27t+care+about+cookies+not+working>, retrieved 2026-11-16
[^b1-20]: #14683 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b1-21]: derived from 2 evidence records: #15374, #15385
[^b1-22]: derived from 12 evidence records: #15368, #15369, #15370, #15371, #15373, #15374, #15377, #15378, #15380, #15381, #15384, #15385
[^b1-23]: derived from 3 evidence records: #14679, #14681, #20423
[^b1-24]: derived from 4 evidence records: #14680, #14682, #15385, #15397
[^b1-25]: derived from 3 evidence records: #14679, #15374, #20423

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

<details><summary><b>2. ClearURLs</b>, score 65.2</summary>

### ClearURLs

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 132; Orphan Radar brief -->

Score **65.2[^b2-4]** of cfg:100 · signals: abandonment, displacement, pain

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
> “made logging in via google impossible with error 400 somehow. dont use this” (1[^b2-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736654/)[^b2-9], 2026-08-14[^b2-9]
>
> “Breaks Google search AI mode (gives error message "Can't generate an AI overview right now. Try again later.")” (1[^b2-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2738839/)[^b2-10], 2026-08-22[^b2-10]

**Stopped doing its core job on many sites or setups** (2[^b2-11] complaints)
> “it's useless” (1[^b2-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736934/)[^b2-12], 2026-08-14[^b2-12]
>
> “Stopped working for about two months.” (1[^b2-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2750655/)[^b2-13], 2026-09-23[^b2-13]

**Breaks or fails at sign-in, sync or accounts** (2[^b2-14] complaints)
> “Broke my Google account. Getting error 400 everywhere whenever try to login via Google.” (1[^b2-15]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2765534/)[^b2-15], 2026-10-10[^b2-15]
>
> “DO NOT DOWNLOAD this extension if you use Google to log in to anything. This breaks every and any Google login. I spent so long trying to figure out the problem when it was this extension the whole time. Fix this crap …” (1[^b2-16]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2785514/)[^b2-16], 2026-11-16[^b2-16]

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
| demand | 20.7[^b2-22] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 11.1[^b2-23] | cfg:25 | months since last update; last-year rating below lifetime rating; displacement event: sunset mentioned |
| pain specificity | 11.4[^b2-6] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 12[^b2-24] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target |
| willingness to pay | none | cfg:10 | nothing |
| timing | 10[^b2-5] | cfg:10 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b2-1]: #14554 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-2]: #14557 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-3]: derived from 2 evidence records: #15877, #15880
[^b2-4]: derived from 18 evidence records: #14554, #14555, #14556, #14557, #15858, #15863, #15865, #15866, #15867, #15869, #15877, #15878, #15879, #15880, #15882, #15886, #20429, #20431
[^b2-5]: #15878 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2737389/>, retrieved 2026-11-16
[^b2-6]: derived from 10 evidence records: #15858, #15863, #15865, #15866, #15867, #15869, #15877, #15879, #15880, #15882
[^b2-7]: #14555 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-8]: #15886 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=clearurls&sort=created&page_size=50>, retrieved 2026-11-16
[^b2-9]: #15880 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736654/>, retrieved 2026-11-16
[^b2-10]: #15877 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2738839/>, retrieved 2026-11-16
[^b2-11]: derived from 2 evidence records: #15869, #15879
[^b2-12]: #15879 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2736934/>, retrieved 2026-11-16
[^b2-13]: #15869 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2750655/>, retrieved 2026-11-16
[^b2-14]: derived from 2 evidence records: #15858, #15866
[^b2-15]: #15866 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2765534/>, retrieved 2026-11-16
[^b2-16]: #15858 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/reviews/2785514/>, retrieved 2026-11-16
[^b2-17]: derived from 4 evidence records: #15863, #15865, #15867, #15882
[^b2-18]: #15978 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/clearurls/>, retrieved 2026-11-16
[^b2-19]: #20429 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=clearurls+alternative>, retrieved 2026-11-16
[^b2-20]: #14558 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=1&lang=en-US>, retrieved 2026-11-16
[^b2-21]: derived from 6 evidence records: #15858, #15866, #15869, #15877, #15879, #15880
[^b2-22]: derived from 3 evidence records: #14554, #14556, #20429
[^b2-23]: derived from 4 evidence records: #14555, #14557, #15878, #15886
[^b2-24]: derived from 2 evidence records: #14554, #20429

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

<details><summary><b>3. Full Page Screen Capture — FireShot</b>, score 61.3</summary>

### Full Page Screen Capture — FireShot

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 342; Orphan Radar brief -->

Score **61.3[^b3-4]** of cfg:100 · signals: abandonment, pain

#### 1. Summary

Full Page Screen Capture — FireShot on Firefox Add-ons (addons.mozilla.org) has 175,676[^b3-1] users, was last updated 2023-06-21[^b3-2], and shows abandonment, pain; its users' most common fixable complaint is “features moved behind a paywall or subscription”[^b3-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2023-06-21[^b3-2]; 41[^b3-2] months ago
- **Displacement event**: none found.
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 7[^b3-5] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.63[^b3-6] stars; recent rating 3.92[^b3-7] stars

#### 3. Stranded users

- 175,676[^b3-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/fireshot/>), read from addons.mozilla.org on 2026-11-16[^b3-1]

#### 4. Top complaints

**Features moved behind a paywall or subscription** (3[^b3-3] complaints)
> “It requires a paid subscription to get proper links in a PDF snapshot. It also gets updated way too frequently, without any new features, but just ask from the user to pay for a subscription. It is not worth it.” (1[^b3-8]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/)[^b3-8], 2026-07-07[^b3-8]
>
> “Always auto updating for nothing except to force you to try the pro version (with a badge in the icon), even if the update parameter is off. Need the paid version for text selection in the saved pdf. Was good, now …” (1[^b3-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/)[^b3-9], 2026-09-16[^b3-9]
>
> “A pity to not offer for free or at a reasonable price this basic tool. To get a screenshot of the full web page, including the section that needs to be scrolled down, it can be done natively in firefox: …” (2[^b3-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/)[^b3-10], 2026-10-03[^b3-10]

**Stopped doing its core job on many sites or setups** (2[^b3-11] complaints)
> “stopped working. i now use "awesome screenshot"” (2[^b3-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2720187/)[^b3-12], 2026-06-13[^b3-12]
>
> “Used to be good, now useless without paid subscription. Away with it!” (1[^b3-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/)[^b3-13], 2026-09-23[^b3-13]

Plus 2[^b3-14] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “FireShot is a Full page screen capture tool that also makes precise Selections even that extend beyond the screen — unlike the standard tool. Fast, simple, private, offline, reliable for research, …”[^b3-15]
- Core features free, or a fair one-time price (fixes: features moved behind a paywall or subscription)[^b3-3]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b3-11]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/fireshot/>[^b3-15]
- Replacement searches to target (Google autocomplete):
  - `gofullpage full page screen capture alternative`[^b3-16]
  - `how to use go full page screen capture`[^b3-16]
  - `full page screen capture shortcut key`[^b3-16]
  - `how to take a full page screen capture on windows`[^b3-16]
  - `chrome capture full page screenshot not working`[^b3-17]
  - `capture full page screenshot edge not working`[^b3-17]
  - `how to use go full page screen capture`[^b3-17]
  - `how to take a full page screen capture on windows`[^b3-17]
- Public threads asking for an alternative: none found.

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Totally worth the price, there is no other PDF screenshot tool of this quality. I paid for the lifetime license in 2022 and use it every single day! Highly recommend!” (5[^b3-18]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2780439/)[^b3-18], 2026-11-03[^b3-18]
  - “Used to be good, now useless without paid subscription. Away with it!” (1[^b3-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/)[^b3-13], 2026-09-23[^b3-13]
  - “Always auto updating for nothing except to force you to try the pro version (with a badge in the icon), even if the update parameter is off. Need the paid version for text …” (1[^b3-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/)[^b3-9], 2026-09-16[^b3-9]
  - “It requires a paid subscription to get proper links in a PDF snapshot. It also gets updated way too frequently, without any new features, but just ask from the user to pay for a …” (1[^b3-8]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/)[^b3-8], 2026-07-07[^b3-8]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: Custom License[^b3-19].
- Forking: unknown; the license is not a recognised open-source license, so assume forking is not permitted without permission.
- Use a new name and new branding. Do not use “Full Page Screen Capture — FireShot”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- A user says the platform already does this natively: “A pity to not offer for free or at a reasonable price this basic tool. To get a screenshot of the full web page, including the section that needs to be …” (2[^b3-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/)[^b3-10], 2026-10-03[^b3-10]. Check before building.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b3-1] |
| Abandonment | well evidenced (listing metrics) | [^b3-2] |
| Displacement event | none found |  |
| Top complaints | thin | [^b3-20] |
| Replacement demand in search | well evidenced | [^b3-16] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Full Page Screen Capture — FireShot, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “FireShot is a Full page screen capture tool that also makes precise Selections even that extend beyond the screen — unlike the standard tool. Fast, simple, private, offline, reliable for research, …”[^b3-15]

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
| demand | 19.7[^b3-21] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 9.9[^b3-22] | cfg:25 | months since last update; last-year rating below lifetime rating |
| pain specificity | 11.7[^b3-5] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 12[^b3-23] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target |
| willingness to pay | 3[^b3-24] | cfg:10 | users mention paying or pricing |
| timing | unscored | cfg:10 | slow-burn abandonment, no dated event; complaints are still arriving |

#### Evidence

[^b3-1]: #14756 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b3-2]: #14759 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b3-3]: derived from 3 evidence records: #15574, #15578, #15589
[^b3-4]: derived from 15 evidence records: #14756, #14757, #14758, #14759, #15572, #15574, #15575, #15577, #15578, #15580, #15589, #15590, #15599, #20450, #20452
[^b3-5]: derived from 7 evidence records: #15574, #15575, #15577, #15578, #15580, #15589, #15590
[^b3-6]: #14757 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b3-7]: #15599 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=fireshot&sort=created&page_size=50>, retrieved 2026-11-16
[^b3-8]: #15589 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2726482/>, retrieved 2026-11-16
[^b3-9]: #15578 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2747829/>, retrieved 2026-11-16
[^b3-10]: #15574 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2755531/>, retrieved 2026-11-16
[^b3-11]: derived from 2 evidence records: #15575, #15590
[^b3-12]: #15590 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2720187/>, retrieved 2026-11-16
[^b3-13]: #15575 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2750682/>, retrieved 2026-11-16
[^b3-14]: derived from 2 evidence records: #15577, #15580
[^b3-15]: #16017 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/>, retrieved 2026-11-16
[^b3-16]: #20450 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+alternative>, retrieved 2026-11-16
[^b3-17]: #20451 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=full+page+screen+capture+not+working>, retrieved 2026-11-16
[^b3-18]: #15572 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/fireshot/reviews/2780439/>, retrieved 2026-11-16
[^b3-19]: #14760 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b3-20]: derived from 5 evidence records: #15574, #15575, #15578, #15589, #15590
[^b3-21]: derived from 3 evidence records: #14756, #14758, #20450
[^b3-22]: derived from 3 evidence records: #14757, #14759, #15599
[^b3-23]: derived from 2 evidence records: #14756, #20450
[^b3-24]: derived from 5 evidence records: #15572, #15575, #15578, #15589, #20452

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

<details><summary><b>4. AMP</b>, score 60.6</summary>

### AMP

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 217; Orphan Radar brief -->

Score **60.6[^b4-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

AMP on WordPress.org plugin directory has 300,000[^b4-1] users, was last updated 2025-04-10[^b4-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b4-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2025-04-10[^b4-2]; 19[^b4-2] months ago
  - recent support threads with zero replies: 3[^b4-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.8.12[^b4-6]; current WordPress is 7.1.4[^b4-7]; 3[^b4-8] major releases behind
- **Displacement event** (present):
  - platform break mentioned: platform break[^b4-9]; in 2[^b4-9] records; latest dated mention 2023-12-08[^b4-10]
  - sunset mentioned: sunset[^b4-11]; in 2[^b4-11] records; latest dated mention 2026-08-28[^b4-12]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 9[^b4-13] complaints in the last twelve months

Dated sources for the events:
- “PHP 8 deprecation warning in AMP PairedUrl.php. Hi, I’m seeing repeated PHP 8 deprecation warnings in the AMP plugin: preg_match(): Passing null to parameter …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/)[^b4-12], 2026-08-28[^b4-12]
- “PHP Deprecation and Warning Errors in AMP Plugin Logs. Issue Summary: I am seeing recurring PHP errors in my server logs related to the AMP plugin. over 170 MB …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/)[^b4-14], 2026-07-09[^b4-14]
- “I hate it! AMP is Malware!!!. 1 star AMP acts like malware. I have tried multiple times to deactivate it and delete it from my site and it keeps coming back. I …” (1[^b4-10]★) — [WordPress.org review](https://wordpress.org/support/topic/i-hate-it-amp-is-malware/)[^b4-10], 2023-12-08[^b4-10]
- “Not compatible with many plugins or themes. 2 stars When you active this plugin and each other plugin, it performs a check for compatibility with other plugins …” (2[^b4-15]★) — [WordPress.org review](https://wordpress.org/support/topic/not-compatible-with-many-plugins-or-themes/)[^b4-15], 2023-07-20[^b4-15]

#### 3. Stranded users

- 300,000[^b4-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/amp/>), read from WordPress.org on 2026-11-16[^b4-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (4[^b4-3] complaints)
> “Can’t Open AMP Setting. Hello, after a long time without using this plugin, now I want to use it but can’t. AMP Settings Something went wrong. Check your connection and open your browser console to see if there are any …” — [WordPress.org support thread](https://wordpress.org/support/topic/cant-open-amp-setting/)[^b4-16], 2026-03-04[^b4-16]
>
> “Error message upon submitting contact form. I have a contact form on my site, and when people submit the form, this message pops up in a green box: It appears your submission was successful. Even though the server …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-message-upon-submitting-contact-form/)[^b4-17], 2025-12-21[^b4-17]
>
> “The AMP Site Scanner has experienced an error.. Received this error when installing a new plugin, and the popup message told me to submit to this forum. 🙂 { "message": "u(…) is not a function", "stack": "TypeError: u(…) …” — [WordPress.org support thread](https://wordpress.org/support/topic/the-amp-site-scanner-has-experienced-an-error-2/)[^b4-18], 2026-01-08[^b4-18]

**Broken by a platform, browser or PHP update** (3[^b4-19] complaints)
> “AMP conflict with block editor. Hi, I couldn’t open any article because it was giving an error, once I deactivate the AMP it all worked. The error is: TypeError: Class extends value …” — [WordPress.org support thread](https://wordpress.org/support/topic/amp-conflict-with-block-editor/)[^b4-20], 2026-03-17[^b4-20]
>
> “PHP Deprecation and Warning Errors in AMP Plugin Logs. Issue Summary: I am seeing recurring PHP errors in my server logs related to the AMP plugin. over 170 MB log text[09-Jul-2026 11:11:41 UTC] PHP Deprecated: …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/)[^b4-14], 2026-07-09[^b4-14]
>
> “PHP 8 deprecation warning in AMP PairedUrl.php. Hi, I’m seeing repeated PHP 8 deprecation warnings in the AMP plugin: preg_match(): Passing null to parameter #2 ($subject) of type string is deprecated The warning …” — [WordPress.org support thread](https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/)[^b4-12], 2026-08-28[^b4-12]

**Slow, heavy or resource-hungry** (1[^b4-21] complaints)
> “AMP on Woodmart Theme. Hello, I installed AMP on my website with a Woodmart theme. It looks as if my theme is not fully compatible with AMP. Also, after having checked my Page Speed on Google, the mobile aspect scored …” — [WordPress.org support thread](https://wordpress.org/support/topic/amp-on-woodmart-theme/)[^b4-21], 2026-04-16[^b4-21]

Plus 1[^b4-22] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “An easier path to great Page Experience for everyone. Powered by AMP.”[^b4-23]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b4-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b4-19]
- Lightweight and fast: lazy work, no bloat (fixes: slow, heavy or resource-hungry)[^b4-21]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/amp/>[^b4-23]
- Replacement searches: none found for the alternative / not working / pricing queries[^b4-24].
- Public threads where people asked for an alternative (links only):
  - [Most Outstanding AMP](https://wordpress.org/support/topic/most-outstanding-amp/)[^b4-25]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b4-26].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “AMP”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Nobody's autocomplete suggests searching for an alternative yet.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b4-1] |
| Abandonment | well evidenced (listing metrics) | [^b4-27] |
| Displacement event | well evidenced | [^b4-28] |
| Top complaints | well evidenced | [^b4-29] |
| Replacement demand in search | checked, none found | [^b4-30] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): AMP, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “An easier path to great Page Experience for everyone. Powered by AMP.”[^b4-23]

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
| demand | 12.1[^b4-31] | cfg:25 | audience on a log scale; rating count |
| supply failure | 17.5[^b4-32] | cfg:25 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 13[^b4-13] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 11[^b4-33] | cfg:15 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| willingness to pay | none | cfg:10 | nothing |
| timing | 7[^b4-12] | cfg:10 | recency of the latest displacement event |

#### Evidence

[^b4-1]: #2152 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-2]: #2155 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-3]: derived from 4 evidence records: #12224, #12230, #12232, #12233
[^b4-4]: derived from 17 evidence records: #2152, #2154, #2155, #2156, #2163, #12223, #12224, #12225, #12228, #12229, #12230, #12231, #12232, #12233, #12273, #20417, #20419
[^b4-5]: derived from 3 evidence records: #12225, #12228, #12229
[^b4-6]: #2156 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b4-7]: #2163 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b4-8]: derived from 2 evidence records: #2156, #2163
[^b4-9]: derived from 2 evidence records: #12261, #12269
[^b4-10]: #12261 WordPress.org review, <https://wordpress.org/support/topic/i-hate-it-amp-is-malware/>, retrieved 2026-11-16
[^b4-11]: derived from 2 evidence records: #12223, #12225
[^b4-12]: #12223 WordPress.org support thread, <https://wordpress.org/support/topic/php-8-deprecation-warning-in-amp-pairedurl-php/>, retrieved 2026-11-16
[^b4-13]: derived from 9 evidence records: #12223, #12224, #12225, #12228, #12229, #12230, #12231, #12232, #12233
[^b4-14]: #12225 WordPress.org support thread, <https://wordpress.org/support/topic/php-deprecation-and-warning-errors-in-amp-plugin-logs/>, retrieved 2026-11-16
[^b4-15]: #12269 WordPress.org review, <https://wordpress.org/support/topic/not-compatible-with-many-plugins-or-themes/>, retrieved 2026-11-16
[^b4-16]: #12230 WordPress.org support thread, <https://wordpress.org/support/topic/cant-open-amp-setting/>, retrieved 2026-11-16
[^b4-17]: #12233 WordPress.org support thread, <https://wordpress.org/support/topic/error-message-upon-submitting-contact-form/>, retrieved 2026-11-16
[^b4-18]: #12232 WordPress.org support thread, <https://wordpress.org/support/topic/the-amp-site-scanner-has-experienced-an-error-2/>, retrieved 2026-11-16
[^b4-19]: derived from 3 evidence records: #12223, #12225, #12229
[^b4-20]: #12229 WordPress.org support thread, <https://wordpress.org/support/topic/amp-conflict-with-block-editor/>, retrieved 2026-11-16
[^b4-21]: #12228 WordPress.org support thread, <https://wordpress.org/support/topic/amp-on-woodmart-theme/>, retrieved 2026-11-16
[^b4-22]: #12231 WordPress.org support thread, <https://wordpress.org/support/topic/function-amp_has_paired_endpoint-was-called-incorrectly/>, retrieved 2026-11-16
[^b4-23]: #13625 WordPress.org description, <https://wordpress.org/plugins/amp/>, retrieved 2026-11-16
[^b4-24]: derived from 3 evidence records: #20417, #20418, #20419
[^b4-25]: #12273 WordPress.org review, <https://wordpress.org/support/topic/most-outstanding-amp/>, retrieved 2026-11-16
[^b4-26]: #2159 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b4-27]: derived from 6 evidence records: #2155, #2156, #2163, #12225, #12228, #12229
[^b4-28]: derived from 4 evidence records: #12223, #12225, #12261, #12269
[^b4-29]: derived from 8 evidence records: #12223, #12224, #12225, #12228, #12229, #12230, #12232, #12233
[^b4-30]: #20417 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=amp+alternative>, retrieved 2026-11-16
[^b4-31]: derived from 3 evidence records: #2152, #2154, #20417
[^b4-32]: derived from 7 evidence records: #2155, #2156, #2163, #12223, #12225, #12228, #12229
[^b4-33]: derived from 3 evidence records: #2152, #12273, #20417

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

<details><summary><b>5. WooSidebars</b>, score 60.6</summary>

### WooSidebars

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 504; Orphan Radar brief -->

Score **60.6[^b5-4]** of cfg:100 · signals: abandonment, displacement

#### 1. Summary

WooSidebars on WordPress.org plugin directory has 100,000[^b5-1] users, was last updated 2024-04-03[^b5-2], and shows abandonment, displacement; its users' most common fixable complaint is “broken by a platform, browser or php update”[^b5-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2024-04-03[^b5-2]; 31[^b5-2] months ago
  - recent support threads with zero replies: 5[^b5-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.5.14[^b5-6]; current WordPress is 7.1.4[^b5-7]; 6[^b5-8] major releases behind
- **Displacement event** (present):
  - platform break mentioned: platform break[^b5-9]; in 5[^b5-9] records; latest dated mention 2023-07-20[^b5-10]
  - sunset mentioned: sunset[^b5-11]; in 4[^b5-11] records; latest dated mention 2026-05-24[^b5-12]
- **Pain density** (weak):
  - recent complaints (low-star reviews, negative threads, issues): 2[^b5-3] complaints in the last twelve months

Dated sources for the events:
- “Is this plugin abandoned?. Is it compatible with PHP 8.3? …etc… Thanks!” — [WordPress.org support thread](https://wordpress.org/support/topic/is-this-plugin-abandoned-131/)[^b5-12], 2026-05-24[^b5-12]
- “Is the plugin support abandoned?. Please bump the version. We are getting abandonment notices. @mattyza @woothemes @automattic” — [WordPress.org support thread](https://wordpress.org/support/topic/is-the-plugin-support-abandoned-2/)[^b5-13], 2024-03-12[^b5-13]
- “Compatibility with PHP 8.2. Hi. I understood that this plugin is no longer maintained but is there any way to make it works with PHP 8.2 ? It is currently in …” — [WordPress.org support thread](https://wordpress.org/support/topic/compatibility-with-php-8-2-11/)[^b5-10], 2023-07-20[^b5-10]
- “Error with PHP 8.0. Hello, I have try to set a website to PHP 8.0 but have this error : Unknown format specifier "a" in …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-with-php-8-0/)[^b5-14], 2022-03-03[^b5-14]
- “PHP 8.0 Error. 5 stars There is a problem with line 170 in class-woo-sidebars.php which can be fixed by changing the %a to a %s. From this: 'search_items' => …” (5[^b5-15]★) — [WordPress.org review](https://wordpress.org/support/topic/php-8-0-error-4/)[^b5-15], 2021-09-19[^b5-15]

#### 3. Stranded users

- 100,000[^b5-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/woosidebars/>), read from WordPress.org on 2026-11-16[^b5-1]

#### 4. Top complaints

**Broken by a platform, browser or PHP update** (2[^b5-3] complaints)
> “Is this plugin abandoned?. Is it compatible with PHP 8.3? …etc… Thanks!” — [WordPress.org support thread](https://wordpress.org/support/topic/is-this-plugin-abandoned-131/)[^b5-12], 2026-05-24[^b5-12]
>
> “Errors with PHP 8.3: translation too early. Hello, PHP 8.3 is logging errors : The bug in woosidebars – class-woo-conditions.php:57 : public function __construct () { $this->meta_box_settings['title'] = __( …” — [WordPress.org support thread](https://wordpress.org/support/topic/errors-with-php-8-3-translation-too-early/)[^b5-16], 2025-12-15[^b5-16]


#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “WooSidebars adds functionality to display different widgets in a sidebar, according to a context (for example, a specific page or a category).”[^b5-17]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b5-3]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/woosidebars/>[^b5-17]
- Replacement searches: none found for the alternative / not working / pricing queries[^b5-18].
- Public threads where people asked for an alternative (links only):
  - [“Compatibility with PHP 8.2”](https://wordpress.org/support/topic/compatibility-with-php-8-2-11/)[^b5-10]
  - [WooSidebars breaking the layout of WooCommerce Products page](https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page/)[^b5-19]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Lots of great features and works amazing!!!. 5 stars For being a free plugin it almost feels like one I paid for. Where to start so many features and customization things that I …” (5[^b5-20]★) — [WordPress.org review](https://wordpress.org/support/topic/lots-of-great-features-and-works-amazing/)[^b5-20], 2015-08-28[^b5-20]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b5-21].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “WooSidebars”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Few recent complaints, so the problem list may be incomplete or unrepresentative.
- Nobody's autocomplete suggests searching for an alternative yet.
- Maintained by the platform's own organisation (author: “WooThemes”[^b5-22]): it may be fixed or folded into the platform, and users may distrust a third-party replacement.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b5-1] |
| Abandonment | well evidenced (listing metrics) | [^b5-23] |
| Displacement event | well evidenced | [^b5-24] |
| Top complaints | thin | [^b5-3] |
| Replacement demand in search | checked, none found | [^b5-25] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): WooSidebars, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “WooSidebars adds functionality to display different widgets in a sidebar, according to a context (for example, a specific page or a category).”[^b5-17]

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
| demand | 9.1[^b5-26] | cfg:25 | audience on a log scale; rating count |
| supply failure | 21[^b5-27] | cfg:25 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 10.5[^b5-3] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 11[^b5-28] | cfg:15 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| willingness to pay | 2[^b5-29] | cfg:10 | users mention paying or pricing |
| timing | 7[^b5-12] | cfg:10 | recency of the latest displacement event |

#### Evidence

[^b5-1]: #4790 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b5-2]: #4793 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b5-3]: derived from 2 evidence records: #11666, #11670
[^b5-4]: derived from 34 evidence records: #4790, #4792, #4793, #4794, #4801, #11665, #11666, #11667, #11668, #11669, #11670, #11671, #11672, #11673, #11674, #11675, #11676, #11677, #11678, #11680, #11682, #11683, #11684, #11686, #11687, #11688, #11689, #11690, #11692, #11693, #11694, #11719, #20420, #20422
[^b5-5]: derived from 5 evidence records: #11665, #11667, #11668, #11669, #11670
[^b5-6]: #4794 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b5-7]: #4801 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b5-8]: derived from 2 evidence records: #4794, #4801
[^b5-9]: derived from 5 evidence records: #11675, #11679, #11685, #11698, #11700
[^b5-10]: #11675 WordPress.org support thread, <https://wordpress.org/support/topic/compatibility-with-php-8-2-11/>, retrieved 2026-11-16
[^b5-11]: derived from 4 evidence records: #11666, #11671, #11675, #11688
[^b5-12]: #11666 WordPress.org support thread, <https://wordpress.org/support/topic/is-this-plugin-abandoned-131/>, retrieved 2026-11-16
[^b5-13]: #11671 WordPress.org support thread, <https://wordpress.org/support/topic/is-the-plugin-support-abandoned-2/>, retrieved 2026-11-16
[^b5-14]: #11679 WordPress.org support thread, <https://wordpress.org/support/topic/error-with-php-8-0/>, retrieved 2026-11-16
[^b5-15]: #11698 WordPress.org review, <https://wordpress.org/support/topic/php-8-0-error-4/>, retrieved 2026-11-16
[^b5-16]: #11670 WordPress.org support thread, <https://wordpress.org/support/topic/errors-with-php-8-3-translation-too-early/>, retrieved 2026-11-16
[^b5-17]: #13844 WordPress.org description, <https://wordpress.org/plugins/woosidebars/>, retrieved 2026-11-16
[^b5-18]: derived from 3 evidence records: #20420, #20421, #20422
[^b5-19]: #11689 WordPress.org support thread, <https://wordpress.org/support/topic/woosidebars-breaking-the-layout-of-woocommerce-products-page/>, retrieved 2026-11-16
[^b5-20]: #11719 WordPress.org review, <https://wordpress.org/support/topic/lots-of-great-features-and-works-amazing/>, retrieved 2026-11-16
[^b5-21]: #4797 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b5-22]: #4798 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=4&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b5-23]: derived from 8 evidence records: #4793, #4794, #4801, #11665, #11667, #11668, #11669, #11670
[^b5-24]: derived from 8 evidence records: #11666, #11671, #11675, #11679, #11685, #11688, #11698, #11700
[^b5-25]: #20420 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=woosidebars+alternative>, retrieved 2026-11-16
[^b5-26]: derived from 3 evidence records: #4790, #4792, #20420
[^b5-27]: derived from 29 evidence records: #4793, #4794, #4801, #11665, #11666, #11667, #11668, #11669, #11670, #11671, #11672, #11673, #11674, #11675, #11676, #11677, #11678, #11680, #11682, #11683, #11684, #11686, #11687, #11688, #11689, #11690, #11692, #11693, #11694
[^b5-28]: derived from 4 evidence records: #4790, #11675, #11689, #20420
[^b5-29]: derived from 2 evidence records: #11719, #20422

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

<details><summary><b>6. Cookie AutoDelete</b>, score 59.4</summary>

### Cookie AutoDelete

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 352; Orphan Radar brief -->

Score **59.4[^b6-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

Cookie AutoDelete on Firefox Add-ons (addons.mozilla.org) has 157,821[^b6-1] users, was last updated 2022-12-12[^b6-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “stopped doing its core job on many sites or setups”[^b6-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2022-12-12[^b6-2]; 47[^b6-2] months ago
- **Displacement event** (present):
  - sunset mentioned: sunset[^b6-5]; in 1[^b6-5] records; latest dated mention 2025-09-10[^b6-5]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 6[^b6-6] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.54[^b6-7] stars; recent rating 4.04[^b6-8] stars

Dated sources for the events:
- “This was probably a good extension as of the last update (3 years ago). Now it's abandoned, unmantained, obsolete and maybe even dangerous. The list of domains …” (2[^b6-5]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2515531/)[^b6-5], 2025-09-10[^b6-5]

#### 3. Stranded users

- 157,821[^b6-1] users on Firefox Add-ons (addons.mozilla.org) (<https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>), read from addons.mozilla.org on 2026-11-16[^b6-1]

#### 4. Top complaints

**Stopped doing its core job on many sites or setups** (3[^b6-3] complaints)
> “Unfortunately no longer works. Says it deleted cookies but the cookies are still there, very deceiving. GitHub Issues ignored, project dead. What a shame, this is a much needed extension.” (1[^b6-9]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2541886/)[^b6-9], 2025-12-08[^b6-9]
>
> “It seems to me it no longer works.” (1[^b6-10]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2573927/)[^b6-10], 2026-01-25[^b6-10]
>
> “This extension hasn't been updated for 4 years and no longer works with Firefox. I now use "Auto-Delete Cookies for Privacy".” (1[^b6-11]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2775517/)[^b6-11], 2026-10-23[^b6-11]

**Broken by a platform, browser or PHP update** (1[^b6-12] complaints)
> “Windows 11 / Firefox 159.0.1 (64-Bit): Cookie AutoDelete reports "cookie deleted," but the cookie is still present in the website data. This is misleading because users may rely on the confirmation and assume the cookie …” (1[^b6-12]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2781120/)[^b6-12], 2026-11-05[^b6-12]

**A specific feature is missing** (1[^b6-13] complaints)
> “Does not work......... No blacklist. No setting to delete everything by default unless whitelisted. wtf is this garbage?” (1[^b6-13]★) — [addons.mozilla.org review](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2633438/)[^b6-13], 2026-04-06[^b6-13]

Plus 1[^b6-14] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Control your cookies! This WebExtension is inspired by Self Destructing Cookies. When a tab closes, any cookies not being used are automatically deleted. Keep the ones you trust (forever/until …”[^b6-15]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b6-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b6-12]
- Adds the requested feature (fixes: a specific feature is missing)[^b6-13]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **Firefox Add-ons (addons.mozilla.org)**, where the incumbent is: <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>[^b6-15]
- Replacement searches to target (Google autocomplete):
  - `cookie autodelete alternative`[^b6-16]
  - `cookie autodelete alternative reddit`[^b6-16]
  - `cookie autodelete alternative chrome`[^b6-16]
  - `cookie autodelete not working`[^b6-17]
- Public threads where people asked for an alternative (links only):
  - [I’ve been looking for an extension that gives flexible control over cookies, and Cookie …](https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2721751/)[^b6-18]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: MIT License[^b6-19].
- Forking: Forking is permitted; keep the copyright and license notice.
- Use a new name and new branding. Do not use “Cookie AutoDelete”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b6-1] |
| Abandonment | well evidenced (listing metrics) | [^b6-2] |
| Displacement event | thin (single reviewer claims) | [^b6-5] |
| Top complaints | thin | [^b6-20] |
| Replacement demand in search | well evidenced | [^b6-16] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Cookie AutoDelete, listed on Firefox Add-ons (addons.mozilla.org).
What it does, in its own listing's words: “Control your cookies! This WebExtension is inspired by Self Destructing Cookies. When a tab closes, any cookies not being used are automatically deleted. Keep the ones you trust (forever/until …”[^b6-15]

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
| demand | 19.4[^b6-21] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 10.9[^b6-22] | cfg:25 | months since last update; last-year rating below lifetime rating; displacement event: sunset mentioned |
| pain specificity | 9[^b6-6] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 15[^b6-23] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| willingness to pay | none | cfg:10 | nothing |
| timing | 5.1[^b6-5] | cfg:10 | recency of the latest displacement event; complaints are still arriving |

#### Evidence

[^b6-1]: #14807 addons.mozilla.org user_count, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b6-2]: #14810 addons.mozilla.org last_updated, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b6-3]: derived from 3 evidence records: #15549, #15558, #15559
[^b6-4]: derived from 15 evidence records: #14807, #14808, #14809, #14810, #15548, #15549, #15550, #15553, #15556, #15558, #15559, #15565, #15571, #20468, #20470
[^b6-5]: #15565 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2515531/>, retrieved 2026-11-16
[^b6-6]: derived from 6 evidence records: #15548, #15549, #15550, #15556, #15558, #15559
[^b6-7]: #14808 addons.mozilla.org rating, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b6-8]: #15571 addons.mozilla.org rating_recent, <https://addons.mozilla.org/api/v5/ratings/rating/?addon=cookie-autodelete&sort=created&page_size=50>, retrieved 2026-11-16
[^b6-9]: #15559 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2541886/>, retrieved 2026-11-16
[^b6-10]: #15558 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2573927/>, retrieved 2026-11-16
[^b6-11]: #15549 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2775517/>, retrieved 2026-11-16
[^b6-12]: #15548 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2781120/>, retrieved 2026-11-16
[^b6-13]: #15556 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2633438/>, retrieved 2026-11-16
[^b6-14]: #15550 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2774981/>, retrieved 2026-11-16
[^b6-15]: #16027 addons.mozilla.org description, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/>, retrieved 2026-11-16
[^b6-16]: #20468 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+alternative>, retrieved 2026-11-16
[^b6-17]: #20469 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=cookie+autodelete+not+working>, retrieved 2026-11-16
[^b6-18]: #15553 addons.mozilla.org review, <https://addons.mozilla.org/en-US/firefox/addon/cookie-autodelete/reviews/2721751/>, retrieved 2026-11-16
[^b6-19]: #14811 addons.mozilla.org license, <https://addons.mozilla.org/api/v5/addons/search/?app=firefox&type=extension&sort=users&page_size=50&page=2&lang=en-US>, retrieved 2026-11-16
[^b6-20]: derived from 5 evidence records: #15548, #15549, #15556, #15558, #15559
[^b6-21]: derived from 3 evidence records: #14807, #14809, #20468
[^b6-22]: derived from 4 evidence records: #14808, #14810, #15565, #15571
[^b6-23]: derived from 3 evidence records: #14807, #15553, #20468

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

<details><summary><b>7. Health Check & Troubleshooting</b>, score 59.1</summary>

### Health Check & Troubleshooting

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 265; Orphan Radar brief -->

Score **59.1[^b7-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

Health Check & Troubleshooting on WordPress.org plugin directory has 200,000[^b7-1] users, was last updated 2024-07-25[^b7-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b7-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2024-07-25[^b7-2]; 28[^b7-2] months ago
  - recent support threads with zero replies: 3[^b7-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.6.11[^b7-6]; current WordPress is 7.1.4[^b7-7]; 5[^b7-8] major releases behind
- **Displacement event** (present):
  - sunset mentioned: sunset[^b7-9]; in 2[^b7-9] records; latest dated mention 2026-07-26[^b7-10]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 8[^b7-11] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 3.6[^b7-12] stars; recent rating 3[^b7-13] stars

Dated sources for the events:
- “Plugin contains an unpatched security vulnerability.. I received a security message from WordFence about this plugin. Is it still being maintained or should I …” — [WordPress.org support thread](https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/)[^b7-10], 2026-07-26[^b7-10]
- “This plugin hasn’t been tested with the latest 3 major releases of WordPress.. This plugin hasn’t been tested with the latest 3 major releases of WordPress . …” — [WordPress.org support thread](https://wordpress.org/support/topic/this-plugin-hasnt-been-tested-with-the-latest-3-major-releases-of-wordpress-29/)[^b7-14], 2026-06-18[^b7-14]

#### 3. Stranded users

- 200,000[^b7-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/health-check/>), read from WordPress.org on 2026-11-16[^b7-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (2[^b7-3] complaints)
> “health-check There is a plugins_loaded error. 函数 _load_textdomain_just_in_time 调用不正确。 Translation loading for the health-check domain was triggered too early. This is usually an indicator for some code in the plugin or …” — [WordPress.org support thread](https://wordpress.org/support/topic/health-check-there-is-a-plugins_loaded-error/)[^b7-15], 2026-04-10[^b7-15]
>
> “PLEASE fix the security. There is no plugin that does what this does. And I did read this. https://wordpress.org/support/topic/are-you-going-to-fix-the-vulnerability/#post-18772118 But coincidence or no, very recently …” — [WordPress.org support thread](https://wordpress.org/support/topic/please-fix-the-security/)[^b7-16], 2026-06-26[^b7-16]

**No answer from the developer or support** (2[^b7-17] complaints)
> “Vulnerability found. According to WordFence and Jetpack, a vulnerability was found on December 21st in Site Health. Are you aware and when will it be resolved? I see that the plugin is not tested for compatibility since …” — [WordPress.org support thread](https://wordpress.org/support/topic/vulnerability-found-12/)[^b7-18], 2025-12-21[^b7-18]
>
> “Plugin contains an unpatched security vulnerability.. I received a security message from WordFence about this plugin. Is it still being maintained or should I delete it? Critical Problems: * The Plugin "Health Check & …” — [WordPress.org support thread](https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/)[^b7-10], 2026-07-26[^b7-10]

**Broken by a platform, browser or PHP update** (1[^b7-19] complaints)
> “Bug report: _load_textdomain_just_in_time warning in Health Check on WordPress 6. I’m seeing the following notice with WP_DEBUG enabled on WordPress 6.7+: Function _load_textdomain_just_in_time was called incorrectly. …” — [WordPress.org support thread](https://wordpress.org/support/topic/bug-report-_load_textdomain_just_in_time-warning-in-health-check-on-wordpress-6/)[^b7-19], 2026-09-27[^b7-19]

**A specific feature is missing** (1[^b7-20] complaints)
> “I can’t believe that. 1 star I can’t believe anyone gave this plugin 5 stars. Troubleshooting mode will break your site. It disables ALL plugins and it says that this will only affect you and NOT your other site …” (1[^b7-20]★) — [WordPress.org review](https://wordpress.org/support/topic/i-cant-believe-that/)[^b7-20], 2026-04-04[^b7-20]

Plus 2[^b7-21] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Health Check identifies common problems, and helps you troubleshoot plugin and theme conflicts.”[^b7-22]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b7-3]
- Responsive public issue tracker (fixes: no answer from the developer or support)[^b7-17]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b7-19]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

What users say about import, export or migration:
- “HEED ALL THE WARNINGS! THIS DESTROYED MY SITE!. 5 stars What other people are saying this plugin does, it did to me. As so many people describe, I used it once, and when I exited …” (5[^b7-23]★) — [WordPress.org review](https://wordpress.org/support/topic/heed-all-the-warnings-this-destroyed-my-site/)[^b7-23], 2024-11-28[^b7-23]
- “A disaster!. 1 star A disaster! The plugin deactivated and deleted most of my plugins. Impossible to restore without restoring the site from a backup. I’ve been an experienced …” (1[^b7-24]★) — [WordPress.org review](https://wordpress.org/support/topic/a-disaster-7/)[^b7-24], 2024-08-27[^b7-24]
- “Troubleshooting mode will screw your website. 1 star I needed to use this plugin to troubleshoot a plugin conflict on my website, it ended up screwing my website. I had to restore …” (1[^b7-25]★) — [WordPress.org review](https://wordpress.org/support/topic/troubleshooting-mode-will-screw-your-website/)[^b7-25], 2024-05-24[^b7-25]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/health-check/>[^b7-22]
- Replacement searches: not checked (unknown).
- Public threads where people asked for an alternative (links only):
  - [“Why i cannot use 2025 theme on diagnose mode?”](https://wordpress.org/support/topic/why-i-cannot-use-2025-theme-on-diagnose-mode/)[^b7-26]

#### 8. Price anchor

- Incumbent: the listing's business model is 'community'[^b7-27], i.e. it declares no commercial offering. Exact prices: unknown.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b7-28].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “Health Check & Troubleshooting”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- All evidence comes from a single source.
- Replacement searches were not checked.
- Maintained by the platform's own organisation (author: “WordPress.org”[^b7-29]): it may be fixed or folded into the platform, and users may distrust a third-party replacement.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b7-1] |
| Abandonment | well evidenced (listing metrics) | [^b7-30] |
| Displacement event | well evidenced | [^b7-9] |
| Top complaints | thin | [^b7-31] |
| Replacement demand in search | unknown |  |
| Price anchor | thin (no prices, only that the incumbent charges) | [^b7-27] |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Health Check & Troubleshooting, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Health Check identifies common problems, and helps you troubleshoot plugin and theme conflicts.”[^b7-22]

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
| demand | 11[^b7-32] | cfg:25 | audience on a log scale; rating count |
| supply failure | 19.6[^b7-33] | cfg:25 | months since last update; recent issues/threads with no reply; last-year rating below lifetime rating; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 10.5[^b7-11] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 11[^b7-34] | cfg:15 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| willingness to pay | none | cfg:10 | nothing |
| timing | 7[^b7-10] | cfg:10 | recency of the latest displacement event |

#### Evidence

[^b7-1]: #2551 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-2]: #2554 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-3]: derived from 2 evidence records: #11787, #11795
[^b7-4]: derived from 22 evidence records: #2551, #2552, #2553, #2554, #2555, #2563, #11785, #11786, #11787, #11790, #11793, #11795, #11801, #11802, #11804, #11814, #11815, #11816, #11817, #11818, #11819, #11820
[^b7-5]: derived from 3 evidence records: #11790, #11793, #11802
[^b7-6]: #2555 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-7]: #2563 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b7-8]: derived from 2 evidence records: #2555, #2563
[^b7-9]: derived from 2 evidence records: #11786, #11790
[^b7-10]: #11786 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-contains-an-unpatched-security-vulnerability-2/>, retrieved 2026-11-16
[^b7-11]: derived from 8 evidence records: #11785, #11786, #11787, #11795, #11801, #11815, #11816, #11817
[^b7-12]: #2552 WordPress.org rating, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-13]: derived from 6 evidence records: #11815, #11816, #11817, #11818, #11819, #11820
[^b7-14]: #11790 WordPress.org support thread, <https://wordpress.org/support/topic/this-plugin-hasnt-been-tested-with-the-latest-3-major-releases-of-wordpress-29/>, retrieved 2026-11-16
[^b7-15]: #11795 WordPress.org support thread, <https://wordpress.org/support/topic/health-check-there-is-a-plugins_loaded-error/>, retrieved 2026-11-16
[^b7-16]: #11787 WordPress.org support thread, <https://wordpress.org/support/topic/please-fix-the-security/>, retrieved 2026-11-16
[^b7-17]: derived from 2 evidence records: #11786, #11801
[^b7-18]: #11801 WordPress.org support thread, <https://wordpress.org/support/topic/vulnerability-found-12/>, retrieved 2026-11-16
[^b7-19]: #11785 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-_load_textdomain_just_in_time-warning-in-health-check-on-wordpress-6/>, retrieved 2026-11-16
[^b7-20]: #11816 WordPress.org review, <https://wordpress.org/support/topic/i-cant-believe-that/>, retrieved 2026-11-16
[^b7-21]: derived from 2 evidence records: #11815, #11817
[^b7-22]: #13658 WordPress.org description, <https://wordpress.org/plugins/health-check/>, retrieved 2026-11-16
[^b7-23]: #11830 WordPress.org review, <https://wordpress.org/support/topic/heed-all-the-warnings-this-destroyed-my-site/>, retrieved 2026-11-16
[^b7-24]: #11832 WordPress.org review, <https://wordpress.org/support/topic/a-disaster-7/>, retrieved 2026-11-16
[^b7-25]: #11834 WordPress.org review, <https://wordpress.org/support/topic/troubleshooting-mode-will-screw-your-website/>, retrieved 2026-11-16
[^b7-26]: #11804 WordPress.org support thread, <https://wordpress.org/support/topic/why-i-cannot-use-2025-theme-on-diagnose-mode/>, retrieved 2026-11-16
[^b7-27]: #2560 WordPress.org business_model, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-28]: #2558 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b7-29]: #2559 WordPress.org author, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=3&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b7-30]: derived from 6 evidence records: #2554, #2555, #2563, #11790, #11793, #11802
[^b7-31]: derived from 6 evidence records: #11785, #11786, #11787, #11795, #11801, #11816
[^b7-32]: derived from 2 evidence records: #2551, #2553
[^b7-33]: derived from 15 evidence records: #2552, #2554, #2555, #2563, #11786, #11790, #11793, #11802, #11814, #11815, #11816, #11817, #11818, #11819, #11820
[^b7-34]: derived from 2 evidence records: #2551, #11804

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

<details><summary><b>8. WebP Express</b>, score 59.0</summary>

### WebP Express

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 208; Orphan Radar brief -->

Score **59[^b8-4]** of cfg:100 · signals: abandonment, displacement, pain

#### 1. Summary

WebP Express on WordPress.org plugin directory has 300,000[^b8-1] users, was last updated 2026-10-18[^b8-2], and shows abandonment, displacement, pain; its users' most common fixable complaint is “crashes, errors and broken pages”[^b8-3].

#### 2. What happened

- **Abandonment** (present):
  - months since last update: last updated 2026-10-18[^b8-2]; 1[^b8-2] months ago
  - support threads opened vs resolved in the last two months: 4[^b8-5] support threads opened in the last two months; 0[^b8-6] resolved; 100%[^b8-7] unresolved
  - recent support threads with zero replies: 13[^b8-8] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.9.11[^b8-9]; current WordPress is 7.1.4[^b8-10]; 2[^b8-11] major releases behind
- **Displacement event** (present):
  - sunset mentioned: sunset[^b8-12]; in 1[^b8-12] records; latest dated mention 2025-03-12[^b8-12]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 13[^b8-13] complaints in the last twelve months

Dated sources for the events:
- “abandoned plugin: Guys, this plugin was very good, but it seems that its developer abandoned it, what could have happened?” — [WordPress.org support thread](https://wordpress.org/support/topic/abandoned-plugin-107/)[^b8-12], 2025-03-12[^b8-12]

#### 3. Stranded users

- 300,000[^b8-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/webp-express/>), read from WordPress.org on 2026-11-16[^b8-1]

#### 4. Top complaints

**Crashes, errors and broken pages** (7[^b8-3] complaints)
> “yoast post xml parse error. Hi When disable WebP Express plugin the site-map is working again the option ‘alter html’ is checked The other site maps are working fine. eg:page-xml, cpt-xml, etc what could break the site …” — [WordPress.org support thread](https://wordpress.org/support/topic/yoast-post-xml-parse-error/)[^b8-14], 2025-12-07[^b8-14]
>
> “Error: timeout. When I click Bulk Convert, it shows ‘Receiving list of files to convert…’, and after a while, it shows ‘Error: timeout’ I set max_execution_time=50000 in php.ini, but it doesn’t working.” — [WordPress.org support thread](https://wordpress.org/support/topic/error-timeout-3/)[^b8-15], 2026-07-28[^b8-15]
>
> “WPBakery Bug. Hello, With the standard WPBakery settings, many photos are no longer displaying. I don’t know if the issue exists without WPBakery, but it’s not reassuring. Best Regards, Pierre” — [WordPress.org support thread](https://wordpress.org/support/topic/wpbakery-bug/)[^b8-16], 2026-09-15[^b8-16]

**Broken by a platform, browser or PHP update** (1[^b8-17] complaints)
> “500 error: unescaped space in absolute path breaks .htaccess RewriteCond. Hi, when the WordPress path contains a space, WebP Express writes .htaccess rules that Apache cannot parse. Every request to wp-content/uploads …” — [WordPress.org support thread](https://wordpress.org/support/topic/500-error-unescaped-space-in-absolute-path-breaks-htaccess-rewritecond/)[^b8-17], 2026-11-09[^b8-17]

**Cannot import, export or migrate data** (1[^b8-18] complaints)
> “Deleting Plugin Breaks Images. I’ve gotten a lot of value from WebP Express, but it’s now redundant with an image conversion function offered by my web host. So I deactivated the plugin, which didn’t cause any issues. …” — [WordPress.org support thread](https://wordpress.org/support/topic/deleting-plugin-breaks-images/)[^b8-18], 2026-05-26[^b8-18]

**A specific feature is missing** (1[^b8-19] complaints)
> “Exclude gravity forms uploads from conversion. Hi this is a feature request. it would be great to exclude gravity forms uploads (uploads > gravity_forms) from bulk conversion. those will never be displayed on the front …” — [WordPress.org support thread](https://wordpress.org/support/topic/exclude-gravity-forms-uploads-from-conversion/)[^b8-19], 2025-12-17[^b8-19]

**Stopped doing its core job on many sites or setups** (1[^b8-20] complaints)
> “Create webp files upon request – broken. In the latest version the ‘Create webp files upon request’ does not work. The Error in the Self test is: x-webp-express-error: Sanity check FAILED for WebP Express content dir: …” — [WordPress.org support thread](https://wordpress.org/support/topic/create-webp-files-upon-request-broken/)[^b8-20], 2025-12-22[^b8-20]

Plus 2[^b8-21] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Serve autogenerated WebP images instead of jpeg/png to browsers that supports WebP.”[^b8-22]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b8-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b8-17]
- Open formats with one-click import and export (fixes: cannot import, export or migrate data)[^b8-18]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Formats named in the evidence: JSON[^b8-23], XML[^b8-24], HTML[^b8-24].

What users say about import, export or migration:
- “Path is outside resolved document root. Hi there I’m getting the following error which I am told comes from Webp Express when it tries to convert during a WPAllImport import Path …” — [WordPress.org support thread](https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/)[^b8-25], 2026-09-24[^b8-25]
- “Deleting Plugin Breaks Images. I’ve gotten a lot of value from WebP Express, but it’s now redundant with an image conversion function offered by my web host. So I deactivated the …” — [WordPress.org support thread](https://wordpress.org/support/topic/deleting-plugin-breaks-images/)[^b8-18], 2026-05-26[^b8-18]
- “wod-options.json error for auto generating images. When testing the "redirection to converter" and "WebP Realizer" we see the following error: - x-webp-express-error: Error …” — [WordPress.org support thread](https://wordpress.org/support/topic/wod-options-json-error-for-auto-generating-images/)[^b8-23], 2026-01-05[^b8-23]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/webp-express/>[^b8-22]
- Replacement searches to target (Google autocomplete):
  - `webp express alternative`[^b8-26]
- Public threads where people asked for an alternative (links only):
  - [Path is outside resolved document root](https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/)[^b8-25]
  - [webp express yoast seo bug solved](https://wordpress.org/support/topic/webp-express-yoast-seo-bug-solved/)[^b8-27]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “Amazing. 5 stars This stuff is the real deal: just an app that works, no hassling like premium versions or special features. Thank you.” (5[^b8-28]★) — [WordPress.org review](https://wordpress.org/support/topic/amazing-4053/)[^b8-28], 2024-11-11[^b8-28]
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b8-29].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “WebP Express”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- The incumbent was updated recently (2026-10-18[^b8-2]): it may be recovering rather than abandoned.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b8-1] |
| Abandonment | well evidenced (listing metrics) | [^b8-30] |
| Displacement event | thin (single reviewer claims) | [^b8-12] |
| Top complaints | well evidenced | [^b8-31] |
| Replacement demand in search | well evidenced | [^b8-26] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): WebP Express, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Serve autogenerated WebP images instead of jpeg/png to browsers that supports WebP.”[^b8-22]

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
| demand | 18.5[^b8-32] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 9.7[^b8-33] | cfg:25 | months since last update; share of recent support threads unresolved; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 10.8[^b8-13] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 15[^b8-34] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| willingness to pay | 2[^b8-35] | cfg:10 | users mention paying or pricing |
| timing | 3[^b8-12] | cfg:10 | complaints are still arriving |

#### Evidence

[^b8-1]: #2043 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-2]: #2046 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-3]: derived from 7 evidence records: #13291, #13292, #13293, #13296, #13302, #13303, #13307
[^b8-4]: derived from 25 evidence records: #2043, #2045, #2046, #2047, #2048, #2049, #2054, #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307, #13311, #13316, #13319, #13321, #13324, #20471, #20473
[^b8-5]: #2048 WordPress.org support_threads_recent, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-6]: #2049 WordPress.org support_threads_resolved, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-7]: derived from 2 evidence records: #2048, #2049
[^b8-8]: derived from 13 evidence records: #13289, #13290, #13291, #13292, #13293, #13294, #13295, #13296, #13298, #13300, #13303, #13306, #13307
[^b8-9]: #2047 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=2&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b8-10]: #2054 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b8-11]: derived from 2 evidence records: #2047, #2054
[^b8-12]: #13316 WordPress.org support thread, <https://wordpress.org/support/topic/abandoned-plugin-107/>, retrieved 2026-11-16
[^b8-13]: derived from 13 evidence records: #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307, #13319, #13321
[^b8-14]: #13307 WordPress.org support thread, <https://wordpress.org/support/topic/yoast-post-xml-parse-error/>, retrieved 2026-11-16
[^b8-15]: #13296 WordPress.org support thread, <https://wordpress.org/support/topic/error-timeout-3/>, retrieved 2026-11-16
[^b8-16]: #13293 WordPress.org support thread, <https://wordpress.org/support/topic/wpbakery-bug/>, retrieved 2026-11-16
[^b8-17]: #13289 WordPress.org support thread, <https://wordpress.org/support/topic/500-error-unescaped-space-in-absolute-path-breaks-htaccess-rewritecond/>, retrieved 2026-11-16
[^b8-18]: #13298 WordPress.org support thread, <https://wordpress.org/support/topic/deleting-plugin-breaks-images/>, retrieved 2026-11-16
[^b8-19]: #13306 WordPress.org support thread, <https://wordpress.org/support/topic/exclude-gravity-forms-uploads-from-conversion/>, retrieved 2026-11-16
[^b8-20]: #13305 WordPress.org support thread, <https://wordpress.org/support/topic/create-webp-files-upon-request-broken/>, retrieved 2026-11-16
[^b8-21]: derived from 2 evidence records: #13319, #13321
[^b8-22]: #13616 WordPress.org description, <https://wordpress.org/plugins/webp-express/>, retrieved 2026-11-16
[^b8-23]: #13302 WordPress.org support thread, <https://wordpress.org/support/topic/wod-options-json-error-for-auto-generating-images/>, retrieved 2026-11-16
[^b8-24]: derived from 2 evidence records: #13307, #13311
[^b8-25]: #13292 WordPress.org support thread, <https://wordpress.org/support/topic/path-is-outside-resolved-document-root-3/>, retrieved 2026-11-16
[^b8-26]: #20471 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=webp+express+alternative>, retrieved 2026-11-16
[^b8-27]: #13311 WordPress.org support thread, <https://wordpress.org/support/topic/webp-express-yoast-seo-bug-solved/>, retrieved 2026-11-16
[^b8-28]: #13324 WordPress.org review, <https://wordpress.org/support/topic/amazing-4053/>, retrieved 2026-11-16
[^b8-29]: #2050 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b8-30]: derived from 18 evidence records: #2046, #2047, #2048, #2049, #2054, #13289, #13290, #13291, #13292, #13293, #13294, #13295, #13296, #13298, #13300, #13303, #13306, #13307
[^b8-31]: derived from 11 evidence records: #13289, #13291, #13292, #13293, #13296, #13298, #13302, #13303, #13305, #13306, #13307
[^b8-32]: derived from 3 evidence records: #2043, #2045, #20471
[^b8-33]: derived from 6 evidence records: #2046, #2047, #2048, #2049, #2054, #13316
[^b8-34]: derived from 4 evidence records: #2043, #13292, #13311, #20471
[^b8-35]: derived from 2 evidence records: #13324, #20473

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

<details><summary><b>9. Image Optimizer – Compress Images and Convert to WebP or AVIF</b>, score 57.5</summary>

### Image Optimizer – Compress Images and Convert to WebP or AVIF

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 70; Orphan Radar brief -->

Score **57.5[^b9-4]** of cfg:100 · signals: pain

#### 1. Summary

Image Optimizer – Compress Images and Convert to WebP or AVIF on WordPress.org plugin directory has 1,000,000[^b9-1] users, was last updated 2026-09-22[^b9-2], and shows pain; its users' most common fixable complaint is “features moved behind a paywall or subscription”[^b9-3].

#### 2. What happened

- **Abandonment** (weak):
  - months since last update: last updated 2026-09-22[^b9-2]; 2[^b9-2] months ago
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 7.0.8[^b9-5]; current WordPress is 7.1.4[^b9-6]; 1[^b9-7] major releases behind
- **Displacement event** (weak):
  - platform break mentioned: platform break[^b9-8]; in 1[^b9-8] records; latest dated mention 2024-10-06[^b9-8]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 13[^b9-9] complaints in the last twelve months

Dated sources for the events:
- “Heads up: Not compatible with media cloud offload. Just in case anyone else might try to mix this with the cloud offload plugin https://mediacloud.press/ It …” — [WordPress.org support thread](https://wordpress.org/support/topic/heads-up-not-compatible-with-media-cloud-offload/)[^b9-8], 2024-10-06[^b9-8]

#### 3. Stranded users

- 1,000,000[^b9-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/image-optimization/>), read from WordPress.org on 2026-11-16[^b9-1]

#### 4. Top complaints

**Features moved behind a paywall or subscription** (5[^b9-3] complaints)
> “Including all photo sizes in the 200 free photo limit. 1 star Including all photo sizes in the 200 free photo limit really makes one feel cheated. It’s a disgraceful tactic to get people to upgrade to a paid package. …” (1[^b9-10]★) — [WordPress.org review](https://wordpress.org/support/topic/including-all-photo-sizes-in-the-200-free-photo-limit/)[^b9-10], 2026-02-12[^b9-10]
>
> “Another Bait and Switch Plugin. 1 star This is another bait and switch plugin where they offer a service for free for a limited time, then stop providing the service because they want you to go pro. No thank you. I can …” (1[^b9-11]★) — [WordPress.org review](https://wordpress.org/support/topic/another-bait-and-switch-plugin/)[^b9-11], 2026-06-19[^b9-11]
>
> “Cry for Credit Upgrade.. 1 star Barely cuts the image size by 50% – deactivating.” (1[^b9-12]★) — [WordPress.org review](https://wordpress.org/support/topic/cry-for-credit-upgrade/)[^b9-12], 2026-10-09[^b9-12]

**Broken by a platform, browser or PHP update** (3[^b9-13] complaints)
> “Breaks Post Editing with Javascript Console Errors. 1 star We were upgraded to WordPress 6.9 and our post editing capabilities broke because of this plugin. There were numerous console errors and we could not use the …” (1[^b9-14]★) — [WordPress.org review](https://wordpress.org/support/topic/breaks-post-editing-with-javascript-console-errors/)[^b9-14], 2026-01-06[^b9-14]
>
> “Fatal Error on Deactivation. Plugin was not running because of missing exif and filinfo. Attempting to deactivate results in the following error: Fatal error: Uncaught TypeError: call_user_func_array(): Argument #1 …” — [WordPress.org support thread](https://wordpress.org/support/topic/fatal-error-on-deactivation-2/)[^b9-15], 2026-06-11[^b9-15]
>
> “Fatals with 1.7.0 Update. Seeing this fatal on a large number of sites: PHP Fatal error: Uncaught TypeError: ImageOptimization\Modules\Connect\Module::get_connect(): Return value must be of type …” — [WordPress.org support thread](https://wordpress.org/support/topic/fatals-with-1-7-0-update/)[^b9-16], 2026-01-20[^b9-16]

**Stopped doing its core job on many sites or setups** (2[^b9-17] complaints)
> “Don’t use. 1 star Don’t use broke my website, very bad code. This topic was modified 9 months, 4 weeks ago by hacktronics .” (1[^b9-18]★) — [WordPress.org review](https://wordpress.org/support/topic/dont-use-29/)[^b9-18], 2026-01-21[^b9-18]
>
> “Subscription fees are non-refundable. 1 star Be prepared that if after purchasing a subscription the plugin does not work, no one will refund your money. Instead of a refund, they ask for access to the site to see why …” (1[^b9-19]★) — [WordPress.org review](https://wordpress.org/support/topic/subscription-fees-are-non-refundable/)[^b9-19], 2025-12-15[^b9-19]

**Crashes, errors and broken pages** (1[^b9-20] complaints)
> “Poor user experience. 1 star Extremely poor experience. This plugin ruined my homepage layout immediately after activation. To make matters worse, I encountered an error when trying to deactivate it. I deeply regret …” (1[^b9-20]★) — [WordPress.org review](https://wordpress.org/support/topic/poor-user-experience-6/)[^b9-20], 2026-04-27[^b9-20]

**Slow, heavy or resource-hungry** (1[^b9-21] complaints)
> “Don’t Use. 1 star With a jpeg quality 11 image quality ca 4% memory is saved – a total waste of money … Bulk optimisation fails completely …” (1[^b9-21]★) — [WordPress.org review](https://wordpress.org/support/topic/dont-use-28/)[^b9-21], 2025-12-16[^b9-21]

Plus 1[^b9-22] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Image Optimizer is an easy-to-use WordPress plugin that reduces image size through various compression and resizing techniques – all of which preserve …”[^b9-23]
- Core features free, or a fair one-time price (fixes: features moved behind a paywall or subscription)[^b9-3]
- Works on the current platform release and PHP version (fixes: broken by a platform, browser or php update)[^b9-13]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b9-17]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Export format: unknown. No evidence record states whether or how data can be exported.

What users say about import, export or migration:
- “crash my site. When you activate the plugin although all the images are on the server, most have disappeared from the posts where they should be. Deactivating the plugin did not …” — [WordPress.org support thread](https://wordpress.org/support/topic/crash-my-site-13/)[^b9-24], 2024-02-05[^b9-24]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/image-optimization/>[^b9-23]
- Replacement searches to target (Google autocomplete):
  - `ewww image optimizer alternative`[^b9-25]
  - `elementor image optimizer not working`[^b9-26]
  - `ewww image optimizer webp not working`[^b9-26]
  - `ewww image optimizer pricing`[^b9-27]
  - `elementor image optimizer pricing`[^b9-27]
  - `fastly image optimizer pricing`[^b9-27]
  - `image optimizer increase size`[^b9-27]
- Public threads where people asked for an alternative (links only):
  - [Before switch from imagify to Elementor image optimize](https://wordpress.org/support/topic/before-switch-from-imagify-to-elementor-image-option/)[^b9-28]
  - [Restore original image not working](https://wordpress.org/support/topic/restore-original-image-not-working/)[^b9-29]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- What users say about paying:
  - “It works for some. 3 stars Optimized some of our media, only hundreds out of thousands. I guess that’s what I get for not paying for it?” (3[^b9-30]★) — [WordPress.org review](https://wordpress.org/support/topic/it-works-for-some/)[^b9-30], 2026-10-28[^b9-30]
  - “Another Bait and Switch Plugin. 1 star This is another bait and switch plugin where they offer a service for free for a limited time, then stop providing the service because they …” (1[^b9-11]★) — [WordPress.org review](https://wordpress.org/support/topic/another-bait-and-switch-plugin/)[^b9-11], 2026-06-19[^b9-11]
  - “Cheated by this company. 1 star A couple days ago, I Paid $60 to purchase an upgrade for Elementor as part of my WordPress. It had a feature called Image Optimizer in side it. I …” (1[^b9-31]★) — [WordPress.org review](https://wordpress.org/support/topic/cheated-by-this-company/)[^b9-31], 2026-06-07[^b9-31]
  - “Subscription fees are non-refundable. 1 star Be prepared that if after purchasing a subscription the plugin does not work, no one will refund your money. Instead of a refund, they …” (1[^b9-19]★) — [WordPress.org review](https://wordpress.org/support/topic/subscription-fees-are-non-refundable/)[^b9-19], 2025-12-15[^b9-19]
- People search for “Image Optimizer – Compress Images and Convert to WebP or AVIF pricing”[^b9-27].
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b9-32].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “Image Optimizer – Compress Images and Convert to WebP or AVIF”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- The incumbent was updated recently (2026-09-22[^b9-2]): it may be recovering rather than abandoned.
- Fewer than two of the three signals are present; the opportunity rests on one kind of evidence.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b9-1] |
| Abandonment | thin | [^b9-33] |
| Displacement event | thin (single reviewer claims) | [^b9-8] |
| Top complaints | well evidenced | [^b9-34] |
| Replacement demand in search | well evidenced | [^b9-25] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Image Optimizer – Compress Images and Convert to WebP or AVIF, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Image Optimizer is an easy-to-use WordPress plugin that reduces image size through various compression and resizing techniques – all of which preserve …”[^b9-23]

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
| demand | 19.5[^b9-35] | cfg:25 | audience on a log scale; rating count; people search for '‹product› alternative' |
| supply failure | 5.1[^b9-36] | cfg:25 | months since last update; recent issues/threads with no reply; not tested with current platform releases; displacement event: platform break mentioned |
| pain specificity | 12.9[^b9-9] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 15[^b9-37] | cfg:15 | a replacement can be listed in the same marketplace; replacement searches to target; public threads asking for an alternative |
| willingness to pay | 5[^b9-38] | cfg:10 | users mention paying or pricing; people search for its pricing |
| timing | none | cfg:10 | nothing |

#### Evidence

[^b9-1]: #701 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b9-2]: #704 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b9-3]: derived from 5 evidence records: #11967, #11969, #11970, #11972, #11978
[^b9-4]: derived from 29 evidence records: #701, #703, #704, #705, #712, #11942, #11943, #11952, #11954, #11955, #11959, #11960, #11965, #11967, #11969, #11970, #11972, #11974, #11978, #11979, #11980, #11981, #11982, #11983, #11987, #11989, #11992, #20480, #20482
[^b9-5]: #705 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b9-6]: #712 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b9-7]: derived from 2 evidence records: #705, #712
[^b9-8]: #11952 WordPress.org support thread, <https://wordpress.org/support/topic/heads-up-not-compatible-with-media-cloud-offload/>, retrieved 2026-11-16
[^b9-9]: derived from 13 evidence records: #11942, #11943, #11967, #11969, #11970, #11972, #11974, #11978, #11979, #11980, #11981, #11982, #11983
[^b9-10]: #11978 WordPress.org review, <https://wordpress.org/support/topic/including-all-photo-sizes-in-the-200-free-photo-limit/>, retrieved 2026-11-16
[^b9-11]: #11970 WordPress.org review, <https://wordpress.org/support/topic/another-bait-and-switch-plugin/>, retrieved 2026-11-16
[^b9-12]: #11967 WordPress.org review, <https://wordpress.org/support/topic/cry-for-credit-upgrade/>, retrieved 2026-11-16
[^b9-13]: derived from 3 evidence records: #11942, #11943, #11981
[^b9-14]: #11981 WordPress.org review, <https://wordpress.org/support/topic/breaks-post-editing-with-javascript-console-errors/>, retrieved 2026-11-16
[^b9-15]: #11942 WordPress.org support thread, <https://wordpress.org/support/topic/fatal-error-on-deactivation-2/>, retrieved 2026-11-16
[^b9-16]: #11943 WordPress.org support thread, <https://wordpress.org/support/topic/fatals-with-1-7-0-update/>, retrieved 2026-11-16
[^b9-17]: derived from 2 evidence records: #11980, #11983
[^b9-18]: #11980 WordPress.org review, <https://wordpress.org/support/topic/dont-use-29/>, retrieved 2026-11-16
[^b9-19]: #11983 WordPress.org review, <https://wordpress.org/support/topic/subscription-fees-are-non-refundable/>, retrieved 2026-11-16
[^b9-20]: #11974 WordPress.org review, <https://wordpress.org/support/topic/poor-user-experience-6/>, retrieved 2026-11-16
[^b9-21]: #11982 WordPress.org review, <https://wordpress.org/support/topic/dont-use-28/>, retrieved 2026-11-16
[^b9-22]: #11979 WordPress.org review, <https://wordpress.org/support/topic/its-just-bad/>, retrieved 2026-11-16
[^b9-23]: #13506 WordPress.org description, <https://wordpress.org/plugins/image-optimization/>, retrieved 2026-11-16
[^b9-24]: #11964 WordPress.org support thread, <https://wordpress.org/support/topic/crash-my-site-13/>, retrieved 2026-11-16
[^b9-25]: #20480 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+alternative>, retrieved 2026-11-16
[^b9-26]: #20481 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+not+working>, retrieved 2026-11-16
[^b9-27]: #20482 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=image+optimizer+pricing>, retrieved 2026-11-16
[^b9-28]: #11955 WordPress.org support thread, <https://wordpress.org/support/topic/before-switch-from-imagify-to-elementor-image-option/>, retrieved 2026-11-16
[^b9-29]: #11960 WordPress.org support thread, <https://wordpress.org/support/topic/restore-original-image-not-working/>, retrieved 2026-11-16
[^b9-30]: #11965 WordPress.org review, <https://wordpress.org/support/topic/it-works-for-some/>, retrieved 2026-11-16
[^b9-31]: #11972 WordPress.org review, <https://wordpress.org/support/topic/cheated-by-this-company/>, retrieved 2026-11-16
[^b9-32]: #708 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b9-33]: derived from 3 evidence records: #704, #705, #712
[^b9-34]: derived from 12 evidence records: #11942, #11943, #11967, #11969, #11970, #11972, #11974, #11978, #11980, #11981, #11982, #11983
[^b9-35]: derived from 3 evidence records: #701, #703, #20480
[^b9-36]: derived from 8 evidence records: #704, #705, #712, #11952, #11954, #11955, #11959, #11960
[^b9-37]: derived from 4 evidence records: #701, #11955, #11960, #20480
[^b9-38]: derived from 8 evidence records: #11965, #11970, #11972, #11983, #11987, #11989, #11992, #20482

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

<details><summary><b>10. Duplicate Page</b>, score 57.1</summary>

### Duplicate Page

<!-- meta: generated 2026-11-16T23:22:34+00:00; entity id 17; Orphan Radar brief -->

Score **57.1[^b10-4]** of cfg:100 · signals: displacement, pain

#### 1. Summary

Duplicate Page on WordPress.org plugin directory has 3,000,000[^b10-1] users, was last updated 2026-09-08[^b10-2], and shows displacement, pain; its users' most common fixable complaint is “stopped doing its core job on many sites or setups”[^b10-3].

#### 2. What happened

- **Abandonment** (weak):
  - months since last update: last updated 2026-09-08[^b10-2]; 2[^b10-2] months ago
  - recent support threads with zero replies: 3[^b10-5] recent threads with no reply
  - WordPress releases behind the current version (WordPress.org shows a warning from three): tested up to WordPress 6.9.11[^b10-6]; current WordPress is 7.1.4[^b10-7]; 2[^b10-8] major releases behind
- **Displacement event** (present):
  - sunset mentioned: sunset[^b10-9]; in 2[^b10-9] records; latest dated mention 2026-08-03[^b10-10]
- **Pain density** (present):
  - recent complaints (low-star reviews, negative threads, issues): 13[^b10-11] complaints in the last twelve months
  - recent rating below lifetime rating: lifetime rating 4.8[^b10-12] stars; recent rating 4.27[^b10-13] stars

Dated sources for the events:
- “Abandoned?. Hi – Shield Security is stating that this plugin is abandoned. Is that correct? I hope not because it’s a very useful plugin. Thank you!” — [WordPress.org support thread](https://wordpress.org/support/topic/abandoned-215/)[^b10-10], 2026-08-03[^b10-10]
- “Deprecated Gutenberg APIs used by Duplicate Page on WordPress 6.6+. Hello, While testing Duplicate Page on a WordPress Multisite production environment running …” — [WordPress.org support thread](https://wordpress.org/support/topic/deprecated-gutenberg-apis-used-by-duplicate-page-on-wordpress-6-6/)[^b10-14], 2026-06-27[^b10-14]

#### 3. Stranded users

- 3,000,000[^b10-1] users on WordPress.org plugin directory (<https://wordpress.org/plugins/duplicate-page/>), read from WordPress.org on 2026-11-16[^b10-1]
- 60,000[^b10-15] users on WordPress.org plugin directory (<https://wordpress.org/plugins/wp-duplicate-page/>), read from WordPress.org on 2026-11-16[^b10-15]

#### 4. Top complaints

**Stopped doing its core job on many sites or setups** (4[^b10-3] complaints)
> “Duplicate not working on some pages. Hi, I’m using the plugin, and it works most of the time. But on a few pages, the duplicate option doesn’t seem to create a proper copy. Not sure if it’s a setting or something else. …” — [WordPress.org support thread](https://wordpress.org/support/topic/duplicate-not-working-on-some-pages/)[^b10-16], 2026-04-13[^b10-16]
>
> “Update Not Working with Elementor. Hi! The Version 4.5.8 is not working with Elementor there is a bug. Where can we download the older version 4.5.7 ….the updated one is parsing the pages and not duplicating them …” — [WordPress.org support thread](https://wordpress.org/support/topic/update-not-working-with-elementor/)[^b10-17], 2026-04-22[^b10-17]
>
> “Error with 4.5.8. Hi, I’m experiencing an issue after updating the Duplicate Page plugin from version 4.5.7 to 4.5.8. My site uses both Duplicate Page and the Sendify Campaign plugin. Since updating to 4.5.8, …” — [WordPress.org support thread](https://wordpress.org/support/topic/error-with-4-5-8/)[^b10-18], 2026-05-04[^b10-18]

**Crashes, errors and broken pages** (2[^b10-19] complaints)
> “Bug Report Version 4.5.8: Update Doesn’t Properly Clone Oxygen Builder Pages. Similar to Elementor, the page is duplicated in WordPress but the content of the Oxygen Builder pages are not cloned over. Please fix.” — [WordPress.org support thread](https://wordpress.org/support/topic/bug-report-version-4-5-8-update-doesnt-properly-clone-oxygen-builder-pages/)[^b10-20], 2026-04-22[^b10-20]
>
> “Bug Report: v4.5.8 Does Not Properly Duplicate Elementor Pages. Up to version 4.5, the Elementor page duplication feature was working as expected without any issues. However, after updating to version 4.5.8, the …” — [WordPress.org support thread](https://wordpress.org/support/topic/bug-report-v4-5-8-does-not-properly-duplicate-elementor-pages/)[^b10-21], 2026-04-22[^b10-21]

**Ads, tracking, or distrust of a new owner** (1[^b10-22] complaints)
> “Ads wording. I am using the plugin to create events using the Events Calendar. Upon duplicating an event and then going in to edit the following code has just recently appeared on each duplicated page. What is this …” — [WordPress.org support thread](https://wordpress.org/support/topic/ads-wording/)[^b10-22], 2026-07-24[^b10-22]

**Broken by a platform, browser or PHP update** (1[^b10-14] complaints)
> “Deprecated Gutenberg APIs used by Duplicate Page on WordPress 6.6+. Hello, While testing Duplicate Page on a WordPress Multisite production environment running WordPress 7.0, I noticed that the plugin still uses …” — [WordPress.org support thread](https://wordpress.org/support/topic/deprecated-gutenberg-apis-used-by-duplicate-page-on-wordpress-6-6/)[^b10-14], 2026-06-27[^b10-14]

**Slow, heavy or resource-hungry** (1[^b10-23] complaints)
> “Slows down my entire website. 1 star I’m not sure if it’s the latest update or what, but having this plugin enabled is SIGNIFICANTLY slowing down my WordPress response time – both in the admin panel, and rendering pages …” (1[^b10-23]★) — [WordPress.org review](https://wordpress.org/support/topic/slows-down-my-entire-website/)[^b10-23], 2026-05-06[^b10-23]

Plus 3[^b10-24] complaints too vague to cluster.

#### 5. Smallest replacement

Does the job the incumbent does today, as its listing describes it: “Duplicate Posts, Pages and Custom Posts easily using single click”[^b10-25]
- Does its core job reliably on today's sites and setups (fixes: stopped doing its core job on many sites or setups)[^b10-3]
- Stable core with error handling and a test suite (fixes: crashes, errors and broken pages)[^b10-19]
- No ads, no tracking, transparent ownership, open source (fixes: ads, tracking, or distrust of a new owner)[^b10-22]
- Works on the current WordPress release[^b10-8]
- Imports the incumbent's settings and data (see the switching wedge)

Nothing else. Anything not listed here is out of scope for the first release.

#### 6. Switching wedge

Formats named in the evidence: JSON[^b10-26], HTML[^b10-26].

What users say about import, export or migration:
- “Plugin and DIVI 5. When duplicating a page or post that uses the Divi Builder, the duplicated content becomes corrupted — random/garbled characters appear inside the content that …” — [WordPress.org support thread](https://wordpress.org/support/topic/plugin-and-divi-5/)[^b10-26], 2026-09-02[^b10-26]

A one-click import would need (to verify before building, not established by the evidence):
- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;
- the export format, if one exists, and a sample file;
- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped.

#### 7. Launch channel

- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/duplicate-page/>[^b10-25]
- List it on **WordPress.org plugin directory**, where the incumbent is: <https://wordpress.org/plugins/wp-duplicate-page/>[^b10-27]
- Replacement searches to target (Google autocomplete):
  - `duplicate page not showing in.canva`[^b10-28]
  - `notion duplicate page not working`[^b10-28]
  - `squarespace duplicate page not showing`[^b10-28]
  - `wordpress duplicate page not showing`[^b10-28]
  - `elementor duplicate page not showing`[^b10-28]
- Public threads where people asked for an alternative (links only):
  - [Is there a way to exclude specific meta fields?](https://wordpress.org/support/topic/is-there-a-way-to-exclude-specific-meta-fields/)[^b10-29]
  - [Bulk duplicate multiple pages at once?](https://wordpress.org/support/topic/bulk-duplicate-multiple-pages-at-once/)[^b10-30]
  - [Redirect after clone](https://wordpress.org/support/topic/redirect-after-clone/)[^b10-31]

#### 8. Price anchor

- Incumbent price: unknown. No evidence record states a price.
- Rivals' prices: unknown. No evidence record prices a rival.

#### 9. License and naming

- License: GPL-compatible (WordPress.org directory requirement)[^b10-32].
- Forking: Forking is permitted; the fork and anything distributed with it must stay under the GPL.
- Use a new name and new branding. Do not use “Duplicate Page”, its logo or its screenshots in the product name, listing or ads; mention it only to say what you import from or replace, where the marketplace allows that.

#### 10. Risks and reasons to skip

- The incumbent was updated recently (2026-09-08[^b10-2]): it may be recovering rather than abandoned.
- Nobody's autocomplete suggests searching for an alternative yet.
- Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.

#### 11. Confidence

| Claim | Confidence | Evidence |
|---|---|---|
| Size of the stranded audience | well evidenced (official listing figure) | [^b10-1] |
| Abandonment | thin | [^b10-33] |
| Displacement event | well evidenced | [^b10-9] |
| Top complaints | well evidenced | [^b10-34] |
| Replacement demand in search | checked, none found | [^b10-35] |
| Price anchor | unknown |  |
| Switching wedge (export/import) | unknown unless quoted above |  |

#### 12. Build prompt

```text
Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): Duplicate Page, listed on WordPress.org plugin directory.
What it does, in its own listing's words: “Duplicate Posts, Pages and Custom Posts easily using single click”[^b10-25]

Build the smallest product that fixes what its users complain about, and nothing else:
- Does its core job reliably on today's sites and setups (users of the incumbent complain: stopped doing its core job on many sites or setups)
- Stable core with error handling and a test suite (users of the incumbent complain: crashes, errors and broken pages)
- No ads, no tracking, transparent ownership, open source (users of the incumbent complain: ads, tracking, or distrust of a new owner)
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
| demand | 18.3[^b10-36] | cfg:25 | audience on a log scale; rating count; people search for '‹product› not working' / '‹product› pricing' |
| supply failure | 10.6[^b10-37] | cfg:25 | months since last update; recent issues/threads with no reply; last-year rating below lifetime rating; not tested with current platform releases; displacement event: sunset mentioned |
| pain specificity | 10.2[^b10-11] | cfg:15 | complaints fall into cfg:5 or fewer fixable problems; share covered; complaint volume |
| channel | 11[^b10-38] | cfg:15 | a replacement can be listed in the same marketplace; public threads asking for an alternative |
| willingness to pay | none | cfg:10 | nothing |
| timing | 7[^b10-10] | cfg:10 | recency of the latest displacement event |

#### Evidence

[^b10-1]: #188 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-2]: #11497 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bsearch%5D=backup&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-3]: derived from 4 evidence records: #12859, #12862, #12866, #12887
[^b10-4]: derived from 55 evidence records: #188, #189, #190, #192, #199, #11496, #11497, #12841, #12842, #12844, #12845, #12846, #12849, #12852, #12853, #12856, #12859, #12861, #12862, #12863, #12866, #12867, #12868, #12869, #12870, #12871, #12872, #12873, #12874, #12875, #12876, #12877, #12878, #12879, #12880, #12881, #12882, #12883, #12884, #12885, #12886, #12887, #12888, #12889, #12890, #12891, #12892, #12893, #12894, #12895, #12896, #12897, #20432, #20433, #20434
[^b10-5]: derived from 3 evidence records: #12841, #12844, #12845
[^b10-6]: #192 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-7]: #199 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
[^b10-8]: derived from 2 evidence records: #192, #199
[^b10-9]: derived from 2 evidence records: #12842, #12846
[^b10-10]: #12842 WordPress.org support thread, <https://wordpress.org/support/topic/abandoned-215/>, retrieved 2026-11-16
[^b10-11]: derived from 13 evidence records: #12842, #12844, #12845, #12846, #12853, #12859, #12861, #12862, #12863, #12866, #12867, #12884, #12887
[^b10-12]: #189 WordPress.org rating, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-13]: derived from 30 evidence records: #12868, #12869, #12870, #12871, #12872, #12873, #12874, #12875, #12876, #12877, #12878, #12879, #12880, #12881, #12882, #12883, #12884, #12885, #12886, #12887, #12888, #12889, #12890, #12891, #12892, #12893, #12894, #12895, #12896, #12897
[^b10-14]: #12846 WordPress.org support thread, <https://wordpress.org/support/topic/deprecated-gutenberg-apis-used-by-duplicate-page-on-wordpress-6-6/>, retrieved 2026-11-16
[^b10-15]: #11494 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bsearch%5D=backup&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
[^b10-16]: #12866 WordPress.org support thread, <https://wordpress.org/support/topic/duplicate-not-working-on-some-pages/>, retrieved 2026-11-16
[^b10-17]: #12862 WordPress.org support thread, <https://wordpress.org/support/topic/update-not-working-with-elementor/>, retrieved 2026-11-16
[^b10-18]: #12859 WordPress.org support thread, <https://wordpress.org/support/topic/error-with-4-5-8/>, retrieved 2026-11-16
[^b10-19]: derived from 2 evidence records: #12861, #12863
[^b10-20]: #12861 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-version-4-5-8-update-doesnt-properly-clone-oxygen-builder-pages/>, retrieved 2026-11-16
[^b10-21]: #12863 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-v4-5-8-does-not-properly-duplicate-elementor-pages/>, retrieved 2026-11-16
[^b10-22]: #12844 WordPress.org support thread, <https://wordpress.org/support/topic/ads-wording/>, retrieved 2026-11-16
[^b10-23]: #12884 WordPress.org review, <https://wordpress.org/support/topic/slows-down-my-entire-website/>, retrieved 2026-11-16
[^b10-24]: derived from 3 evidence records: #12845, #12853, #12867
[^b10-25]: #13464 WordPress.org description, <https://wordpress.org/plugins/duplicate-page/>, retrieved 2026-11-16
[^b10-26]: #12840 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-and-divi-5/>, retrieved 2026-11-16
[^b10-27]: #14436 WordPress.org description, <https://wordpress.org/plugins/wp-duplicate-page/>, retrieved 2026-11-16
[^b10-28]: #20433 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=duplicate+page+not+working>, retrieved 2026-11-16
[^b10-29]: #12849 WordPress.org support thread, <https://wordpress.org/support/topic/is-there-a-way-to-exclude-specific-meta-fields/>, retrieved 2026-11-16
[^b10-30]: #12852 WordPress.org support thread, <https://wordpress.org/support/topic/bulk-duplicate-multiple-pages-at-once/>, retrieved 2026-11-16
[^b10-31]: #12856 WordPress.org support thread, <https://wordpress.org/support/topic/redirect-after-clone/>, retrieved 2026-11-16
[^b10-32]: #195 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
[^b10-33]: derived from 6 evidence records: #192, #199, #11497, #12841, #12844, #12845
[^b10-34]: derived from 10 evidence records: #12842, #12844, #12846, #12859, #12861, #12862, #12863, #12866, #12884, #12887
[^b10-35]: #20432 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=duplicate+page+alternative>, retrieved 2026-11-16
[^b10-36]: derived from 4 evidence records: #188, #190, #11496, #20433
[^b10-37]: derived from 39 evidence records: #189, #192, #199, #11497, #12841, #12842, #12844, #12845, #12846, #12868, #12869, #12870, #12871, #12872, #12873, #12874, #12875, #12876, #12877, #12878, #12879, #12880, #12881, #12882, #12883, #12884, #12885, #12886, #12887, #12888, #12889, #12890, #12891, #12892, #12893, #12894, #12895, #12896, #12897
[^b10-38]: derived from 5 evidence records: #188, #12849, #12852, #12856, #20432

##### Evidence index

- #188 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #189 WordPress.org rating, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #190 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #192 WordPress.org tested_up_to, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bbrowse%5D=popular&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #195 WordPress.org license, <https://developer.wordpress.org/plugins/wordpress-org/detailed-plugin-guidelines/>, retrieved 2026-11-16
- #199 WordPress.org platform_current_version, <https://api.wordpress.org/core/version-check/1.7/>, retrieved 2026-11-16
- #11494 WordPress.org user_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bsearch%5D=backup&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #11496 WordPress.org rating_count, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bsearch%5D=backup&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #11497 WordPress.org last_updated, <https://api.wordpress.org/plugins/info/1.2/?action=query_plugins&request%5Bper_page%5D=100&request%5Bsearch%5D=backup&request%5Bpage%5D=1&request%5Bfields%5D%5Bdescription%5D=0&request%5Bfields%5D%5Bsections%5D=0&request%5Bfields%5D%5Bicons%5D=0&request%5Bfields%5D%5Bbanners%5D=0&request%5Bfields%5D%5Bscreenshots%5D=0&request%5Bfields%5D%5Bversions%5D=0&request%5Bfields%5D%5Bcontributors%5D=0&request%5Bfields%5D%5Bbusiness_model%5D=1&request%5Bfields%5D%5Bshort_description%5D=1&request%5Bfields%5D%5Btags%5D=1&request%5Bfields%5D%5Bratings%5D=1>, retrieved 2026-11-16
- #12840 WordPress.org support thread, <https://wordpress.org/support/topic/plugin-and-divi-5/>, retrieved 2026-11-16
- #12841 WordPress.org support thread, <https://wordpress.org/support/topic/duplicate-post-issue-on-acf-fields/>, retrieved 2026-11-16
- #12842 WordPress.org support thread, <https://wordpress.org/support/topic/abandoned-215/>, retrieved 2026-11-16
- #12844 WordPress.org support thread, <https://wordpress.org/support/topic/ads-wording/>, retrieved 2026-11-16
- #12845 WordPress.org support thread, <https://wordpress.org/support/topic/latest-release-not-tagged-in-git/>, retrieved 2026-11-16
- #12846 WordPress.org support thread, <https://wordpress.org/support/topic/deprecated-gutenberg-apis-used-by-duplicate-page-on-wordpress-6-6/>, retrieved 2026-11-16
- #12849 WordPress.org support thread, <https://wordpress.org/support/topic/is-there-a-way-to-exclude-specific-meta-fields/>, retrieved 2026-11-16
- #12852 WordPress.org support thread, <https://wordpress.org/support/topic/bulk-duplicate-multiple-pages-at-once/>, retrieved 2026-11-16
- #12853 WordPress.org support thread, <https://wordpress.org/support/topic/missing-svn-tags-for-recent-versions-4-5-9-causing-composer-install/>, retrieved 2026-11-16
- #12856 WordPress.org support thread, <https://wordpress.org/support/topic/redirect-after-clone/>, retrieved 2026-11-16
- #12859 WordPress.org support thread, <https://wordpress.org/support/topic/error-with-4-5-8/>, retrieved 2026-11-16
- #12861 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-version-4-5-8-update-doesnt-properly-clone-oxygen-builder-pages/>, retrieved 2026-11-16
- #12862 WordPress.org support thread, <https://wordpress.org/support/topic/update-not-working-with-elementor/>, retrieved 2026-11-16
- #12863 WordPress.org support thread, <https://wordpress.org/support/topic/bug-report-v4-5-8-does-not-properly-duplicate-elementor-pages/>, retrieved 2026-11-16
- #12866 WordPress.org support thread, <https://wordpress.org/support/topic/duplicate-not-working-on-some-pages/>, retrieved 2026-11-16
- #12867 WordPress.org support thread, <https://wordpress.org/support/topic/duplicate-option-missing/>, retrieved 2026-11-16
- #12868 WordPress.org review, <https://wordpress.org/support/topic/perfect-tool-168/>, retrieved 2026-11-16
- #12869 WordPress.org review, <https://wordpress.org/support/topic/excellent-plugin-10001/>, retrieved 2026-11-16
- #12870 WordPress.org review, <https://wordpress.org/support/topic/a-must-have-plugin-427/>, retrieved 2026-11-16
- #12871 WordPress.org review, <https://wordpress.org/support/topic/lauft-prima-2/>, retrieved 2026-11-16
- #12872 WordPress.org review, <https://wordpress.org/support/topic/recommended-must-have-wordpress-plugin/>, retrieved 2026-11-16
- #12873 WordPress.org review, <https://wordpress.org/support/topic/real-time-saver-32/>, retrieved 2026-11-16
- #12874 WordPress.org review, <https://wordpress.org/support/topic/huge-time-saver-117/>, retrieved 2026-11-16
- #12875 WordPress.org review, <https://wordpress.org/support/topic/works-exactly-as-it-should-20/>, retrieved 2026-11-16
- #12876 WordPress.org review, <https://wordpress.org/support/topic/really-helpful-227/>, retrieved 2026-11-16
- #12877 WordPress.org review, <https://wordpress.org/support/topic/super-handy-imo/>, retrieved 2026-11-16
- #12878 WordPress.org review, <https://wordpress.org/support/topic/does-the-job-1094/>, retrieved 2026-11-16
- #12879 WordPress.org review, <https://wordpress.org/support/topic/no-brainer-tbh/>, retrieved 2026-11-16
- #12880 WordPress.org review, <https://wordpress.org/support/topic/simple-page-cloner/>, retrieved 2026-11-16
- #12881 WordPress.org review, <https://wordpress.org/support/topic/duplicate-18/>, retrieved 2026-11-16
- #12882 WordPress.org review, <https://wordpress.org/support/topic/works-like-magic-75/>, retrieved 2026-11-16
- #12883 WordPress.org review, <https://wordpress.org/support/topic/it-does-one-thing/>, retrieved 2026-11-16
- #12884 WordPress.org review, <https://wordpress.org/support/topic/slows-down-my-entire-website/>, retrieved 2026-11-16
- #12885 WordPress.org review, <https://wordpress.org/support/topic/great-17113/>, retrieved 2026-11-16
- #12886 WordPress.org review, <https://wordpress.org/support/topic/super-handy-54/>, retrieved 2026-11-16
- #12887 WordPress.org review, <https://wordpress.org/support/topic/not-working-properly-with-elementor-4-04/>, retrieved 2026-11-16
- #12888 WordPress.org review, <https://wordpress.org/support/topic/simple-but-basic/>, retrieved 2026-11-16
- #12889 WordPress.org review, <https://wordpress.org/support/topic/quick-copy-tool/>, retrieved 2026-11-16
- #12890 WordPress.org review, <https://wordpress.org/support/topic/good-for-simple-use/>, retrieved 2026-11-16
- #12891 WordPress.org review, <https://wordpress.org/support/topic/absolutely-useful-12/>, retrieved 2026-11-16
- #12892 WordPress.org review, <https://wordpress.org/support/topic/helpful-but-basic/>, retrieved 2026-11-16
- #12893 WordPress.org review, <https://wordpress.org/support/topic/time-saver-plugin-14/>, retrieved 2026-11-16
- #12894 WordPress.org review, <https://wordpress.org/support/topic/perfect-for-quick-duplicates/>, retrieved 2026-11-16
- #12895 WordPress.org review, <https://wordpress.org/support/topic/helpful-494/>, retrieved 2026-11-16
- #12896 WordPress.org review, <https://wordpress.org/support/topic/works-perfectly-2920/>, retrieved 2026-11-16
- #12897 WordPress.org review, <https://wordpress.org/support/topic/what-we-need-3/>, retrieved 2026-11-16
- #13464 WordPress.org description, <https://wordpress.org/plugins/duplicate-page/>, retrieved 2026-11-16
- #14436 WordPress.org description, <https://wordpress.org/plugins/wp-duplicate-page/>, retrieved 2026-11-16
- #20432 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=duplicate+page+alternative>, retrieved 2026-11-16
- #20433 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=duplicate+page+not+working>, retrieved 2026-11-16
- #20434 Google autocomplete search suggestions, <https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q=duplicate+page+pricing>, retrieved 2026-11-16

</details>

<!-- TOP10:END -->
