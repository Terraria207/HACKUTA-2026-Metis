# Metis

A server-backed mathematical connection explorer with isolated journeys, versioned modules, durable jobs and a responsive browser workspace. Implemented from `docs/metis-overview.txt` with the accepted corrections in `docs/implementation-review.md`. The review and acceptance documents are parent-owned and unchanged.

**The default is a clearly labeled, zero-cost fixture simulation. It is not real mathematical discovery.** Live mode uses MongoDB, actual provider HTTP adapters, and Atlas Vector Search. Missing credentials, unknown prices, zero budgets, or unavailable proof infrastructure stop the relevant operation; none silently falls back to a simulated success.

## Run locally

Requires Python 3.12+ (tested with 3.12.3). Node 18+ is optional, for the JavaScript syntax check. No frontend build, CDN, npm dependency, cloud account or model key is needed for fixture mode.

```bash
cd /workspace
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn metis.main:app --host 127.0.0.1 --port 8000 --workers 1
```

If `venv`/pip is unavailable and `uv` is installed:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.lock
.venv/bin/uvicorn metis.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open **http://127.0.0.1:8000**. Create a journey, choose islands, add a named **Fixture sample**, confirm its MSC group, and start a run. The report's scripted associations remain **Unchecked**; fixture mode never marks them potentially new or machine verified. Explore the graph, evidence, before/after snapshots, history, wrong-feedback re-review and all three exports. SQLite data survives restarts in `.metis/fixture.sqlite`; use `METIS_SQLITE_PATH` to change it.

In Aether, start the long-running command through an Aether managed terminal, following `aether-internal skill terminal`. Do not use shell backgrounding. The initial build hit a scheduler failure; a separate validation session subsequently started managed terminals successfully (see verification below).

Optional container startup (does not create a hosted Site):

```bash
docker compose up --build metis
```

Compose binds the app to loopback, persists fixture data in a volume, drops capabilities and uses a read-only root filesystem. No Docker socket is mounted into the app. The image and compose configuration have not been built/run in this environment.

## Verification

```bash
.venv/bin/python -m pytest -q
node --check web/app.js
.venv/bin/python -m compileall -q metis scripts
```

The tests cover hyperedge AND versus alternative OR routes, direction/equivalence, cycles, quarantine, typed proof semantics, distance/scoring, full fixture API journeys, paper uploads, exports, restart recovery, checkpoint replay, isolation, blinded payloads, wrong-feedback jobs, atomic reservations, expired leases, cancellation, no-call defaults, URL/DNS safety and conservative Lean failure paths.

An optional actual MongoDB integration test uses a randomly named temporary database and deletes only that database:

```bash
METIS_TEST_MONGODB_URI='mongodb://127.0.0.1:27017' .venv/bin/python -m pytest -q -m mongo
```

Initial build validation had no managed terminal/browser or compiler access. A separate Aether validation session on 2026-11-15 successfully started the app in a managed terminal, exercised the fixture browser journey, and prepared the pinned Lean project. See the independent browser/sandbox validation notes below for exact results. MongoDB, Atlas and paid provider integrations remain untested; no credentials or paid APIs were used.

## Live MongoDB and providers

Copy `.env.example` to `.env`, keep it out of version control, and export it into the server environment. The application does not implicitly load dotenv files.

