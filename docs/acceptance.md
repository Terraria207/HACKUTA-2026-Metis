# Metis acceptance criteria

These are verification requirements, not claims that implementation is complete.

## Mathematical trust boundaries

- A+B→C cannot derive C when only A is reached. A→C and B→C are alternative routes. Equivalence works both ways. Cycles cannot bootstrap a proof.
- Definitions and dependency metadata cannot be traversed as logical implications. A cited proof stays literature supported; only audited formal proof establishes machine verification.
- Proposed nodes and their edges are excluded from proof traversal, distance and scoring. Unintegrated endpoints use tree-only bridge score.
- Graph distance ignores direction but counts only valid cited/verified edges, with candidate excluded. Hyperedge premises are each one hop from conclusion, not from each other. Disconnected nodes cap at D_max.
- Necessary-premise review checks actual arguments; uncertainty cannot be represented as a mathematical guarantee. Independent counterexample/hypothesis analysis is stored separately.
- A formal proof must match the target statement, use pinned tools and audited axioms, and have no placeholders. A compiler failure/unavailable sandbox leaves an edge unverified.
- Completed negative literature searches yield potentially new; errors yield Unchecked. Preserve query/date/source evidence. Existing citations need their own validation.

## Isolation and persistence

- Two journeys can propose identical endpoints without data collisions. Base modules remain immutable. Supporting a base edge creates only a journey overlay.
- Extraction cache is content/version keyed; node matching, integration and graph-sensitive reviews are journey scoped.
- Worker termination after a completed step does not duplicate edges, support counts, provider charges or reports on resume. Pause stops new calls, cancel cannot be undone by a late worker response.
- Lease expiry permits recovery. SSE reconnect restores missed events. The browser can close without killing backend work.
- Budget reservations are atomic across simultaneous calls; retries reserve new maximum costs. Unknown prices prevent paid calls. Provider budget is separate from Atlas credits.
- Secrets never appear in API responses, traces, exports or source control. URLs reject private/link-local destinations, including redirects and DNS changes. Uploads have size/time limits.

## User journeys

- Create, reopen and resume an exploration with selected versioned modules.
- Upload PDF, retrieve arXiv/URL, select corpus paper; inspect and correct MSC placement before run. Bulk import has bounded work and visible failures.
- Run, pause, resume, cancel and retry from trace; each error explains what remains incomplete.
- Report separates potentially new connections, rediscoveries and orchestrator concepts; feedback triggers re-review. Exports preserve evidence and trust labels.
- Graph shows hyperedge junctions, status/tier styling, filters, search, evidence, provenance, proof details and before/after state. History reopens old trace/report.
- Keyboard, narrow viewport and empty/error/loading states remain usable.

## Environment-specific verification

Record separately: deterministic fixture tests, MongoDB integration tests, real Atlas vector/change-stream tests, provider API tests, Lean sandbox tests, browser interaction tests. Passing fixture tests does not verify live integrations. Provide setup instructions and explicit missing credentials without manufacturing successes.

## Atlas deployment constraint

Prefer M0/free with bounded corpus, traces and connection pool. Atlas lists 512 MB including index storage for free clusters: https://www.mongodb.com/docs/atlas/manage-clusters/ . Automatic upgrade is disabled by application policy; no promise that an application setting caps cloud billing. Usage alerts and cloud billing controls must be configured in Atlas. The $50 credit balance is not model-provider authorization.

### Internal-paper extraction regression (2026-11-15)

Inspection of the first live Collatz extraction found four concepts and one internal
relation. The relation used a numeric tier (`1`) instead of the required enum,
so it was rejected before review; the six reviewed rejections were later crew
proposals. Thus pipeline completion did not demonstrate successful extraction
of the paper's internal relationships.

Extraction v5 explicitly requests internal definition/dependency relationships,
self-contained hypotheses, and verbatim source evidence. It validates concept fields and local
references and relation schemas before integration and makes at most one
budget-accounted repair call for malformed or empty relationships. Still-invalid
repair output fails the stage before caching; a supported empty result remains
allowed and is traced. The cache version prevents reusing the deficient v2
extraction in fresh runs. This does not relax mathematical or citation review,
nor does it repair previously saved runs retroactively.

Descriptive relation review distinguishes a documented dependency from logical
entailment; accepting a dependency does not make it traversable as a proof step.
Provider read timeouts are bounded at 180 seconds (connect: 15 seconds) to allow
complete structured extraction responses from slower models.

Live re-extraction run `r_1bc78738aef57acb34e0c57a8e92b6b2` completed
in ingestion-only mode: 17 extracted concepts and 10 reviewed relations, 7 passed
and 3 rejected. Five accepted relations connect journey concepts to each other;
two connect paper concepts with reused base concepts. Six passed relations are
cited and one is intuitive; none is machine-verified. The live default graph now
has 43 concepts and 15 relations, including the eight pre-existing base relations.
This is paper integration, not a new cross-field discovery run. Conservative
global provider ledger after validation: $39.22 of the authorized $100 cap.
Regression suite: 113 passed, 2 optional integrations skipped.
