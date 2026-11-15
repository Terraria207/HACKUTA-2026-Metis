This is a small curated source-backed module, not a comprehensive number theory
corpus or a formalization of Collatz. Six concepts occupy MSC 11B83 and 11D61.
There are no inference edges, no fabricated vectors, and no verified claims.
The importer uses Established to mean accepted base material, not compiler proof.

Primary sources retrieved 2026-11-15:

* Jean-Louis Verger-Gaugry, arXiv:2611.14569v1,
  https://arxiv.org/html/2611.14569v1 : equation (1.0.1), Section 1 definitions,
  Theorem 1.2(iii), and the integer restriction in Section 2's S-unit definition.
  The paper assumes divergence; its prime-set theorem also requires uniformly
  bounded wave heights. It does not prove or disprove Collatz. Its quoted
  Bennett–Billerey finiteness theorem is deliberately not imported: independently
  checking that primary theorem and its exceptional cases remains outside this module.
* Mathlib at c44e0c8ee63ca166450922a373c7409c5d26b00b,
  https://github.com/leanprover-community/mathlib4/blob/c44e0c8ee63ca166450922a373c7409c5d26b00b/Mathlib/NumberTheory/Padics/PadicVal/Defs.lean
  declaration padicValNat, including its zero/default conventions.

The source statements are curator paraphrases, with locators and hypotheses;
there has been no independent mathematical peer review. The conditional theorem
is a report of the author's claim, not locally audited inference.

From the repository root, with Python dependencies installed:

```
python -m scripts.prepare_module corpus/number-theory.json
python -m scripts.import_module corpus/number-theory.json
```

The first command validates offline without reading provider credentials. The
second imports without embeddings using existing deployment configuration.
For a live vector-search-ready import, instead use the following only after
private provider configuration and an approved budgeted run exist:

```
python -m scripts.prepare_module corpus/number-theory.json --execute --run-id RUN_ID
```

This uses Providers/AtlasVectors and their global, journey and run reservations.
It requires 1024-dimensional vectors matching deploy/atlas-vector-index.json.
Use the same embedding model for later paper embeddings. No paid call was made
while developing this module. Imported versions are immutable; choose a new
version to change content. Select Number theory after importing the module.

## Curated starter foundations (2026-11-15.2)

These manually inspected, source-backed bundles add 48 concepts and 35 cited
relations, plus a single descriptive cross-field bridge. They contain no stored
embeddings and mint no machine-verified edges. Citation review is curator review,
not a Lean proof or independent model review. Coverage is deliberately modest.

| Bundle | Concepts | Relations | Scope |
|---|---:|---:|---|
| `linear-algebra-starter.json` | 12 | 9 | Finite real vector families, basis/dimension, stochastic matrices |
| `graph-theory-starter.json` | 12 | 9 | Finite simple graphs, subgraphs and trees |
| `probability-starter.json` | 12 | 9 | Axioms, event identities, conditional probability, finite Markov evolution |
| `number-theory-starter.json` | 12 | 8 | Additive integer divisibility/gcd/prime foundations |
| `markov-bridge.json` | 0 | 1 | Stochastic matrix → finite Markov evolution (`defined_from`) |

The number-theory extension **requires `number-theory@2026-11-15.1`**. It does
not replace or rewrite the six Collatz/S-unit concept IDs. A journey with both
has 18 number-theory concepts and eight relations. The original six concepts
remain without new relations; no Collatz implication is asserted. With all
bundles and the old base pinned, there are 54 concepts and 36 relations.

Exact inspected source locators (each concept and edge also carries its locator):

