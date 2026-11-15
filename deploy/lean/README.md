The compiler environment uses Lean 4.19.0 and mathlib commit
c44e0c8ee63ca166450922a373c7409c5d26b00b. pins.json records both and the SHA256
of the upstream dependency manifest, also committed here. Every dependency
revision in that manifest is pinned. Setup refuses a mismatched checkout.

Install elan from its official release, put lake on PATH, then in a managed
terminal (downloads and cache preparation can take minutes):

```
python scripts/setup_lean.py /absolute/path/to/mathlib
```

This downloads upstream code/cache, validates pins, compiles Acceptance.lean,
and writes METIS_MATHLIB_VERSION only after success. No model API is involved.
The acceptance file checks the shortcut map at 19 and 29, a valuation default,
and an explicitly conditional even-step identity. These are small compiler
checks, not a formalization of the paper. Cached upstream oleans remain part of
the trusted toolchain supply chain.

For the application's restricted Docker verifier, build with a compatible Linux
base pinned by registry digest (no implicit latest image):

```
python scripts/build_lean_image.py --project /absolute/path/to/mathlib --base-image REGISTRY/BASE@sha256:DIGEST
```

Publish that image to a controlled registry, resolve its RepoDigest, and configure
METIS_LEAN_IMAGE with that immutable reference and METIS_LEAN_PROJECT with the
prepared absolute project directory. The runtime never pulls images; preload it.
The builder copies the exact installed toolchain into /opt/lean; the mathlib
project and oleans are mounted read-only separately. Test the deployment using:

```
METIS_TEST_LEAN_IMAGE=REGISTRY/IMAGE@sha256:DIGEST METIS_TEST_LEAN_PROJECT=/absolute/path/to/mathlib python -m pytest tests/test_lean_acceptance.py
```

The opt-in test requires real sandbox compilation, rejects a false theorem and
placeholder proof, and checks version mismatch. It skips when unconfigured.

Development verification: setup_lean.py completed successfully in an Aether
managed terminal on 2026-11-15, including actual Lean compilation of all three
acceptance theorems. Docker image publication and the application's sandbox
acceptance test were not run; no registry credentials were used.
