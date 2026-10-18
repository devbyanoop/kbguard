# Writing a custom adapter

!!! warning "Partially real: registration works and is tested; contract_tests/ doesn't exist yet"
    The mechanism below — implement the Protocol, register an entry point, kbguard finds it — is real and covered by tests today. The one requirement that isn't buildable yet is passing `contract_tests/`, since that suite hasn't been written (planned alongside the Chroma adapter). Until it exists, "satisfies the Protocol" is the only bar a custom adapter can be checked against.

## The mechanism (verified)

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

...plus one entry point in *its own* package's `pyproject.toml`:

```toml
[project.entry-points."kbguard.adapters"]
weaviate = "kbguard_weaviate.adapter:WeaviateAdapter"
```

No changes to kbguard's own source are needed. `kbguard.registry.load_adapter("weaviate")` discovers it at runtime via `importlib.metadata` entry points, the same mechanism kbguard's own built-in adapters use — this is tested in `tests/test_registry.py` against a fake registered adapter, proving the discovery path itself works correctly (name lookup, class resolution, and a clear `RegistryError` — naming what *is* available — when a requested name isn't registered).

## The one requirement: pass the contract tests (planned)

Satisfying the Protocol's method signatures is necessary but not sufficient — nothing stops a method from being present but behaving wrong (e.g. `iter_chunks` that silently truncates at 500 rows instead of paging). `contract_tests/` will be the suite every adapter must pass before it's trusted:

- row count matches the number of chunks actually iterated,
- chunk ids are stable across two scans of unchanged data,
- `search` returns a deliberately planted nearest neighbor,
- metadata round-trips through the configured mapping.

This page will be updated with the exact steps to run that suite against a new adapter once it exists — tracked in [Roadmap & status](../../project/roadmap.md).
