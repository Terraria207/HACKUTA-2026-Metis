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
