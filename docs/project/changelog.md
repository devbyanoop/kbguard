# Changelog

All notable changes to kbguard are recorded here, following [Keep a Changelog](https://keepachangelog.com/) conventions. Nothing has been released yet — everything below is under `Unreleased`.

## [Unreleased]

### Added
- Project scaffold: `pyproject.toml` (packaging, extras per vector store, `ruff`/`mypy`/`pytest` config), `.gitignore`, `docker-compose.yml` for pgvector/Qdrant test fixtures.
- `models.py`: `Chunk`, `Finding`, `EvalResult`, `Snapshot`, and the `compute_fingerprint()` algorithm used by `diff` and suppressions.
- `config.py`: pydantic schema for `kbguard.yaml` — strict (unknown fields rejected), minimal-by-default (only `store` required), secrets referenced by environment-variable name and resolved only at point of use.
- `adapters/base.py`: the `VectorStoreAdapter` Protocol (five methods: `connect`, `collections`, `count`, `iter_chunks`, `search`), plus `src/kbguard/py.typed` so the Protocol type-checks for external consumers, not just within this repo.
- `registry.py`: entry-point based plugin discovery for adapters (`load_adapter`, `list_available`) — the mechanism that lets a new vector store be added as one file with no changes to kbguard's own source.
- This documentation site (MkDocs + Material), written incrementally alongside the code.

### Design decisions locked in
- Read-only access to vector stores, with no write code path in any adapter.
- Adapters and checks are `Protocol`-typed plugins, discovered via `importlib.metadata` entry points.
- `Finding.fingerprint = sha256(check + sorted(chunk_ids) + sorted(identity_keys))[:16]`.
- Health score formula clamped to `[0, 100]` regardless of configured weights.
- `kbguard diff --against <baseline> [--snapshot <new>]` as the single CLI form (replacing an earlier spec draft that showed two inconsistent forms).
