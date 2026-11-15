# MSC 2020 placement

- `mathlib-paths.txt` — the script's placement of mathlib declarations in MSC 2020 subtopics: one
  module-path prefix and one five-character code per line, longest prefix wins, `-` leaves a
  prefix out. It covers every mathematical area of mathlib; `scripts/index_export.py` refuses any
  code that is not in the official table. This is the recorded heuristic the gods role refines.
- `linear-algebra.json`, `graph-theory.json`, `probability.json`, `number-theory.json` — the
  earlier hand-written specs for the four demo islands (abbreviated subtopic lists and their own
  path tables). They are what the `corpus/*-mathlib.json` bundles of 2026-11-15.1 were built from
  and are still used when `METIS_MATHLIB_EXPORT` is a single export file rather than an index.

The MSC 2020 table itself is **not** in this repository. Mathematical Reviews and zbMATH publish it
under a Creative Commons CC BY-NC-SA licence, so `scripts/fetch_msc.py` downloads it from
msc2020.org into a git-ignored directory. Modules built from it carry MSC codes and titles;
check that licence against your use before redistributing them.
