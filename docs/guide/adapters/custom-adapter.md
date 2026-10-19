# Writing a custom adapter

Both pieces below are real and tested: registering an adapter as a plugin, and the shared `contract_tests/` suite it must pass. The suite runs against Chroma, pgvector, and Qdrant today; adding another backend is mechanical (see the last section).

## 1. Implement the Protocol

A new store needs one file implementing `VectorStoreAdapter` (five methods — see [Adapters: overview](overview.md)):

```python
# kbguard_weaviate/adapter.py
from collections.abc import Iterator
from typing import Any
from kbguard.models import Chunk

class WeaviateAdapter:
    name = "weaviate"

    def connect(self, **settings: Any) -> None: ...
    def collections(self) -> list[str]: ...
    def count(self, collection: str) -> int: ...
    def iter_chunks(self, collection: str, batch_size: int = 500,
                     with_embeddings: bool = True) -> Iterator[Chunk]: ...
    def search(self, collection: str, query_vector: list[float], k: int,
               filters: dict[str, Any] | None = None) -> list[tuple[Chunk, float]]: ...
```

`search` must return results **best-match-first** — this is an explicit Protocol guarantee (`adapters/base.py`), not just a convention. Callers never compare the numeric score across adapters or assume a direction (lower/higher = better); they only rely on ordering.

## 2. Register it

In *your own* package's `pyproject.toml` — no changes to kbguard's own source:

```toml
[project.entry-points."kbguard.adapters"]
weaviate = "kbguard_weaviate.adapter:WeaviateAdapter"
```

`kbguard.registry.load_adapter("weaviate")` discovers it at runtime via `importlib.metadata` entry points, the same mechanism kbguard's own built-in adapters use.

## 3. Pass the contract tests

`contract_tests/` seeds a fixed, three-chunk dataset directly through the store's own native client (never through the adapter under test — the adapter is read-only by design, with no write method at all), then runs the same suite against every registered backend:

- row count from `count()` matches the number of chunks `iter_chunks()` actually yields,
- chunk ids are identical across two separate `iter_chunks()` calls,
- `search()` finds a deliberately planted nearest neighbor, and returns exactly `k` results,
- chunk text round-trips exactly; metadata round-trips as a **superset** (every originally-seeded key/value must be present, but a backend may legitimately include more) — some backends (Qdrant, confirmed) store text/id/metadata in one flat payload namespace rather than genuinely separate storage, so "nothing else is mixed in" isn't a promise every backend can make,
- embeddings round-trip **approximately** (`abs=1e-5`) — some backends store vectors as float32 internally, which loses precision relative to Python's native float64; that's an accepted backend characteristic, not a bug the suite flags,
- `with_embeddings=False` actually omits embeddings.

A backend whose container isn't reachable (e.g. Docker not running) is **skipped with a clear reason**, not errored — confirmed necessary in practice, not just a nice-to-have: a plain "is the port open" check isn't the same as "is *our* service the one listening there" (an unrelated service occupying the same port locally caused exactly this once), so the actual seeding attempt is also wrapped to skip gracefully on any connection failure.

To add a new backend to the suite, in `contract_tests/conftest.py`:

```python
def _seed_weaviate(collection: str) -> None:
    # seed SEED_CHUNKS into `collection` using Weaviate's own client —
    # mirrors _seed_chroma/_seed_pgvector/_seed_qdrant immediately above it

_SEEDERS["weaviate"] = _seed_weaviate
_CONNECT_SETTINGS["weaviate"] = {...}  # whatever connect() needs
# Add "weaviate" to _FIXTURE_PARAMS too (plain string if always available
# in-process like Chroma, or the reachability-checked pattern pgvector/
# Qdrant use if it needs an external service).
```

Every test in `test_adapter_contract.py` then runs against `weaviate` automatically — the test functions themselves never name a specific backend, they take the adapter under test as fixture data via the `ContractCase` dataclass.
