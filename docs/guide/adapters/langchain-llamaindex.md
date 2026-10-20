# LangChain / LlamaIndex bridge

`LangChainBridgeAdapter` (`bridge_langchain` plugin name) wraps a LangChain `VectorStore` instance the client already has, instead of connecting to a store natively. Built and tested against a real `langchain_core.vectorstores.InMemoryVectorStore` — not a mock — plus targeted fake-object tests for the one case the real backend doesn't naturally trigger.

## Why this adapter matters most for real adoption

Most RAG applications are already built on top of a LangChain (or LlamaIndex) vector store object, not a bare database client. This bridge wraps that existing object directly, so you can point kbguard at a knowledge base without standing up a second, separate connection to the underlying store.

## The real limitation: no universal "iterate everything"

Checked against the installed `langchain-core` 1.x package directly: `VectorStore`'s base class exposes **no** enumerate-all, count, or stable-id-lookup-without-already-knowing-ids method — only similarity search (`similarity_search_by_vector`, `similarity_search_with_score`, ...). This isn't a gap in one particular store implementation; it's the shape of the interface itself. So:

- **`count()` raises `NotImplementedError`** rather than fabricate or guess a number it has no way to verify.
- **`iter_chunks()` approximates coverage via search-based sampling**: an optional list of human-provided `sample_queries` (far better signal than random vectors, if you have any idea what's actually in the collection), plus a configurable number of random-vector probes to broaden coverage beyond those specific queries. Every chunk found this way is deduplicated by id.
- **The snapshot manifest honestly records `iteration_mode: "sampled"`**, not `"full"` — the one field every adapter carries (`VectorStoreAdapter.iteration_mode`, added specifically for this adapter) so nothing downstream ever mistakes a sampled scan for a complete one.

## The other real limitation: no embeddings come back

None of `VectorStore`'s search methods return a hit's own embedding vector — confirmed by inspecting the real `Document` class, which simply has no such field. Every `Chunk` this adapter produces has `embedding=None`, regardless of the `with_embeddings` argument. A caller relying on `embeddings.reuse_stored` will recompute every chunk's embedding through the configured embedding model instead — a real cost difference worth knowing about, not a bug in how `with_embeddings` is honored.

## Configuration

Since `vectorstore` is a live Python object, not something expressible in YAML, this adapter is used programmatically, not purely declaratively:

```python
from kbguard.adapters.bridge_langchain import LangChainBridgeAdapter

adapter = LangChainBridgeAdapter()
adapter.connect(
    vectorstore=my_existing_vectorstore,      # required
    embedding_dim=384,                         # required -- no API to ask the store its own dimension
    sample_queries=["refund policy", "shipping times"],   # optional, strongly recommended
    probe_count=20,                            # optional, default 20
    collection="policies",                     # optional label, default "default"
)
```

## Testing

`tests/test_adapters_bridge_langchain.py` (13 tests) seeds a real `InMemoryVectorStore` with a small, fully deterministic `Embeddings` implementation (no network, no real embedding model) and exercises `iter_chunks()`/`search()` against it for real — confirming real seeded content is found, every yielded chunk has `embedding=None`, deduplication works across overlapping queries and probes, and `search()` returns best-match-first. One case the real `InMemoryVectorStore` doesn't trigger (it always assigns an id) is tested directly against a minimal fake `Document`: the content-hash fallback id used when a wrapped store's own `Document.id` is `None`, which many real-world LangChain integrations historically leave unset.