- Margalit and Rabinoff, *Interactive Linear Algebra*, [§2.2.1–2 Vector Equations and Spans](https://textbooks.math.gatech.edu/ila/spans.html), [§2.5.1 Linear Independence](https://textbooks.math.gatech.edu/ila/linear-independence.html), [§2.7.1 Basis and Dimension](https://textbooks.math.gatech.edu/ila/dimension.html), [§5.6.1–2 Stochastic Matrices](https://textbooks.math.gatech.edu/ila/stochastic-matrices.html). The bridge uses the Red Box transition example and the stochastic-matrix/Markov-chain definitions. Column-stochastic convention throughout.
- Oscar Levin, *Discrete Mathematics: An Open Introduction*, 3rd edition, [§4.1 Graph Definition, Isomorphic Graphs, Subgraphs, bipartite definition](https://discrete.openmathbooks.org/dmoi3/sec_gt-intro.html); [§4.2 tree/forest definitions, Proposition 4.2.1, Corollary 4.2.2, Proposition 4.2.3](https://discrete.openmathbooks.org/dmoi3/sec_trees.html).
- Hossein Pishro-Nik, *Introduction to Probability, Statistics, and Random Processes*, [§1.3.2 Axioms 1–3](https://www.probabilitycourse.com/chapter1/1_3_2_probability.php), [§1.3.3 worked probability identities, items 1–3, 5–6](https://www.probabilitycourse.com/chapter1/1_3_3_finding_probabilities.php), [§1.4.0 conditional probability formula and conditional axioms](https://www.probabilitycourse.com/chapter1/1_4_0_conditional_probability.php).
- Thomas W. Judson, *Abstract Algebra: Theory and Applications*, [§2.2](https://math.libretexts.org/Bookshelves/Abstract_and_Geometric_Algebra/Abstract_Algebra:_Theory_and_Applications_(Judson)/02:_The_Integers/2.02:_The_Division_Algorithm): divisibility/gcd definitions after Theorem 2.9; Theorem 2.10; Corollary 2.11; Euclidean Algorithm; Prime Numbers; Lemma 2.13; Theorems 2.14–15. The web rendering of Theorem 2.9 is malformed, so no claim cites that theorem.

Definitions and `defined_from`/`related` edges are descriptive and cannot be
traversed as proof implications. Logical basis and tree edges refer to the same
objects on both endpoints; hypotheses are retained in statements and arguments.
There is no spectral theorem, advanced probability, general module theory,
analytic number theory, or exhaustive foundations coverage here. Isolated nodes
are intentional where no supported relation has been curated.

Validate without credentials, network access, or paid calls:

```sh
python -m scripts.prepare_module corpus/linear-algebra-starter.json
python -m scripts.prepare_module corpus/graph-theory-starter.json
python -m scripts.prepare_module corpus/probability-starter.json
python -m scripts.prepare_module corpus/number-theory-starter.json --prerequisite corpus/number-theory.json
python -m scripts.prepare_module corpus/markov-bridge.json --prerequisite corpus/linear-algebra-starter.json --prerequisite corpus/probability-starter.json
python -m pytest -q tests/test_base_exploration.py tests/test_api.py tests/test_graph.py
```

Publication is explicit. In the parent's already configured live shell, with
`METIS_ALLOW_LIVE` and the global budget cap enabled, run the following budgeted
commands. Each content-bearing bundle gets its own durable setup operation;
`--setup-budget 1` is a cap, not a promised price. Use a smaller parent-approved
cap if appropriate. The original number-theory bundle must already be published
(or prepare it first). A relation-only bridge makes no embedding call.

```sh
python -m scripts.prepare_module corpus/linear-algebra-starter.json --execute --setup-budget 1
python -m scripts.prepare_module corpus/graph-theory-starter.json --execute --setup-budget 1
python -m scripts.prepare_module corpus/probability-starter.json --execute --setup-budget 1
python -m scripts.prepare_module corpus/number-theory-starter.json --prerequisite corpus/number-theory.json --execute --setup-budget 1
python -m scripts.prepare_module corpus/markov-bridge.json --prerequisite corpus/linear-algebra-starter.json --prerequisite corpus/probability-starter.json --execute --setup-budget 1
```

`--prerequisite` supplies bundles only to ephemeral offline validation. It does
not publish dependencies, copy embeddings, or replace deployment versions.
Execution validates exact prerequisite IDs against ready deployment modules.
Preparation retries preserve existing immutable publication checks and billing
idempotency. Inspect accounting before explicitly increasing `--setup-attempt`.

After publication, reload the new-journey catalog or use **Add fields / modules**
in an existing journey. Select the desired ready module IDs explicitly. Adding
number-theory foundations to the old number-theory journey requires selecting
its additive extension, not another root version. Adding linear algebra or
probability to a journey already pinned to their fixture versions is rejected;
create a new journey with the sourced roots. Select the bridge only alongside
its exact sourced linear-algebra/probability prerequisite pins. The API is
`GET /api/catalog` and `POST /api/journeys/{id}/modules` with
`{"modules":["linear-algebra-starter@2026-11-15.2"]}`. Run locks block changes
while queued/running/paused; finish or cancel first. Existing pins and all old
run snapshots remain unchanged; additions are recorded in `module_history`.
