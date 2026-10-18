# Adapters: overview

!!! warning "Planned — Week 1 (adapters/base.py)"
    The adapter Protocol doesn't exist in code yet. This page describes the planned design; it will be rewritten against the real `VectorStoreAdapter` Protocol and its contract tests once `adapters/base.py` lands.

## What an adapter is

An adapter is the only part of kbguard that talks to a specific vector database. Every adapter implements the same five-method contract:

```python
class VectorStoreAdapter(Protocol):
    def connect(self, **settings) -> None: ...
    def collections(self) -> list[str]: ...
    def count(self, collection: str) -> int: ...
    def iter_chunks(self, collection, batch_size=500, with_embeddings=True) -> Iterator[Chunk]: ...
    def search(self, collection, query_vector, k, filters=None) -> list[tuple[Chunk, float]]: ...
```

Everything downstream — every check, every eval metric — works only on the plain `Chunk` records this contract produces. None of that code knows or cares which store the data came from.

## Supported stores (planned)

| Store | Tier | Status |
| --- | --- | --- |
| Chroma | v0.1 native | Planned — Week 1 |
| pgvector | v0.1 native | Planned — Week 1 |
| Qdrant | v0.1 native | Planned — Week 1 |
| Pinecone | v0.1 native | Planned — Week 2 |
| LangChain / LlamaIndex (bridge) | v0.1 bridge | Planned — Week 2 |
| Weaviate | v0.2 native | Not started |
| Milvus / Zilliz | v0.2 native | Not started |
| Elasticsearch / OpenSearch, MongoDB Atlas, Redis | v0.3 / community | Not started |

## Adding support for a new store

Once the Protocol is stable, a new adapter will be addable as a single installable package, registered via a Python entry point — no changes to kbguard's own source required, and no special-casing of "built-in" vs. "community" adapters (the built-in ones register the exact same way). Every adapter, built-in or third-party, must pass the shared `contract_tests/` suite before it's trusted. This page will include a full walkthrough once that mechanism exists and is verified — see [Writing a custom adapter](custom-adapter.md).
