# Changelog

All notable changes to kbguard are recorded here, following [Keep a Changelog](https://keepachangelog.com/) conventions. Nothing has been released yet — everything below is under `Unreleased`.

## [Unreleased]

### Added
- Project scaffold: `pyproject.toml` (packaging, extras per vector store, `ruff`/`mypy`/`pytest` config), `.gitignore`, `docker-compose.yml` for pgvector/Qdrant test fixtures.
- `models.py`: `Chunk`, `Finding`, `EvalResult`, `Snapshot`, and the `compute_fingerprint()` algorithm used by `diff` and suppressions.
- `config.py`: pydantic schema for `kbguard.yaml` — strict (unknown fields rejected), minimal-by-default (only `store` required), secrets referenced by environment-variable name and resolved only at point of use.
- `adapters/base.py`: the `VectorStoreAdapter` Protocol (five methods: `connect`, `collections`, `count`, `iter_chunks`, `search`), plus `src/kbguard/py.typed` so the Protocol type-checks for external consumers, not just within this repo.
- `registry.py`: entry-point based plugin discovery for adapters (`load_adapter`, `list_available`) — the mechanism that lets a new vector store be added as one file with no changes to kbguard's own source.
- `adapters/chroma.py`: the first working adapter, registered as a real plugin and verified end-to-end (`load_adapter("chroma")` resolves through the actual installed package metadata, not a mock). In-process, no server required.
- `contract_tests/`: the shared, backend-agnostic suite every adapter must pass (count/iteration, id stability, best-match-first search ordering, text/metadata/embedding round-trip), parametrized over a `BACKENDS` list so adding a new adapter to the suite is a seeder function + one list entry, no new test code. Passing against Chroma.
- `ingest/metadata.py`: fills `Chunk`'s standard fields from a chunk's own raw metadata via dotted-path `metadata_map` lookups (e.g. `meta.last_modified`), with explicit type coercion (position → int, updated_at → datetime, handling both epoch numbers and ISO-8601 strings including a `Z` suffix on Python 3.10, not just 3.11+) and a `validate_metadata_map` check that rejects an unrecognized target field instead of silently ignoring it.
- `ingest/embeddings.py`: `get_embedder` (text → vector, lazy-loaded so an optional extra's library is never imported — and never even needed — unless a chunk actually lacks a stored embedding) and `embed_chunk` (the separate reuse-or-recompute policy). Supports `sentence-transformers` (local) and `litellm` (hosted/local-server, e.g. Ollama) providers.
- `ingest/exporter.py`: `export_chunks` sequences `iter_chunks()` → `apply_metadata_map` → `embed_chunk` into one generator. Split into a plain outer function (runs `validate_metadata_map` immediately on call) wrapping an inner generator (the actual per-chunk `yield` loop), since a single generator function wouldn't run *any* of its body — including validation — until first iterated, which would have meant a bad `metadata_map` silently raising nothing until some arbitrary, possibly-never later point. `with_embeddings` passed to the adapter is wired directly to `reuse_stored`, so a store is never asked for vectors that are just going to be discarded.
- `ingest/snapshot.py`: `SnapshotWriter`/`SnapshotReader` — the on-disk snapshot format (`chunks.parquet`, `vectors.npy`, `index.sqlite`, `findings.jsonl`, `manifest.json`) every check/eval/diff will read from. Fails fast on a missing embedding, a dimension mismatch, a duplicate chunk id, a duplicate finding fingerprint, or any write after `close()`.
- This documentation site (MkDocs + Material), written incrementally alongside the code.

### Fixed (caught before release, not after)
- `chunks.parquet` now uses an explicit schema rather than one inferred from the buffered data — confirmed by hand that pyarrow infers `null`-typed columns from an empty list, which would have given an empty-collection snapshot a schema incompatible with every non-empty one.
- `SnapshotReader.vector()` uses a plain `np.load()`, not `mmap_mode="r"` — memory-mapping worked for row access but kept a file handle open that Windows refuses to delete while mapped, confirmed by hand to break a `pytest` `tmp_path` cleanup with a file-in-use error. Revisit only if vector files actually grow large enough for this to matter.

### Changed
- `config.py`'s `EmbeddingsConfig` gained an explicit `provider: "sentence-transformers" | "litellm"` field (default `sentence-transformers`) instead of guessing the backend from `model`'s name — a prefix-based guess would misroute valid local HuggingFace models that don't carry a `sentence-transformers/` prefix, and guessing wrong here means document text silently leaving the user's machine via a hosted API. Backward compatible (additive field with a default).
- `pyproject.toml`'s `[tool.mypy]` gained a `[[tool.mypy.overrides]]` entry for optional, lazily-imported extras without type stubs (`sentence_transformers`, `litellm`) — the pattern to extend, not per-call-site `# type: ignore`, as more optional adapters/providers are added.

### Fixed
- Registry test originally relied on `EntryPoint.load()` resolving a real dotted import path, which passed under `python -m pytest` but failed under the plain `pytest` command — fixed by mocking `EntryPoint.load` directly instead.
- Same class of bug recurred in `contract_tests/test_adapter_contract.py` (a top-level `from contract_tests.conftest import ContractCase`, needed only for a type hint) — fixed with a `TYPE_CHECKING`-guarded import plus `from __future__ import annotations`, so it's never evaluated at actual test-run time.

### Changed
- `adapters/base.py`'s `search` docstring now states explicitly that results are returned best-match-first — this was true of the Chroma adapter's behavior but hadn't been written into the Protocol itself, which risked a second adapter disagreeing on ordering with no contract forcing consistency.

### Design decisions locked in
- Read-only access to vector stores, with no write code path in any adapter.
- Adapters and checks are `Protocol`-typed plugins, discovered via `importlib.metadata` entry points.
- `Finding.fingerprint = sha256(check + sorted(chunk_ids) + sorted(identity_keys))[:16]`.
- Health score formula clamped to `[0, 100]` regardless of configured weights.
- `kbguard diff --against <baseline> [--snapshot <new>]` as the single CLI form (replacing an earlier spec draft that showed two inconsistent forms).
