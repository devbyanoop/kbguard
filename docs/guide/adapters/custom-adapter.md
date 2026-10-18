# Writing a custom adapter

Both pieces below are real and tested: registering an adapter as a plugin, and the shared `contract_tests/` suite it must pass. The suite currently covers one backend (Chroma); adding a second is mechanical (see the last section).

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
- chunk text and metadata round-trip exactly,
- embeddings round-trip **approximately** (`abs=1e-5`) — some backends store vectors as float32 internally, which loses precision relative to Python's native float64; that's an accepted backend characteristic, not a bug the suite flags,
- `with_embeddings=False` actually omits embeddings.

To add a new backend to the suite, in `contract_tests/conftest.py`:

```python
def _seed_weaviate(collection: str) -> None:
    # seed SEED_CHUNKS into `collection` using Weaviate's own client —
    # mirrors _seed_chroma immediately above it

_SEEDERS["weaviate"] = _seed_weaviate
_CONNECT_SETTINGS["weaviate"] = {...}  # whatever connect() needs
```

Every test in `test_adapter_contract.py` then runs against `weaviate` automatically — the test functions themselves never name a specific backend, they take the adapter under test as fixture data via the `ContractCase` dataclass.