```bash
set -a
. ./.env
set +a
.venv/bin/uvicorn metis.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Set `METIS_MODE=live` and `MONGODB_URI` to an Atlas or local MongoDB URI. Live startup pings MongoDB and installs indexes, including unique layer/type/endpoint edge identities and durable job/call IDs. Startup fails if MongoDB is missing/unreachable. It does not seed fixture modules or use SQLite. The optional `local-mongo` compose profile provides MongoDB 8.0.4; it is not Atlas and does not supply Vector Search.

For Atlas, prefer the free tier with a small corpus and a connection pool limited to 10. The $50 database credit allowance is **not** a model budget or an application-enforced Atlas billing cap. The app never provisions/upgrades cloud resources. Configure Atlas access rules, billing controls and usage alerts in your Atlas account. Monitor database/index size, since papers, source excerpts, snapshots and traces consume storage. No automated retention/deletion runs against scientific records.

Before any paid call:

1. Copy `deploy/providers.example.json` to a private **writable** server path and set `METIS_PROVIDERS_FILE` to it. Replace placeholder model IDs with models actually available to your accounts; the speculative roster in the overview is not treated as verified provider availability.
2. Put API keys in server environment variables named by each role's `key_env`. The settings API never accepts or returns actual keys. For externally reachable deployments, set a strong `METIS_API_TOKEN` and use the browser's **API access token** button (session storage only), TLS and a private network or authenticated reverse proxy. This is a single-user application, not a multi-tenant authentication system.
3. Set `METIS_ALLOW_LIVE=true`, an explicit `METIS_LIVE_BUDGET_USD`, the journey's `budget_usd` and the input run budget. All default to **zero**. Resume can raise a run's cap; journey settings can raise its cap. Changing the global cap requires server configuration/restart.
4. For every role configure a positive `max_cost_usd` and known `input_usd_per_million` / `output_usd_per_million` prices. Grounded literature calls additionally need `request_overhead_usd`. The app uses a conservative UTF-8-byte input bound plus framing allowance and configured output limit, and refuses estimates above the configured maximum. Supply conservative provider prices including search/tool charges. This is protective accounting, **not a guarantee about provider invoices or an external billing cap**.

Adapters support OpenAI chat completions, Anthropic Messages, Gemini generateContent with Google Search grounding, Mistral/xAI/NVIDIA OpenAI-compatible chat endpoints, and Voyage embeddings. Hosts are fixed in server code, not supplied by papers or API callers. Each review, hypothesis check, proof alignment check, crew comparison and research request has a fresh context. Penelope never receives provenance, model, perspective or support count. Configure independent model families for the hypothesis checker and reviewer.

Every call reserves its maximum charge against global, journey and run accounts **before** making a network request. Atomic account updates prevent simultaneous calls from overspending a cap. Partial reservations are rolled back when another cap fails. Completed calls are cached by idempotency key. Ambiguous/failed calls conservatively retain their maximum charge; retries require fresh reservations. A crash between reservation and call storage can retain an unused reservation: reconcile against the provider ledger before any administrative release. The UI shows maximum-charge accounting, not invented exact billing.

Live API calls were not made during this build, and no paid resource was created.

## Modules and Atlas vectors

Live mode needs reviewed base modules before journeys can be created. The default three islands are linear algebra (15/15A/15A03), graph theory (05/05C/05C50) and probability (60/60B/60B20). Fixture MSC paths are deliberately a tiny illustrative subset, not the full MSC taxonomy or a curated mathematical corpus.

Import an immutable module bundle with `POST /api/modules/import` or:

```bash
PYTHONPATH=. .venv/bin/python scripts/import_module.py path/to/module.json
```

Bundle schema: `module:{id,name,version,islands,mathlib_version,source,fixture:false}`, `groups:[{id,name,msc,depth,parent,ancestors,island,description}]`, `concepts:[{id,name,statement,description,kind,home_group,island,source,embedding}]`, `edges:[{id,premises,conclusion,directed,type,tier,argument,evidence}]`. IDs must be globally unique (prefix with module ID/version). Ancestry begins at the island, includes the home group, and has length equal to depth. Published versions are immutable; a new version needs new IDs. Bridge bundles may use `module.requires:[islandModuleId,...]` and reference those modules' existing groups/concepts without copying them. Journeys pin selected module IDs. The API supports explicit module selection, including versioned multi-island bridge bundles. Ready compatible bridge modules are included automatically when using default module selection.

Import never mints `verified` inference edges. A cited inference needs an explicitly reviewed source and location. Compiler dependencies are stored as **dependency metadata**, not inference. `scripts/import_mathlib.py --help` converts a supplied declaration/dependency JSON export plus reviewed MSC mapping into such a bundle. It retains the complete formal type, including hypotheses, and only creates dependency relations. It is not a bundled mathlib extractor or a claim that the declarations have been locally recompiled/axiom-audited. Curating real module mappings, citations and declaration exports is required before scientific use.

For real matching, configure the Voyage embedding role and Atlas Vector Search indexes named `metis_concepts` and `metis_groups` (names can be overridden by `METIS_ATLAS_CONCEPTS_INDEX`, `METIS_ATLAS_GROUPS_INDEX`). `deploy/atlas-vector-index.json` is an explicit-vector index definition with a layer filter; choose the dimension matching your configured embedding model. Base concepts/groups must already carry vectors generated with the **same** model. New paper concept vectors are generated through the budgeted Voyage adapter. This implementation uses explicit Voyage embeddings rather than provisioning Atlas Automated Embedding. Failed/missing vector services fail the live stage; lexical fixture search is labeled separately.

## Mathematical trust model

- Typed, directed hyperedges preserve all premises. One hyperedge means AND; separate edges are alternative routes. Only `implies` and bidirectional `equivalent` are traversed as proof steps. Definition, generalization, special-case, related and dependency relations never imply a theorem merely by traversal.
- `Proposed` nodes and invalidated claims are excluded from proof reachability, distance and bridge scores. Inference validity requires a separate independent hypothesis/necessity/counterexample result plus blinded Penelope review. These remain model judgments, never mathematical guarantees.
- Distance ignores direction, uses only accepted cited/verified non-dependency relations, treats each premise as adjacent to the conclusion, caps disconnected pairs at `D_max` and excludes the candidate edge. Similarity is cosine with negative values clipped to zero. Scores use the strongest premise/conclusion pair; unintegrated concepts use tree distance alone. Unavailable embeddings produce an unavailable score rather than fabricated similarity.
- Input integration is reviewed before crew exploration. Extraction is globally content/schema/model keyed; matching, placement, integration and reviews happen within each journey's pinned graph. An isolated component of new paper nodes is not considered integrated merely because those nodes connect to each other.
- Cited evidence is **literature supported**, not machine verified. Before live citation review, source text is retrieved through the safe fetcher (or taken from the actual input paper), the excerpt must occur in that text, and the reviewer receives surrounding source context. Retrieval failure downgrades support. Human-reviewed module imports remain an explicit curator trust boundary.
- `Not found` means **potentially new in the recorded completed searches**, never proven novelty. Grounded queries, sources, timestamps and failures are stored. Incomplete/failed/ungrounded search remains `Unchecked`. Cited edges are Existing only after source review; a literature hit still needs a separate cited review before tier promotion.
- The reachability inspector gives a proof DAG of accepted edges from explicit assumptions, with its supporting edge IDs. Even a DAG of individually verified steps is labeled **composition unverified**; it is not silently promoted to a compiled Lean theorem. Definitions are never marked Proven.
- Rejected counterexamples survive as structured invalidation signals. Wrong feedback immediately removes a claim from valid reasoning and queues independent re-review. Declared dependent proof edges are recursively invalidated; restoring the original claim does not automatically restore its dependents. Journey overlays invalidate shared base claims without mutating base documents.
- Odysseus records recurrent cross-run island-pair patterns. A pattern threshold can trigger a quarantined definition/conjecture proposal, strict review, grounded concept search, and fresh blinded crew tests. Acceptance needs independently reviewed edges from the configured number of distinct crew mates and no counterexample. Found concepts become sourced rediscoveries. These nodes/edges are kept out of Odysseus's ranking. Optional definition formalization is available with journey setting `formalize_definitions=true`. After blind testing, the prover submits a type and value, a separate alignment reviewer checks the definition, and the controlled Lean sandbox type-checks it. Unavailable/failed checks keep the concept quarantined. A type-checked definition is never labeled machine verified or Proven.

## Controlled Lean runner

No compiler installed/configured means **verification unavailable**. A cited argument, a model's assertion, an imported declaration or a fixture never sets machine verification.

To opt in, provision an immutable Docker image with Lean/lake and a trusted, prebuilt, pinned mathlib project. Set `METIS_LEAN_IMAGE` to an `image@sha256:<64 hex digest>` and `METIS_LEAN_PROJECT` to its absolute host path. The project must contain `lean-toolchain`, `lake-manifest.json` and `METIS_MATHLIB_VERSION`; that marker must exactly match the version shared by the journey's modules. Build/download tools yourself outside Metis; the runner never pulls an image or accesses the network.

The prover submits only statement/proof expressions. An independent model must approve exact statement alignment, including every hypothesis. The runner rejects placeholders, added axioms, unsafe code, metaprogramming, command syntax and comments, and generates one controlled declaration. Docker runs as UID 65534 with no network, no capabilities, read-only mounts/root, no privilege escalation, 2 GiB RAM, one CPU, 64 PIDs and a 35-second timeout. It audits `#print axioms metis_result`; only `propext`, `Classical.choice` and `Quot.sound` are allowed. The compiled source hash, image digest, toolchain, mathlib version, alignment review and axiom output are retained. Any unavailable sandbox, timeout, failed compilation or unapproved axiom leaves the edge unverified.

