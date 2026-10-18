# Roadmap & status

This page is the single source of truth for "is X actually built yet?" — updated the same day any item's status changes, not retroactively. If a page elsewhere in this guide seems to claim more than this page shows as done, trust this page.

**Last updated:** 2026-10-18

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
- [ ] `registry.py` — entry-point plugin discovery
- [ ] `adapters/base.py` — the `VectorStoreAdapter` Protocol
- [ ] `adapters/chroma.py`
- [ ] `contract_tests/` (Chroma)
- [ ] `ingest/metadata.py`
- [ ] `ingest/embeddings.py`
- [ ] `ingest/exporter.py`
- [ ] `ingest/snapshot.py`
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
