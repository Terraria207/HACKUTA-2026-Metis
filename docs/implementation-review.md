# Metis implementation review

Source: Metis — Lower-Level Overview, November 14, 2026, 23 pages.
Status: requirements reviewed; implementation not yet started.

## Correctness issues to resolve

1. Literature search cannot establish novelty. “Not found” must mean no prior statement found in the recorded searches, never “proven new result.” Record queries, sources, dates and search failures; failed searches remain Unchecked.
2. Mathlib proof dependencies are not automatically logical implications between natural-language concept nodes. Separate dependency metadata from inference edges. Never discard hypotheses when constructing an inference. A compiled declaration can establish its exact formal statement, not an arbitrary extracted relationship.
3. “Is defined from” and generalization relationships are not uniformly proof steps. Give edge types explicit inference semantics; traversal for proof construction must not treat every relationship as implication.
4. Lean compilation alone is insufficient for verification: placeholders and extra axioms can compile. Reject sorry/admit, audit declaration axioms against a policy, pin the toolchain and mathlib, and run generated code in a resource-limited isolated environment. Statement matching remains a separate reviewed check.
5. Cache extraction globally, but scope matching, integration and graph review to the journey and module versions. A review in one graph cannot establish placement or lack of duplicates in another.
6. Duplicate identity needs layer and relationship type as well as endpoints. Otherwise separate journeys collide and distinct logical relationships merge. Base support must be a journey overlay.
7. Change streams alone are not a durable job queue. Persist jobs, checkpoint steps, use leases and idempotency keys, and recover from expired stream tokens. Budget reservations must precede parallel provider calls.
8. Rejected counterexamples cannot be invisible to conflict resolution. Supply structured invalidation signals without presenting rejected claims as findings. Wrong-feedback review must invalidate dependent proof claims when warranted.

## Implementation sequence

1. Define typed schemas, module versions, journey isolation, evidence provenance and conservative proof semantics. Test hyperedge AND versus independent-edge OR, cycles, quarantine, graph distance and scoring.
2. Implement MongoDB persistence, indexes, durable jobs, checkpoints, budget accounting, retries and live events.
3. Implement versioned base-module import, paper ingestion, extraction cache and journey-specific integration.
4. Implement configurable provider adapters, blinded reviews, rotating crew assignments, formal verification, literature checks and ranking with auditable evidence.
5. Implement journey UI, run controls, graph inspection, report/export, history, settings and feedback re-review.
6. Verify with deterministic fixtures and integration tests; separately run live provider, Atlas and Lean acceptance tests when configured. Fixture results must be labeled and must never imply real mathematical discovery.

## Decisions needed

- Should “Proven” mean machine-checked only, or also include arguments relying on cited literature as the overview currently specifies? Recommendation: distinct “machine verified” and “literature supported” labels.
- Are Atlas and provider services available for this build, and what is the permitted live-call budget? Keep secrets in environment/server-side configuration.
- Default demo islands: linear algebra, graph theory and probability. Exact MSC mappings and curated base corpus must be versioned and traceable to sources.

## Accepted decisions (user follow-up)

- Use “potentially new”; never infer novelty from a negative search.
- Proven means machine verified only. Cited arguments are literature supported.
- Add independent hypothesis/counterexample analysis for inference edges; dependency metadata is never itself a proof.
- Reject placeholder proofs and unapproved axioms; verify formal statement alignment.
- Atlas allowance is $50 in credits with free tier available. Prefer free tier. This is not a model-provider budget or a guarantee of an Atlas billing cap. Live provider calls require separately configured credentials and explicit budget.