Do not mount the host Docker socket into the web container. For this prototype, optional compilation is available when running the backend on a controlled trusted host with Docker access. A production deployment should isolate the proof worker on a separate host/service. The application container deliberately does not enable that infrastructure by default. See the independent browser/sandbox validation notes below for the actual controlled Docker test result.

## Durable workflow and inputs

The seven stages are decomposition/integration, target draws, crew exploration, independent proof review, formal attempts, literature search, ranking/memory. Stage outputs, traces, reviews, source snapshots, support, before-graphs, budgets and checkpoints persist. Jobs use expiring leases, heartbeat renewal, ownership-fenced completion, stable output IDs and startup reconciliation. Change streams are **not** relied on as a job queue. Durable event records drive SSE; reconnection accepts `Last-Event-ID`, and the browser also polls persisted state.

Pause prevents new provider calls; an in-flight request may finish and still incurs its reserved charge. Cancellation remains terminal even if a late response arrives. The current stage can be replayed from cached successful calls and stable graph/support IDs. Retry after ambiguous failure is explicit if automatic transient retries are exhausted. Failed stages expose error summaries and a Retry control. Feedback re-review is a separate operation with a zero default budget; History can retry failed reviews using the displayed run-budget input as its explicit cap. It can review a claim from a cancelled run, without resuming that run. Base-edge re-review downgrades are journey overlays and never mutate shared modules. One active exploration per journey is enforced with a durable lock. Use one API process as supplied; MongoDB leasing is implemented, but multiple-process race/failover stress testing remains outstanding.

