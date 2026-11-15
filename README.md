# Metis

A server-backed mathematical connection explorer with isolated journeys, versioned modules, durable jobs and a responsive browser workspace. Implemented from `docs/metis-overview.txt` with the accepted corrections in `docs/implementation-review.md`. The review and acceptance documents are parent-owned and unchanged. See **Plan alignment (2026-11-15)** below for the corrections made after comparing the repository against the overview.

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

Open **http://127.0.0.1:8000**. The title screen shows the METIS wordmark over a pixel-art beach with three scrolls. Unroll **New Journey**, pick basis groups (islands) and **Set sail**; on the sea map open the **Paper** bottle, add a named **Fixture sample**, confirm its MSC group, and start a run. The report's scripted associations remain **Unchecked**; fixture mode never marks them potentially new or machine verified. Explore the map, the simplified view (G), the Odyssey discussion, the route finder, evidence, before/after, history, wrong-feedback re-review and all three exports. The interface is described under **Interface (UI spec)** below. SQLite data survives restarts in `.metis/fixture.sqlite`; use `METIS_SQLITE_PATH` to change it.

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

The tests cover hyperedge AND versus alternative OR routes, direction/equivalence, cycles, quarantine, typed proof semantics, distance/scoring, full fixture API journeys, paper uploads, exports, restart recovery, checkpoint replay, isolation, blinded payloads, wrong-feedback jobs, atomic reservations, expired leases, cancellation, no-call defaults, URL/DNS safety, conservative Lean failure paths, and (`tests/test_plan_alignment.py`) the integration loop, Proven conjectures, ranking order, the key-discoveries feed, the gods curation path, bridge modules, automated-embedding routing and the vendored graph library.

An optional actual MongoDB integration test uses a randomly named temporary database and deletes only that database:

```bash
METIS_TEST_MONGODB_URI='mongodb://127.0.0.1:27017' .venv/bin/python -m pytest -q -m mongo
```

Initial build validation had no managed terminal/browser or compiler access. A separate Aether validation session on 2026-11-15 successfully started the app in a managed terminal, exercised the fixture browser journey, and prepared the pinned Lean project. See the independent browser/sandbox validation notes below for exact results. MongoDB, Atlas and paid provider integrations remain untested; no credentials or paid APIs were used.

## Interface (UI spec)

The interface follows `docs/metis-ui-spec.txt` (Metis — UI Spec, 2026-11-15), which restructures the design doc's four tabs into a title screen, a scroll transition and a sea map. No frontend build: `web/` holds plain scripts (`pixel.js` sprites and portraits, `title.js` the animated beach, `seamap.js` the island layout and renderer, `app.js` the flow and panels), the wordmark image (`web/art/metis-logo.png`, the supplied artwork at its true 170×70 pixel grid) and the vendored Cytoscape.js. Everything else is drawn in code on canvas at whole-number zoom.

