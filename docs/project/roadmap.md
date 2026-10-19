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
- [ ] `examples/policy_corpus/` — seeded example corpus
- [ ] `cli.py` — `scan` command
- [ ] `adapters/pgvector.py` + contract tests (needs Docker running)
- [ ] `adapters/qdrant.py` + contract tests (needs Docker running)

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