Input supports bounded PDF upload, public URL, arXiv ID, pasted text, existing corpus paper ID and up to 20 bulk arXiv IDs or stored-corpus papers matching an MSC field/subfield/subtopic. MSC import deduplicates content already in the destination journey and does not fetch external papers or call models. Confirm the home MSC group before starting; the workspace can apply the selected MSC group to an imported input paper before extraction. **Add to journey stores the paper without paid extraction.** Use **Extract corpus only** for durable reviewed decomposition without crew exploration, or **Start run** for the whole pipeline. This makes spending explicit; it differs from automatically decomposing every paper at initial import. The extraction cache is global, while graph integration remains local.

URLs only allow public HTTP(S), ports 80/443, no userinfo, and public IPs for every DNS answer. Connections pin a vetted numeric IP while HTTPS verifies the original hostname; every redirect is checked again. No environment proxies, ambient cookies or arbitrary model endpoints are used. Mutating request bodies, including chunked multipart uploads, are capped before parsing at 12 MiB plus 1,000,000 bytes of framing and a 30-second body deadline. Fetch size is 12 MiB, redirects at most four, socket timeout 20 seconds, with a 40-second checked download deadline that stops slow body trickles (an in-flight socket operation may take up to its timeout). PDF parsing runs in a separate spawned process with 8 CPU seconds, 512 MiB address space and a 12-second wall timeout. Scanned PDFs require external OCR; JavaScript-only/paywalled sources may not yield usable text. Bulk network import is synchronous and bounded, with per-item errors.

## Current limitations / remaining work

This is an independently reviewable implementation, **not a fully validated scientific discovery system**. In addition to the unperformed live MongoDB/Atlas/provider tests:

