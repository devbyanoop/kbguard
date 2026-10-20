# Adapters: overview

The `VectorStoreAdapter` Protocol, the plugin-discovery mechanism (`registry.py`), and all five v0.1 adapters (Chroma, pgvector, Qdrant, Pinecone, the LangChain/LlamaIndex bridge) are implemented, registered, and tested — see the status table below for exactly what each one's testing does and doesn't cover.

## What an adapter is

An adapter is the only part of kbguard that talks to a specific vector database. Every adapter implements the same five-method contract:

```python
class VectorStoreAdapter(Protocol):
    name: str
    iteration_mode: Literal["full", "sampled"]

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

- **`iter_chunks`** must page through the *entire* collection without holding it all in memory — real adapters implement this with store-specific pagination (keyset for pgvector, cursor/`scroll` for Qdrant, offset for Chroma). The method's docstring in `adapters/base.py` states this explicitly, since it's the contract `contract_tests/` (see below) verifies.
- **`search`** results are returned **best-match-first** — every consumer relies on this ordering, never on the numeric score. Scores only need to be comparable *within one call*; a Chroma distance and a Qdrant similarity aren't the same kind of number, and nothing in kbguard assumes a lower-is-better or higher-is-better direction generically.

Every adapter also declares `iteration_mode`: `"full"` for the four native adapters (`iter_chunks` genuinely walks the entire collection), `"sampled"` for the LangChain/LlamaIndex bridge, whose wrapped `VectorStore` exposes no enumeration API at all — only similarity search. `SnapshotWriter` records this verbatim into the snapshot manifest, so a sampled scan is never mistaken for a complete one downstream.

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
| [Chroma](chroma.md) | v0.1 native | Done |
| [pgvector](pgvector.md) | v0.1 native | Done |
| [Qdrant](qdrant.md) | v0.1 native | Done |
| [Pinecone](pinecone.md) | v0.1 native | Done — verified against both a fake client and a real live index |
| [LangChain / LlamaIndex](langchain-llamaindex.md) (bridge) | v0.1 bridge | Done — tested against a real `InMemoryVectorStore` |
| Weaviate | v0.2 native | Not started |
| Milvus / Zilliz | v0.2 native | Not started |
| Elasticsearch / OpenSearch, MongoDB Atlas, Redis | v0.3 / community | Not started |

## Adding support for a new store

Both the registration mechanism and `contract_tests/` — the shared test suite every adapter (built-in or third-party) must pass — are real today: row count matches iteration, ids are stable across scans, `search` finds a planted neighbor, metadata and text round-trip (a superset check for backends like Qdrant whose payload mixes text/id/metadata into one namespace — see [Writing a custom adapter](custom-adapter.md)), embeddings round-trip approximately (allowing for backends that store vectors as float32). Running against Chroma, pgvector, and Qdrant; Docker-dependent backends skip cleanly (not error) when their container isn't reachable.

Pinecone and the LangChain/LlamaIndex bridge aren't in `contract_tests/` — Pinecone is a managed cloud service with no Docker option, and the bridge's whole premise (wrapping an arbitrary already-constructed `VectorStore` instance) doesn't fit a single parametrized backend fixture the way the other four do. Each has its own dedicated test file(s) instead — see their pages for exactly what's covered. Pinecone's real, free-tier account is reached via `.env` (see [Contributing](../../project/contributing.md)), the same pattern as pgvector/Qdrant's remote Docker host.