- **Title screen**: pixel-art beach with drifting clouds and rolling waves, the METIS wordmark, and scrolls for **New Journey**, **Load Journey** and **Key Discoveries** (the spec's suggested third scroll), plus Settings. A scroll unrolls on hover, on a tap, or with the keyboard (← → move between scrolls, Enter unrolls or selects, Esc rolls it back up) and rolls back up when the mouse leaves unless a choice is in progress.
- **New Journey**: the scroll enlarges into the setup form: name (blank lists the journey by its creation date), basis groups marked **Ready** or **Needs building** with their saved versions and mathlib tag, a check mark or warning per model role, and the run settings under Advanced. **Set sail** is disabled until at least one group is chosen and, in live mode, every role has a model, a key and no failed key test. Bridge modules between the chosen islands are added automatically.
- **Needs building**: with `METIS_MATHLIB_EXPORT` set, a missing group is built before the journey starts and the scroll holds at full screen showing the stages and the island being inked. In fixture mode, and in live mode without a gods role or build budget, the build is the script-mapped one and says so; in live mode with the gods role it is curated and embedded within the build budget (see *Base modules from mathlib*).
- **Load Journey**: past journeys newest first, by name or creation date in the browser's time zone, with islands, papers run, new connections, last activity and status. Choosing one offers **Open journey** or **Open review document**; the review document lists the run reports newest first on the full-screen scroll with **Sail to the map**. A paused or failed run offers Resume when the journey opens.
- **Transition**: the scroll flies out from the menu, fills the screen and fades into the sea; a click or Esc skips it, and reduced-motion settings shorten it to nothing.
- **Sea map**: each basis group is an island whose area scales with its node count; subgroups are patches of different-coloured grass (a treemap of the MSC subfields and subtopics); a paper gets a flowered patch of its own in its primary MSC group; its concepts are Odyssey items and creatures chosen by a hash of the node id, so they look the same on every visit. Basis nodes are laid out but not drawn. A link on one island is a walker going premise → conclusion (both ways for an equivalence), with a campfire where a hyperedge's premises meet; a link between islands is a boat — trireme for verified, merchant ship for cited, raft for intuitive, with a bright sail for the latest run and a weathered one otherwise. Walkers are drawn only for links that touch a paper node or came from the crew. New items sparkle gold, unintegrated concepts have a dashed amber outline, proposed ones are faded. Zoom is in whole steps (½×, 1×, 2×, 3×, 4×, 6×, 8×) with wheel, pinch, + and −, drag to pan, Fit all, a minimap while zoomed in, more detail as you zoom, names on hover and details on click.
- **Simplified view** (button or G): every node as a dot coloured by status, edges solid/dashed/dotted by tier, hyperedges through a junction dot, groups as labeled regions. It uses the same world coordinates, so zoom, pan and selection carry over in both directions. Filters (tier, existing tag, island, run, new connections only, rejected, pending) and search by name or meaning apply in both views.
- **Paper input**: a message-in-a-bottle panel: PDF, arXiv ID, URL, text, a corpus paper or the fixture sample; MSC placement shown and correctable; bulk import; Start, Pause, Resume, Retry and Cancel; the seven steps with progress.
- **Odyssey discussion**: each agent's trace entry becomes a line spoken by its character with a pixel portrait, in order, advancing on a timer (three speeds) or a click, with Skip, Mute and a full log. A crew mate's proposals for one comparison are folded into one exchange. The narrator restyles wording only: verdicts, tiers, existing tags, names, citations and reviewer reasons are read from the stored records and shown beside the line, and a narrated line that mentions a status word its entry does not carry is replaced by the template. Fixture mode and any narrator failure use deterministic templates; narration never pauses or fails a run. Every line links to its trace entry and, where it concerns a node or edge, to its place on the map.
- **Route finder**: pick two concepts on the map or by search. *Proof route* uses verified and cited inference edges in their direction; a hyperedge needs every premise, so the route is a tree of steps, and a side premise that cannot be derived from the start is listed as an additional assumption (only a route without any is called a complete argument). *Any route* uses every accepted edge either way and is labeled a conjecture as strong as its weakest edge. The route is drawn on the map, Play sends a walker or ship along it with the camera following, and the formal view can be copied or exported as text. If no route exists under the chosen type, the finder says so.
- **Around the map**: Report (ranked report with links to the map, feedback, PDF/Markdown/JSON), Details side panel (statement, evidence, provenance, tier history, proof tree), History (runs, trace and report, before-and-after, suggested next papers), Trace (grouped by step, filters, Retry), Legend, cost counter, Settings and Return to title.
- **Settings**: API keys per provider, entered once, masked, reused by every journey; a model per role with roster defaults; **Test** makes one small budgeted call for that role in live mode and records the result. Model IDs are prefilled only where the provider's own documentation confirms them (Anthropic, Google, Voyage); `gpt-6.1-sol` and `grok-4-3` come from third-party listings and are marked unverified; Leanstral 1.5 and Nemotron 3 Ultra have no confirmed ID and must be entered.

Choices made on the spec's open questions, all easy to change: boats keep the proposed hull/sail mapping; walkers only on paper or crew links; one patch per paper at its primary MSC group (a concept on another island stands in its home group there); the decomposer and the gods speak under their role names with a scroll and a temple as portraits rather than a chosen character; characters are stable by hashing the node id; D_max stays 8 and Hephaestus's budget 3 proof attempts; keys are stored on the server.

**Keys.** Keys entered in Settings go to a private server file (`METIS_KEYS_FILE`, default `.metis/keys.json`, mode 0600, git-ignored) and are never returned by any endpoint; an environment variable of the same name wins. Because a key travels in the request body, the server accepts key writes only from the same machine, or from any client when `METIS_API_TOKEN` is set. Use TLS for anything that is not loopback.

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
2. Put API keys in server environment variables named by each role's `key_env`, or enter them in the Settings screen (see **Keys** above). No endpoint ever returns a key. For externally reachable deployments, set a strong `METIS_API_TOKEN` and use the browser's **API access token** button (session storage only), TLS and a private network or authenticated reverse proxy. This is a single-user application, not a multi-tenant authentication system.
3. Set `METIS_ALLOW_LIVE=true`, an explicit `METIS_LIVE_BUDGET_USD`, the journey's `budget_usd` and the input run budget. All default to **zero**. Resume can raise a run's cap; journey settings can raise its cap. Changing the global cap requires server configuration/restart.
4. For every role configure a positive `max_cost_usd` and known `input_usd_per_million` / `output_usd_per_million` prices. Grounded literature calls additionally need `request_overhead_usd`. The app uses a conservative UTF-8-byte input bound plus framing allowance and configured output limit, and refuses estimates above the configured maximum. Supply conservative provider prices including search/tool charges. This is protective accounting, **not a guarantee about provider invoices or an external billing cap**.

Adapters support OpenAI chat completions, Anthropic Messages, Gemini generateContent with Google Search grounding, Mistral/xAI/NVIDIA OpenAI-compatible chat endpoints, and Voyage embeddings. Hosts are fixed in server code, not supplied by papers or API callers. Each review, hypothesis check, proof alignment check, crew comparison and research request has a fresh context. Penelope never receives provenance, model, perspective or support count. Configure independent model families for the hypothesis checker and reviewer.

Every call reserves its maximum charge against global, journey and run accounts **before** making a network request. Atomic account updates prevent simultaneous calls from overspending a cap. Partial reservations are rolled back when another cap fails. Completed calls are cached by idempotency key. Ambiguous/failed calls conservatively retain their maximum charge; retries require fresh reservations. A crash between reservation and call storage can retain an unused reservation: reconcile against the provider ledger before any administrative release. The UI shows maximum-charge accounting, not invented exact billing.

Live API calls were not made during this build, and no paid resource was created.

## Modules and Atlas vectors

Live mode needs reviewed base modules before journeys can be created. The default three islands are linear algebra (15/15A/15A03), graph theory (05/05C/05C50) and probability (60/60B/60B20). Fixture MSC paths are deliberately a tiny illustrative subset, not the full MSC taxonomy or a curated mathematical corpus.

### Base modules from mathlib (the gods)

The overview's base graph is built in two halves. **By script**: `deploy/msc/<island>.json` holds the MSC 2020 group tree for each island (field, subfields, subtopics; titles abbreviated after msc2020.org) plus a documented module-path → MSC placement table; `deploy/lean/Extract.lean` exports declarations from the pinned mathlib (name, kind, module, source line, pretty-printed type with every hypothesis, docstring, and the constants the proof uses); `scripts/build_module.py` selects, places and bundles them, and `bridge` mode keeps cross-island dependencies in a bridge module that requires both island modules. **By judgment**: with `--execute`, the `gods` provider role (Claude in the roster) decides which declarations count as foundational, places each in exactly one depth-3 group, merges duplicates, writes group and concept descriptions, and proposes textbook gap-fillers. Gap-fillers land in the bundle's `pending_review` list with `reviewed: false`; a human must check each source before anything cited is imported, because a model's citation claim is not a reviewed citation. Everything the gods do runs as a durable, budgeted `module_build` operation that admits only the gods and embeddings roles.

```bash
# once: pinned toolchain + cached oleans (minutes, several GB; no model calls)
python scripts/setup_lean.py /abs/path/mathlib
# export one island's declarations (imports all of Mathlib; several GB of RAM)
python scripts/extract_mathlib.py --project /abs/path/mathlib --prefixes Mathlib.LinearAlgebra --output .lean/exports/linear-algebra.json
# offline, deterministic bundle (script placement, docstring descriptions)
python -m scripts.build_module island .lean/exports/linear-algebra.json --spec deploy/msc/linear-algebra.json \
    --id linear-algebra-mathlib@<version> --version <version> --limit 600 --output corpus/linear-algebra-mathlib.json
# gods-curated bundle (live mode, explicit budget)
python -m scripts.build_module island ... --execute --budget 5
# cross-island bridge from the same exports
python -m scripts.build_module bridge --bundles corpus/A.json corpus/B.json --exports .lean/exports/a.json .lean/exports/b.json --id A-B-bridge@<version> --version <version> --output corpus/A-B-bridge.json
```

Selection without the gods is a recorded heuristic: declarations that other exported results depend on, or that mathlib documents, ranked by how many results depend on them and capped by `--limit` (many central theorems, `Matrix.det_mul` for one, have no docstring, so documentation alone is not the test). Descriptions are the first docstring sentence or, when there is none, the declaration name with its formal statement; nothing is invented. Each declaration's proof dependencies form one `dependency` hyperedge into it (at most 20 premises, the most specific first; the full count is recorded). Dependency edges are compiler metadata, never inference, and import can never mint `verified` edges; see the trust model below. The shipped `corpus/*-mathlib*.json` bundles were built this way from an export of 18,467 declarations under `Mathlib.LinearAlgebra`, `Mathlib.Combinatorics.SimpleGraph`/`Digraph`, `Mathlib.Probability` and `Mathlib.NumberTheory` at mathlib `c44e0c8ee63ca166450922a373c7409c5d26b00b` (Lean 4.19.0), run in this repository's pinned project on 2026-11-15. They record the selection criteria, mathlib commit and a per-declaration GitHub source URL in `module.source`; they are script-mapped, not gods-curated, and carry no vectors (live deployments add them through `scripts/prepare_module.py --execute`). Island pairs whose exported declarations share no dependency produced no bridge and ship none.

| Module | Islands | Concepts | Dependency hyperedges | Selection / prerequisites |
|---|---|---|---|---|
| `graph-theory-mathlib@2026-11-15.1` | graph-theory | 800 | 787 | declarations with >= 1 exported dependents, or documented by mathlib; top 800 ranked by dependents (documented first on ties) |
| `linear-algebra-graph-theory-mathlib-bridge@2026-11-15.1` | graph-theory, linear-algebra | 0 | 6 | requires linear-algebra-mathlib@2026-11-15.1, graph-theory-mathlib@2026-11-15.1 |
| `linear-algebra-mathlib@2026-11-15.1` | linear-algebra | 800 | 675 | declarations with >= 1 exported dependents, or documented by mathlib; top 800 ranked by dependents (documented first on ties) |
| `linear-algebra-number-theory-mathlib-bridge@2026-11-15.1` | linear-algebra, number-theory | 0 | 69 | requires linear-algebra-mathlib@2026-11-15.1, number-theory-mathlib@2026-11-15.1 |
| `number-theory-mathlib@2026-11-15.1` | number-theory | 800 | 680 | declarations with >= 1 exported dependents, or documented by mathlib; top 800 ranked by dependents (documented first on ties) |
| `probability-mathlib@2026-11-15.1` | probability | 800 | 752 | declarations with >= 1 exported dependents, or documented by mathlib; top 800 ranked by dependents (documented first on ties) |

In fixture mode the server imports every bundle in `corpus/` at startup (`METIS_IMPORT_CORPUS=false` disables this), so these modules are selectable locally; their concepts report similarity as unavailable rather than inventing vectors.

Import an immutable module bundle with `POST /api/modules/import` or:

```bash
PYTHONPATH=. .venv/bin/python scripts/import_module.py path/to/module.json
```

Bundle schema: `module:{id,name,version,islands,mathlib_version,source,fixture:false}`, `groups:[{id,name,msc,depth,parent,ancestors,island,description}]`, `concepts:[{id,name,statement,description,kind,home_group,island,source,embedding}]`, `edges:[{id,premises,conclusion,directed,type,tier,argument,evidence}]`. IDs must be globally unique (prefix with module ID/version). Ancestry begins at the island, includes the home group, and has length equal to depth. Published versions are immutable; a new version needs new IDs. Bridge bundles may use `module.requires:[islandModuleId,...]` and reference those modules' existing groups/concepts without copying them. Journeys pin selected module IDs. The API supports explicit module selection, including versioned multi-island bridge bundles. Ready compatible bridge modules are included automatically when using default module selection.

Import never mints `verified` inference edges. A cited inference needs an explicitly reviewed source and location. Compiler dependencies are stored as **dependency metadata**, not inference. `scripts/import_mathlib.py --help` converts a supplied declaration/dependency JSON export plus reviewed MSC mapping into such a bundle. It retains the complete formal type, including hypotheses, and only creates dependency relations. It is not a bundled mathlib extractor or a claim that the declarations have been locally recompiled/axiom-audited. Curating real module mappings, citations and declaration exports is required before scientific use.

For real matching, configure the Voyage embedding role and Atlas Vector Search indexes named `metis_concepts` and `metis_groups` (names can be overridden by `METIS_ATLAS_CONCEPTS_INDEX`, `METIS_ATLAS_GROUPS_INDEX`). Two index modes exist. **Explicit vectors (default)**: `deploy/atlas-vector-index.json` indexes vectors the application generated through the budgeted Voyage adapter; base concepts/groups must already carry vectors from the **same** model. **Atlas Automated Embedding (opt-in, `METIS_ATLAS_AUTO_EMBED=true`)**: `deploy/atlas-auto-embed-index.json` defines an `autoEmbed` index on `description` with the same Voyage model, so Atlas embeds descriptions on write and query text at search time; duplicate matching and semantic search then spend no embedding call. In both modes the pairwise similarity in bridge scores still uses explicit vectors from the embeddings role, exactly as the overview's Storage section specifies, so the embeddings role stays required. Automated Embedding was a Preview feature when this was written and has not been exercised against a live cluster here; the default mode is the one validated so far. Failed/missing vector services fail the live stage; lexical fixture search is labeled separately.

## Mathematical trust model

- Typed, directed hyperedges preserve all premises. One hyperedge means AND; separate edges are alternative routes. Only `implies` and bidirectional `equivalent` are traversed as proof steps. Definition, generalization, special-case, related and dependency relations never imply a theorem merely by traversal.
- `Proposed` nodes and invalidated claims are excluded from proof reachability, distance and bridge scores. Inference validity requires a separate independent hypothesis/necessity/counterexample result plus blinded Penelope review. These remain model judgments, never mathematical guarantees.
- Distance ignores direction, uses only accepted cited/verified non-dependency relations, treats each premise as adjacent to the conclusion, caps disconnected pairs at `D_max` and excludes the candidate edge. Similarity is cosine with negative values clipped to zero. Scores use the strongest premise/conclusion pair; unintegrated concepts use tree distance alone. Unavailable embeddings produce an unavailable score rather than fabricated similarity.
- Input integration is reviewed before crew exploration. Extraction is globally content/schema/model keyed; matching, placement, integration and reviews happen within each journey's pinned graph. An isolated component of new paper nodes is not considered integrated merely because those nodes connect to each other.
- Cited evidence is **literature supported**, not machine verified. Before live citation review, source text is retrieved through the safe fetcher (or taken from the actual input paper), the excerpt must occur in that text, and the reviewer receives surrounding source context. Retrieval failure downgrades support. Human-reviewed module imports remain an explicit curator trust boundary.
- `Not found` means **potentially new in the recorded completed searches**, never proven novelty. Grounded queries, sources, timestamps and failures are stored. Incomplete/failed/ungrounded search remains `Unchecked`. Cited edges are Existing only after source review; a literature hit still needs a separate cited review before tier promotion.
- The reachability inspector gives a proof DAG of accepted edges from explicit assumptions, with its supporting edge IDs. Even a DAG of individually verified steps is labeled **composition unverified**; it is not silently promoted to a compiled Lean theorem. Definitions are never marked Proven.
- Rejected counterexamples survive as structured invalidation signals. Wrong feedback immediately removes a claim from valid reasoning and queues independent re-review. Declared dependent proof edges are recursively invalidated; restoring the original claim does not automatically restore its dependents. Journey overlays invalidate shared base claims without mutating base documents.
- Odysseus ranks accepted findings by tier, then bridge score, then literature status (`Not found` above `Unchecked` above `Existing`), then independent agreement, and never ranks his own proposed nodes. New paper concepts go through an enforced integration loop before the crew starts: level by level, up to `integration_depth`, the decomposer states what each still-unconnected concept rests on or leads to, links attach to matched existing nodes, and standard concepts the graph lacks become Established integration nodes with the paper's reference as source; whatever is still unconnected is flagged unintegrated and scored with tree distance alone. Fixture mode records the skipped loop instead of inventing links.
- An accepted Odysseus **conjecture** can be attempted by Hephaestus (in the run that accepts it and, within the remaining per-run proof budget, in later runs). The node becomes **Proven** only when an independently aligned statement compiles in the pinned sandbox and clears the axiom audit; a failed or unavailable attempt leaves it Accepted and is never evidence against it. Definitions stop at Accepted. The Home feed lists machine-verified potentially new results, Proven concepts, potentially new connections and accepted conjectures, in that order.
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

- The mathlib-derived modules are selected by a recorded heuristic unless the gods role has run; their descriptions are mathlib docstrings and their placement follows the path table in `deploy/msc/`. Gap-fillers proposed by the gods are never imported without human source review. Bridge bundles can refer to concepts in explicit pinned `module.requires` versions; journeys reject mismatched prerequisites.
- No automatic Atlas index provisioning or change-stream consumer. Durable cursor-indexed events feed SSE. Atlas real matching, in either index mode, must be acceptance-tested with a populated, correctly indexed corpus.
- Graph search supports lexical search and explicit budgeted meaning search through Voyage/Atlas; fixture meaning search is explicitly lexical. Suggested next papers are corpus papers near the latest bridge groups, rather than external recommendations. MSC-category bulk import scans the stored corpus only (at most 20 unique papers), preserves matching MSC placement in the selected modules, and reports unsupported placements. External MSC discovery is not implemented; bounded arXiv-ID import retrieves external papers.
- No automatic OCR, deep citation bibliography resolver, exact formal proof composition, or automatic external MSC harvesting. Human review of statement alignment and source quality is still required for scientific trust, even when model reviews pass.
- Pattern triggers group edges by island pair across different runs, which is a heuristic; recognizing a genuinely shared missing idea still depends on the proposer/reviewer. Blind concept acceptance exists but has not been exercised against live models.
- PDF uses the bundled ReportLab Vera font; some advanced mathematical Unicode glyphs may not render. JSON/Markdown preserve exact Unicode and complete structured evidence. PDF is a reading export, not the canonical mathematical archive.
- No accounts, multi-user authorization, distributed stress test, automated retention policy, operational metrics stack or managed hosted deployment. Keep single-user/local or behind a private authenticated TLS proxy. Source retrieval and parsing are bounded but this prototype is not a hardened hostile-document service.

Review live adapters against provider account/model contracts before setting any nonzero budget. Fixture success must never be used to assert real integration success.


## Plan alignment (2026-11-15)

An evaluation of this repository against the overview found the reasoning substrate faithful (bridge score, distances, hyperedge semantics, blinding, isolation, durable jobs, budgets, Lean sandbox) and the documented deviations deliberate, but listed gaps. The following were corrected in this branch:

- **Base graph and the gods**: `deploy/lean/Extract.lean`, `scripts/extract_mathlib.py`, `deploy/msc/*.json`, `metis/gods.py` and `scripts/build_module.py` implement the overview's two-half base-module build (script extraction + model curation) and bridge modules; the `gods` provider role exists and is admitted only inside durable budgeted `module_build` operations.
- **Integration loop**: the decomposer's "repeat until the chain reaches existing nodes, up to integration_depth" is now an enforced loop (`Pipeline.integrate`), not a prompt parameter.
- **Proven node status** and **Hephaestus attempts on accepted conjectures** are implemented (`metis/concepts.py`); Proven means machine verified only.
- **Ranking** uses tier, bridge score, literature status and agreement, in that order (`pipeline.ranking_key`).
- **Key discoveries** feed includes Proven concepts and accepted conjectures as well as potentially new connections.
- **Automated Embedding** is available as an opt-in index mode alongside explicit vectors; the default is unchanged and the choice is documented above.
- **Graph** renders with vendored Cytoscape.js (same-origin, CSP intact) with island compound nodes, hyperedge junctions, status colours (Established/Accepted/Proven/Proposed), layer shapes and unintegrated outlines. Since the UI spec it is the sea map's simplified view.
- **SSE** reads only events newer than the client's cursor through an indexed query instead of rescanning the events collection each second; the unused `adjacency` collection index is gone (distance is computed in code, as the overview allows at demo scale).
- `deploy/providers.example.json` follows the roster's provider families (xAI, NVIDIA, Mistral, Gemini, OpenAI, Anthropic, Voyage); model IDs remain placeholders until verified against your accounts.

Still outstanding and not claimable from this environment: a live cross-field discovery run (needs provider credentials and budget) and a gods-curated module (needs the `gods` role configured); the shipped mathlib modules are script-mapped and say so.

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

The field picker now reads `GET /api/catalog`: readiness, immutable versions,
source/fixture labels, counts and curated coverage reflect the current database.
Use **Add fields / modules** to select compatible ready versions without
rewriting existing pins; active runs block changes. The graph reports base vs
journey inventory and can inspect rejected/proposed relations as NON-EVIDENCE.
See [starter corpus sources and budgeted publication/migration commands](corpus/README.md#curated-starter-foundations-2026-11-152).