- No bundled, licensed, scientifically curated full mathlib/MSC/textbook corpus. The module converter needs an external declaration export and reviewed namespace/MSC mapping. Bridge bundles can refer to concepts in explicit pinned `module.requires` versions; journeys reject mismatched prerequisites.
- No automatic Atlas index/embedding provisioning or change-stream consumer. Durable polling/SSE and explicit Voyage vectors are the implemented alternatives. Atlas real matching must be acceptance-tested with a populated, correctly indexed corpus.
- Graph search supports lexical search and explicit budgeted meaning search through Voyage/Atlas; fixture meaning search is explicitly lexical. Suggested next papers are corpus papers near the latest bridge groups, rather than external recommendations. MSC-category bulk import scans the stored corpus only (at most 20 unique papers), preserves matching MSC placement in the selected modules, and reports unsupported placements. External MSC discovery is not implemented; bounded arXiv-ID import retrieves external papers.
- No automatic OCR, deep citation bibliography resolver, exact formal proof composition, or automatic external MSC harvesting. Human review of statement alignment and source quality is still required for scientific trust, even when model reviews pass.
- Pattern triggers group edges by island pair across different runs, which is a heuristic; recognizing a genuinely shared missing idea still depends on the proposer/reviewer. Blind concept acceptance exists but has not been exercised against live models.
- PDF uses the bundled ReportLab Vera font; some advanced mathematical Unicode glyphs may not render. JSON/Markdown preserve exact Unicode and complete structured evidence. PDF is a reading export, not the canonical mathematical archive.
- No accounts, multi-user authorization, distributed stress test, automated retention policy, operational metrics stack or managed hosted deployment. Keep single-user/local or behind a private authenticated TLS proxy. Source retrieval and parsing are bounded but this prototype is not a hardened hostile-document service.

Review live adapters against provider account/model contracts before setting any nonzero budget. Fixture success must never be used to assert real integration success.


## Independent repair verification

The follow-up review added regression coverage for completed-call reuse across manual retries (including successful earlier retries), review-save/graph-write crash recovery, lock ownership during startup, reservations across separate SQLite connections, invalidated endpoints in reports/exports/discoveries, candidate-excluded integration scoring, preservation of audited formal tiers during citation promotion, conservative concept acceptance, bounded corpus MSC import, slow-download deadlines, definition type-check labels, module-tree ancestry validation, and chunked request limits. The repair suite passes **74 tests** with **1 Mongo integration test skipped**; JavaScript syntax and Python compilation checks pass. These are deterministic fixture/mock tests; they do not validate external MSC discovery, providers, Atlas or a real Lean compiler. No paid calls or cloud resources were used.

## Independent browser and Docker validation (2026-11-15)

Aether session `run-0yp2mh405b` successfully launched managed terminals and the
managed Chromium browser. The fixture journey `Browser validation` imported a
named fixture paper, started a run, paused after the first durable checkpoint,
resumed and completed all seven checkpoints. Report showed zero potentially new
connections, zero rediscoveries and two **Unchecked** scripted associations.
Graph displayed eight concepts and three relations; node inspection exposed the
fixture statement/provenance. History showed the completed run and 7/7 checkpoints.
JSON, Markdown and PDF export buttons were exercised. Independent HTTP reads saved
all three exports in `.metis/validation/` and verified 200 responses, valid JSON,
readable Markdown and a readable one-page PDF; the JSON export was 41,066 bytes,
Markdown 964 bytes and PDF 22,347 bytes. These files are session-local evidence,
not committed scientific records.

Three reviewed 1440×1000 viewport screenshots (report, graph, history) are retained
in Aether evidence packet `evid-hhq83ndrsg`: `a89c6790441acde74ec036380bb69b82`,
`a2e46bf43aaf4375e966c08c02efbb0e`, `ed72acb0204e0912116f384d6ab5a183`.
They show the fixture labels and rendered workspace, with lower page content
outside the viewport. Initial console inspection found only a missing favicon;
a local SVG icon fixes that request. After reload, the console had no new errors
and the managed browser's failed-network log was empty. Broker rate limiting
required pacing browser calls; this was a tool limitation, not an app failure.

