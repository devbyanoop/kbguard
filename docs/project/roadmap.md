# Roadmap & status

This page is the single source of truth for "is X actually built yet?" — updated the same day any item's status changes, not retroactively. If a page elsewhere in this guide seems to claim more than this page shows as done, trust this page.

**Last updated:** 2026-10-20 (later same day)

## Phase 0 — scaffold

- [x] Git repository, `.gitignore` (snapshots and `.env` files never committed)
- [x] `pyproject.toml` — packaging, extras per vector store, `ruff`/`mypy`/`pytest` config
- [x] Python virtual environment, editable install verified
- [x] `docker-compose.yml` for pgvector/Qdrant test fixtures (Docker now installed on dev machine; daemon start still needed before first use)
- [x] This documentation site (MkDocs + Material)

## Week 1 — foundations

**Goal:** `kbguard scan` writes a snapshot from Chroma, pgvector, and Qdrant.

**Status: met.** `kbguard scan` works end-to-end against all three stores — verified for real (not just in tests) with a real `kbguard scan` run against each. Docker runs on a different machine on the network, reached via `DOCKER_HOST=ssh://...`; the test suite's connection host is configurable via environment variables rather than assuming `localhost` (see [Contributing](../project/contributing.md)) specifically because of this.

- [x] `models.py` — `Chunk`, `Finding` (+ fingerprint algorithm), `EvalResult`, `Snapshot`. Tested, lint-clean, strict-mypy-clean.
- [x] `config.py` — load/validate `kbguard.yaml` (pydantic, strict schema, secrets-by-env-var-name). Tested, lint-clean, strict-mypy-clean.
- [x] `adapters/base.py` — the `VectorStoreAdapter` Protocol, plus `src/kbguard/py.typed` (PEP 561 marker, needed for the Protocol to type-check for anyone importing kbguard as an installed package, not just within this repo). Tested (structural conformance via mypy), lint-clean, strict-mypy-clean.
- [x] `registry.py` — entry-point plugin discovery (`load_adapter`, `list_available`). Only the `adapters` group is wired up; `checks`/`metrics` groups land when their Protocols exist (Week 2/3). Tested, lint-clean, strict-mypy-clean.
- [x] `adapters/chroma.py` — in-process, registered as a real plugin, covered by adapter-specific tests (pagination, search ordering, embeddings on/off). Lint-clean, strict-mypy-clean.
- [x] `contract_tests/` — the shared, backend-agnostic suite (count/iteration, id stability, search ordering, text round-trip, metadata round-trip as a superset check, embedding round-trip). Passing against Chroma, pgvector, and Qdrant. A backend whose container isn't reachable skips cleanly rather than failing — needed a second layer beyond the upfront TCP reachability check, since an unrelated local service occupying the same port made that check pass while the real connection still failed (confirmed by hand on this dev machine).
- [x] `ingest/metadata.py` — fills `Chunk`'s standard fields (`source`, `position`, `version`, `updated_at`, `title`) from a chunk's own raw metadata via dotted-path `metadata_map` config, with type coercion and a `validate_metadata_map` check against unknown target fields. Tested (12 cases), lint-clean, strict-mypy-clean.
- [x] `ingest/embeddings.py` — `get_embedder` (lazy-loaded, provider-dispatched text→vector function) + `embed_chunk` (reuse-or-recompute policy). `config.py`'s `EmbeddingsConfig` gained an explicit `provider` field (`sentence-transformers` default, or `litellm`) rather than guessing from the model name — guessing wrong would risk document text silently leaving the user's machine. Tested (7 cases, fake modules injected via `sys.modules` so tests don't depend on the optional extras being installed), lint-clean, strict-mypy-clean (added a `[[tool.mypy.overrides]]` entry for untyped optional extras).
- [x] `ingest/exporter.py` — `export_chunks` drives `iter_chunks()` → `apply_metadata_map` → `embed_chunk`, yielding fully-populated `Chunk`s. Deliberately split so `validate_metadata_map` runs the instant it's called, not deferred to first iteration (a plain function returning an inner generator, not a generator itself — see changelog). `with_embeddings` passed to the adapter is wired directly to `reuse_stored`, so stored vectors are never fetched just to be discarded. Tested (5 cases, order/wiring/reuse-behavior), lint-clean, strict-mypy-clean.
- [x] `ingest/snapshot.py` — `SnapshotWriter`/`SnapshotReader`: `chunks.parquet` (explicit schema — an empty collection would otherwise get incompatible `null`-typed columns, confirmed by hand), `vectors.npy` (plain `np.load`, not memory-mapped — mmap broke a Windows temp-dir cleanup with a file-in-use error, confirmed by hand), `index.sqlite` (chunk id → row, source → chunk ids, finding fingerprints), `findings.jsonl`, `manifest.json`. Fails fast on a missing embedding, a dimension mismatch, a duplicate chunk id, a duplicate finding fingerprint, or writing after `close()`. No bulk vector accessor yet — deferred until a real caller (`checks/duplicates.py`, Week 2) needs one. 13 tests, lint-clean, strict-mypy-clean (added `pyarrow-stubs` as a dev dependency).
- [x] `cli.py` — `scan` command (typer). Needed a `@app.callback()` to stop typer collapsing a single-command app into a bare top-level command — without it, `kbguard scan ...` would only have worked as `kbguard ...` until a second command existed. Known user-facing error types caught and printed cleanly (no traceback); anything else is a real bug and still surfaces as one. Verified as a genuinely installed console script (`kbguard --help`, `kbguard scan --help`), not just through typer's test runner. 4 tests, lint-clean, strict-mypy-clean.
- [x] `examples/policy_corpus/` — 16-chunk synthetic demo corpus with planted problems (exact + near duplicate, a stale version pair that's also a numeric contradiction, an unrelated contradiction pair, four chunking-damage cases, three clean chunks). Hand-crafted embeddings (not a real model) specifically calibrated against the real default `cosine: 0.97` threshold — every pairwise similarity verified by hand before being committed, now locked in by 23 regression tests. `kbguard scan` run against it for real (not just in tests) and its output hand-inspected. `docs/getting-started/quickstart.md` now real, built from these exact verified commands.
- [x] `adapters/pgvector.py` — keyset pagination (`id > :last`), not `OFFSET` (real risk on a live, multi-writer table). Table/column names come from config, validated against a strict identifier allowlist before use in SQL (can't be parameterized like values can). Never runs DDL — `CREATE EXTENSION`/`CREATE TABLE` stay the DBA's responsibility, enforced structurally (no write method exists on the adapter at all). `search(..., filters=...)` raises `NotImplementedError` rather than silently returning unfiltered results. Verified against a real `pgvector/pgvector:pg16` container via both `contract_tests/` and adapter-specific tests (identifier validation, custom column names, pagination), plus a real `kbguard scan` run. Added `psycopg`/`pgvector` as the `pgvector` extra's real dependencies.
- [x] `adapters/qdrant.py` — scroll-cursor pagination; `query_points()` not `.search()` (confirmed the latter doesn't exist on the installed client version — would have been wrong from memory). Qdrant point ids must be an unsigned int or UUID (confirmed by hand), so `Chunk.id` defaults to the stringified native id, with an opt-in `id_field` setting to read a client's real external id back out of the payload when it didn't fit that constraint. `text_field` (a `store.yaml` sibling of `settings`, wired through `cli.py`) reads chunk text out of the payload, since Qdrant has no distinct text storage. Verified against a real Qdrant container the same way as pgvector.

## Week 2 — checks, health score, first report

**Goal:** every seeded problem in the example corpus is found; first HTML report renders.

- [x] `checks/base.py` — the `Check` Protocol + `CheckContext` (config + optional live adapter/collection for checks needing a self-retrieval probe; no `judge` field yet — added when `judge/client.py` exists and `contradictions.py` actually needs it). Plus `registry.py` gained a `checks` entry-point group (`load_check`, `list_available("checks")`) — the mechanism that keeps `faiss`/`datasketch` honestly optional: confirmed by hand that importing the registry or an adapter pulls in neither, only `load_check("duplicates")` does.
- [x] `checks/duplicates.py` — exact (normalized-text hash) + near (`faiss` cosine ANN candidates, confirmed only with `datasketch` word-set Jaccard) duplicate detection, union-find clustering for transitive chains, severity escalated to `error` across sources. Verified against the real example corpus: finds exactly the two planted duplicate pairs, nothing else. Found and fixed a real bug in the original architecture spec along the way: the default `minhash_jaccard: 0.9` was measured against real paraphrased text and would almost never fire — corrected to `0.3` (see `docs/guide/checks/duplicates.md` for the full comparison table). `SnapshotReader` gained a bulk `vectors()` accessor (deferred from Week 1 specifically until this real caller needed it). `hnswlib` (originally planned as an ANN option) can't build on Windows without MSVC Build Tools — used `faiss-cpu` instead, which ships a working prebuilt wheel. Also closed a real gap from Week 1: `tests/test_plugin_registration.py` only ever tested Chroma's registration, never pgvector/Qdrant — fixed.
- [x] `checks/stale_versions.py` — groups by `title` (falling back to a normalized source/filename stem), orders by `updated_at` (falling back to `version` string), flags every member but the newest, escalates to `error` via a self-retrieval probe (query the *live* store with the stale chunk's own embedding, check if the current version also comes back in the top 5). Verified against the real example corpus and a live Chroma connection: the planted pair is found and genuinely escalates, confirmed by a real search call, not assumed.
- [x] `checks/chunking_damage.py` — six deterministic rules (`size`, `split_table`, `orphan_heading`, `broken_sentence`, `missing_metadata`, `encoding_noise`), no embeddings/LLM/optional deps. Verified against the real example corpus: added a missing planted example (`encoding-noise-1`, control characters in payment-methods text — the corpus had no example for that rule until this review caught it) and fixed a real bug found by hand: `pricing-table-cut`'s cut-off last row (`"| Pro | $25/mo"`) was passing every heading heuristic and getting double-flagged as `orphan_heading` in addition to the correct `split_table` finding, fixed by excluding any line containing `|` from the heading check. Also found the corpus's chunks (3-25 words, built for easy hand-verification) all sit under the spec's global `min_tokens: 40` default — not a spec bug, so fixed with a corpus-local override (`examples/policy_corpus/kbguard.yaml`) rather than changing the global default. 24 tests including a real-corpus integration test asserting the exact rule-to-chunk mapping.
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
