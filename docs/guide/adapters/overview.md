# Adapters: overview

The `VectorStoreAdapter` Protocol and the plugin-discovery mechanism (`registry.py`) are implemented and tested. **No concrete adapter exists yet** — Chroma (next) through LangChain/LlamaIndex are all still planned; see the status table below.

## What an adapter is

An adapter is the only part of kbguard that talks to a specific vector database. Every adapter implements the same five-method contract:

```python
class VectorStoreAdapter(Protocol):
    name: str

    def connect(self, **settings: Any) -> None: ...
    def collections(self) -> list[str]: ...
    def count(self, collection: str) -> int: ...
    def iter_chunks(self, collection: str, batch_size: int = 500,
                     with_embeddings: bool = True) -> Iterator[Chunk]: ...
    def search(self, collection: str, query_vector: list[float], k: int,
               filters: dict[str, Any] | None = None) -> list[tuple[Chunk, float]]: ...
```

It's a `Protocol` (structural typing, PEP 544), not a base class — an adapter class never needs to import anything from kbguard to satisfy this contract, it just needs the right methods. Everything downstream — every check, every eval metric — works only on the plain `Chunk` records this contract produces. None of that code knows or cares which store the data came from.

Two methods carry contracts that aren't visible from the signature alone:

- **`iter_chunks`** must page through the *entire* collection without holding it all in memory — real adapters implement this with store-specific pagination (keyset for pgvector, cursor/`scroll` for Qdrant, offset for Chroma). The method's docstring in `adapters/base.py` states this explicitly, since it's the contract `contract_tests/` (planned, see below) will verify.
- **`search`** results are returned **best-match-first** — every consumer relies on this ordering, never on the numeric score. Scores only need to be comparable *within one call*; a Chroma distance and a Qdrant similarity aren't the same kind of number, and nothing in kbguard assumes a lower-is-better or higher-is-better direction generically.

## Finding an adapter at runtime

`registry.py` resolves a `kbguard.yaml` adapter name (e.g. `store.adapter: qdrant`) to an actual class via Python entry points — not a hardcoded `if/elif` chain:

```python
from kbguard.registry import load_adapter, list_available

list_available("adapters")   # -> ["chroma", "qdrant", ...] — whatever's installed
AdapterCls = load_adapter("qdrant")
```

A package registers an adapter in its own `pyproject.toml`:

```toml
[project.entry-points."kbguard.adapters"]
qdrant = "kbguard.adapters.qdrant:QdrantAdapter"
```

kbguard's own built-in adapters register exactly this way — there's no special-casing of "built-in" vs. "third-party." If `load_adapter` is asked for a name that isn't registered, it raises `RegistryError` listing what *is* available, rather than a bare "not found."

## Supported stores

| Store | Tier | Status |
| --- | --- | --- |
| Chroma | v0.1 native | Planned — next |
| pgvector | v0.1 native | Planned — Week 1 |
| Qdrant | v0.1 native | Planned — Week 1 |
| Pinecone | v0.1 native | Planned — Week 2 |
| LangChain / LlamaIndex (bridge) | v0.1 bridge | Planned — Week 2 |
| Weaviate | v0.2 native | Not started |
| Milvus / Zilliz | v0.2 native | Not started |
| Elasticsearch / OpenSearch, MongoDB Atlas, Redis | v0.3 / community | Not started |

## Adding support for a new store

The registration mechanism above is real today. What's still planned is `contract_tests/` — the shared test suite every adapter (built-in or third-party) must pass before it's trusted: row count matches iteration, ids are stable across scans, `search` finds a planted neighbor, metadata round-trips. See [Writing a custom adapter](custom-adapter.md) for the current state of that requirement.