The suite after the banner-parser regression test passes **79 tests, 2 skipped**
(the unconfigured MongoDB and opt-in Docker checks), with one upstream
Starlette/httpx deprecation warning. JavaScript syntax and Python compilation
checks also pass. The real Docker test is run separately with explicit settings.

`scripts/setup_lean.py /workspace/.metis/mathlib` exited 0 in a managed terminal,
checking the exact pinned Lean 4.19.0/mathlib commit and manifest, downloading
upstream caches and compiling all three small acceptance theorems. This direct
compiler result alone does not validate the sandbox. Docker 29.1.3 ran an offline
Ubuntu container. The image builder initially rejected Lean's actual comma-ended
version banner; the parser now accepts that banner while rejecting other versions.
The initial real sandbox test failed closed because the image lacked Git: Lake
interpreted a failed dependency URL lookup as a changed URL and attempted a
read-only dependency replacement. The image now includes Git and marks the
operator-provided read-only project repositories safe for its unprivileged UID.
Only the trusted project and generated input are mounted; no host Git config or
credentials are mounted. No paid APIs, provider credentials, Atlas or MongoDB were
used. The six-node cited number-theory module has no edges and remains a modest
source-backed seed, not a comprehensive scientific corpus.

The repaired real sandbox acceptance test **passed (1 test, 41.97 seconds total)**.
It compiled and axiom-audited `∀ n : ℕ, n + 0 = n`, failed `1 = (2 : ℕ)`, rejected
`by sorry`, and refused a mismatched mathlib version. It also asserted the exact
image/toolchain/mathlib metadata, source hash and allowed axioms. The former
768 MiB cap made a separate diagnostic import take 103 seconds with over 79,000
cgroup memory-limit events and no OOM kill. A bounded **2 GiB** cap allows the
real test to pass while retaining the 35-second per-invocation timeout and all
other isolation constraints. No compiler-direct result is substituted for this
test of `metis.formal.verify` and its actual Docker command.

