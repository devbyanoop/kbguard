# Roadmap & status

This page is the single source of truth for "is X actually built yet?" — updated the same day any item's status changes, not retroactively. If a page elsewhere in this guide seems to claim more than this page shows as done, trust this page.

**Last updated:** 2026-10-19

## Phase 0 — scaffold

- [x] Git repository, `.gitignore` (snapshots and `.env` files never committed)
- [x] `pyproject.toml` — packaging, extras per vector store, `ruff`/`mypy`/`pytest` config
- [x] Python virtual environment, editable install verified
- [x] `docker-compose.yml` for pgvector/Qdrant test fixtures (Docker now installed on dev machine; daemon start still needed before first use)
- [x] This documentation site (MkDocs + Material)

## Week 1 — foundations

**Goal:** `kbguard scan` writes a snapshot from Chroma, pgvector, and Qdrant.

**Status: partially met.** `kbguard scan` is fully working end-to-end against Chroma — verified for real against `examples/policy_corpus/`, not just in tests. pgvector and Qdrant are blocked on Docker (see below), not on anything in kbguard's own code; everything both adapters need (the Protocol, the registry, the contract test suite, `docker-compose.yml`) is already built and ready for them.

- [x] `models.py` — `Chunk`, `Finding` (+ fingerprint algorithm), `EvalResult`, `Snapshot`. Tested, lint-clean, strict-mypy-clean.
- [x] `config.py` — load/validate `kbguard.yaml` (pydantic, strict schema, secrets-by-env-var-name). Tested, lint-clean, strict-mypy-clean.
- [x] `adapters/base.py` — the `VectorStoreAdapter` Protocol, plus `src/kbguard/py.typed` (PEP 561 marker, needed for the Protocol to type-check for anyone importing kbguard as an installed package, not just within this repo). Tested (structural conformance via mypy), lint-clean, strict-mypy-clean.
- [x] `registry.py` — entry-point plugin discovery (`load_adapter`, `list_available`). Only the `adapters` group is wired up; `checks`/`metrics` groups land when their Protocols exist (Week 2/3). Tested, lint-clean, strict-mypy-clean.
- [x] `adapters/chroma.py` — in-process, registered as a real plugin, covered by adapter-specific tests (pagination, search ordering, embeddings on/off). Lint-clean, strict-mypy-clean.
- [x] `contract_tests/` — the shared, backend-agnostic suite (count/iteration, id stability, search ordering, text/metadata/embedding round-trip). Parametrized over `BACKENDS` in `contract_tests/conftest.py`; currently just `["chroma"]`. Passing.
- [x] `ingest/metadata.py` — fills `Chunk`'s standard fields (`source`, `position`, `version`, `updated_at`, `title`) from a chunk's own raw metadata via dotted-path `metadata_map` config, with type coercion and a `validate_metadata_map` check against unknown target fields. Tested (12 cases), lint-clean, strict-mypy-clean.
- [x] `ingest/embeddings.py` — `get_embedder` (lazy-loaded, provider-dispatched text→vector function) + `embed_chunk` (reuse-or-recompute policy). `config.py`'s `EmbeddingsConfig` gained an explicit `provider` field (`sentence-transformers` default, or `litellm`) rather than guessing from the model name — guessing wrong would risk document text silently leaving the user's machine. Tested (7 cases, fake modules injected via `sys.modules` so tests don't depend on the optional extras being installed), lint-clean, strict-mypy-clean (added a `[[tool.mypy.overrides]]` entry for untyped optional extras).
- [x] `ingest/exporter.py` — `export_chunks` drives `iter_chunks()` → `apply_metadata_map` → `embed_chunk`, yielding fully-populated `Chunk`s. Deliberately split so `validate_metadata_map` runs the instant it's called, not deferred to first iteration (a plain function returning an inner generator, not a generator itself — see changelog). `with_embeddings` passed to the adapter is wired directly to `reuse_stored`, so stored vectors are never fetched just to be discarded. Tested (5 cases, order/wiring/reuse-behavior), lint-clean, strict-mypy-clean.
- [x] `ingest/snapshot.py` — `SnapshotWriter`/`SnapshotReader`: `chunks.parquet` (explicit schema — an empty collection would otherwise get incompatible `null`-typed columns, confirmed by hand), `vectors.npy` (plain `np.load`, not memory-mapped — mmap broke a Windows temp-dir cleanup with a file-in-use error, confirmed by hand), `index.sqlite` (chunk id → row, source → chunk ids, finding fingerprints), `findings.jsonl`, `manifest.json`. Fails fast on a missing embedding, a dimension mismatch, a duplicate chunk id, a duplicate finding fingerprint, or writing after `close()`. No bulk vector accessor yet — deferred until a real caller (`checks/duplicates.py`, Week 2) needs one. 13 tests, lint-clean, strict-mypy-clean (added `pyarrow-stubs` as a dev dependency).
- [x] `cli.py` — `scan` command (typer). Needed a `@app.callback()` to stop typer collapsing a single-command app into a bare top-level command — without it, `kbguard scan ...` would only have worked as `kbguard ...` until a second command existed. Known user-facing error types caught and printed cleanly (no traceback); anything else is a real bug and still surfaces as one. Verified as a genuinely installed console script (`kbguard --help`, `kbguard scan --help`), not just through typer's test runner. 4 tests, lint-clean, strict-mypy-clean.
- [x] `examples/policy_corpus/` — 16-chunk synthetic demo corpus with planted problems (exact + near duplicate, a stale version pair that's also a numeric contradiction, an unrelated contradiction pair, four chunking-damage cases, three clean chunks). Hand-crafted embeddings (not a real model) specifically calibrated against the real default `cosine: 0.97` threshold — every pairwise similarity verified by hand before being committed, now locked in by 23 regression tests. `kbguard scan` run against it for real (not just in tests) and its output hand-inspected. `docs/getting-started/quickstart.md` now real, built from these exact verified commands.
- [ ] `adapters/pgvector.py` + contract tests — **blocked**: Docker Desktop can't start on this machine because WSL2 isn't installed (`wsl --install` needs admin + a reboot — not done without being asked).
- [ ] `adapters/qdrant.py` + contract tests — same blocker.

## Week 2 — checks, health score, first report

**Goal:** every seeded problem in the example corpus is found; first HTML report renders.

- [ ] `checks/base.py`, `checks/duplicates.py`, `checks/stale_versions.py`, `checks/chunking_damage.py`
- [ ] `judge/client.py`
- [ ] `checks/contradictions.py`
- [ ] `adapters/pinecone.py`, `adapters/bridge_langchain.py`
- [ ] `scoring/health.py`
- [ ] `report/results.py`, `report/templates/report.html.j2`, `report/html.py`
- [ ] `cli.py` — checks wired into `scan`, `report` command

## Week 3 — evals, judge, diff, CI

**Goal:** a chunking change shows up as a failing `diff`.

- [ ] `evals/golden.py`, `evals/retrieval.py`, `evals/target.py`
- [ ] `evals/metrics/base.py`, `ragas_plugin.py`, `deepeval_plugin.py`
- [ ] `judge/calibrate.py`
- [ ] `scoring/diff.py`
- [ ] `cli.py` — `golden`, `eval`, `calibrate`, `diff`
- [ ] `.github/workflows/kbguard.yml`

## Week 4 — docs, packaging, release

- [ ] Full README quickstart
- [ ] This docs site filled in end to end, placeholders removed
- [ ] PyPI packaging verified (`twine check`, clean-venv install from built wheel)
- [ ] Sample audit report against a real public corpus, published
- [ ] Write-up / case study for outreach

## Full internal build plan

The complete file-by-file build plan — purpose, concepts, design rationale, and verification steps for every file above — lives in the project's own `Plan/BUILD_PLAN.md` (not published here; it's written for the person building kbguard, not for the end-user guide you're reading now).