Validated runtime reference (local to this session's Docker daemon):

```
METIS_TEST_LEAN_IMAGE=localhost:5000/metis-lean@sha256:18a528254da03131cf82609091c533a8f483259b0ca05937e32f230e560983f4
METIS_TEST_LEAN_PROJECT=/workspace/.metis/mathlib
```

The image was built from
`ubuntu@sha256:2198e4c65076e9cb0b3d695219df667c0e3b0072da64ca3c2648aca17dcecaf5`
and pushed only to a local registry bound to `127.0.0.1:5000`, with no registry
credentials or public publication. The immutable image must be rebuilt/preloaded
or transferred for another daemon; the session-local reference is not a public
deployment artifact. The Lean project/cache is about several GiB and intentionally
ignored by Git. Test logs are in `.metis/validation/lean-acceptance-memory-fixed.log`.

Final configured full-suite verification (same immutable image/project): **80
passed, 1 skipped, 1 warning in 19.05 seconds**. Only MongoDB integration skipped.
`node --check web/app.js`, `python -m compileall -q metis scripts` and
`git diff --check` passed. The real sandbox pass screenshot is retained in
`evid-q8dwjny960` (`5ce782d5cc8b08049e944fa1dbaf77d6`). No environment blocker
remains for these fixture/browser/Lean checks. Live providers, Atlas/MongoDB,
scientific coverage and distributed deployment remain outside this validation.
The combined five-capture reviewed evidence packet is `evid-wja3x7vphb` (the three
browser views, standalone real sandbox pass and final configured full-suite pass).

### Bounded parent-side live acceptance

`scripts.live_acceptance` makes **zero paid calls by default**. The private
`.metis/live.env` stays on the parent machine. Neither this implementation nor
its offline tests accessed it. Run from the repository root with the installed
Python environment. Copy `scripts/examples/live-plan.json` to
`.metis/live-plan.json`, set the local PDF path, and supply your own
`.metis/providers.json`. Every role must have explicit provider, model, key env
name, positive `max_cost_usd`, and known input/output prices per million tokens.
Roles are `decomposer`, `crew0`–`crew3`, `penelope`, `hypothesis`, `hephaestus`,
`tiresias`, `odysseus`, `alignment`, and `embeddings`. No model or price is guessed.
An individual role record looks like this (replace the placeholders and nulls):

```json
{
  "provider": "openai",
  "model": "PARENT_SELECTED_MODEL",
  "key_env": "OPENAI_API_KEY",
  "max_cost_usd": null,
  "max_output_tokens": 2048,
  "input_usd_per_million": null,
  "output_usd_per_million": null
}
```

Use OpenAI or Voyage for `embeddings` (1024 dimensions). `tiresias` requires
Gemini and an explicit `request_overhead_usd` bound for grounded search; include
all search charges in that bound. Maximum charges must cover the conservative
input/output estimate; failed or ambiguous requests retain their full charge.
The same durable `global` ledger covers setup, exploration and existing live
calls, capped at the configured amount and at $100. Use the same database for
all acceptance attempts. The example setup cap is $1 and run/journey cap is $5.
These are bounds, not projected costs or promises of completion.

```bash
python -m scripts.live_acceptance acceptance --config .metis/live-plan.json
python -m scripts.live_acceptance preflight --config .metis/live-plan.json --env-file .metis/live.env --execute
python -m scripts.live_acceptance acceptance --config .metis/live-plan.json --env-file .metis/live.env --execute
```

Offline validation reads the plan, explicit provider specifications and bundle;
it does not load the private env, connect to Atlas or call a provider. Executed
preflight connects to Atlas, checks credential presence and verifies both
`concepts` and `groups` indexes are queryable with 1024-dimensional cosine vectors
and a `layer` filter. It does not call model APIs. Index names can be overridden
with `METIS_ATLAS_CONCEPTS_INDEX` and `METIS_ATLAS_GROUPS_INDEX`.

Executed acceptance checks the local PDF, prepares the module, creates an actual
journey, imports the PDF through the application's upload endpoint, starts an
actual exploration run (not ingest-only), and drives the durable seven-stage
worker. JSON lines print module/journey/paper/run IDs, checkpoint, status, report
classification lists and the global ledger. Keep those IDs for UI inspection or
manual resume. Exit codes: 0 completed/preflight/offline-valid, 1 sanitized error,
2 paused/failed/incomplete. A new invocation creates a new journey and run; it
does not automatically resume a previous acceptance run. Deadline checks pause
between calls; an in-flight provider request has a 60-second HTTP timeout and a
stage is not forcibly killed. Financial caps apply before every request.
Stages without eligible edges can complete without proof or literature calls;
empty/rejected proposals are never reported as discoveries. Formal attempts are
zero in the example; configure bounded proof attempts and the pinned Lean
sandbox to exercise real formal compilation.

First-module setup uses a durable `operations` record of kind `module_setup`
and a `setup:<operation-id>` account, with no fake exploration journey/run.
Concepts **and groups** are embedded together. Successful embedding responses
are reused on retry, partial publication remains invisible until ready, and
published module documents cannot be edited or deleted through the store. An
identical ready module is reused; changed content needs a new module version.
After an ambiguous embedding failure, identical retries stop without rebilling.
Only explicitly incrementing `setup_attempt` (0–10) authorizes a new embedding
attempt under the same setup account; completed earlier attempts are reused.
Standalone preparation also accepts `--setup-budget` and `--setup-attempt`:

```bash
python -m scripts.private_env .metis/live.env python -m scripts.prepare_module corpus/number-theory.json --execute --setup-budget 1
```

The env loader parses literal `KEY=value` / `export KEY=value` lines with optional
whole-value quotes. It performs no shell expansion, substitution or shell
execution; it never prints values. Its command wrapper launches an argv directly.
The CLI suppresses exception bodies; provider failures store only exception
classes, never keys, Mongo URI, request headers or raw HTTP error responses.

### Atlas embedding key routing

Voyage requests default to `https://ai.mongodb.com/v1/embeddings`, matching keys
created in Atlas. For a direct Voyage account, set
`METIS_VOYAGE_API_HOST=api.voyageai.com`. Only those two fixed hosts are accepted;
arbitrary endpoint overrides are rejected. Geography-scoped keys require an
explicit future adapter extension. See MongoDB's [embedding API documentation](https://www.mongodb.com/docs/api/doc/atlas-embedding-and-reranking-api/).
