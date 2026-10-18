# Chroma adapter

The first working adapter — implemented, registered as a real plugin (`kbguard.adapters.chroma:ChromaAdapter`), and covered by tests against a real in-process Chroma instance. `contract_tests/` (the shared suite every adapter must pass — see [Writing a custom adapter](custom-adapter.md)) doesn't exist yet; today's tests are Chroma-specific.

## Connecting

```yaml
store:
  adapter: chroma
  collection: policies
  settings:
    path: ./chroma_data   # omit for in-memory (ephemeral), no server needed
```

- **No `path`:** in-process, in-memory client. Nothing persists between runs — this is what makes Chroma the fastest store to develop and test against, no Docker, no network.
- **With `path`:** data persists to that local directory between runs (a `PersistentClient`).
- A remote Chroma server (`HttpClient`) isn't supported yet.

## Behavior notes (verified)

- **Iteration** uses `collection.get(limit, offset, include=[...])` — offset-based pagination. This is a deliberate, accepted tradeoff specific to Chroma: offset pagination can skip or repeat rows if the collection is written to mid-scan, but Chroma is typically a local, single-writer store where that risk doesn't really apply — unlike the planned pgvector adapter, which uses keyset pagination specifically because that risk is real for a shared Postgres table.
- **Embeddings are never computed by kbguard asking Chroma to do it.** `get_collection(..., embedding_function=None)` is passed everywhere, so Chroma never silently downloads its own default embedding model — a network call this project's "runs entirely in your environment" principle rules out. kbguard always supplies its own embeddings.
- **`search()` results come back nearest-first**, regardless of what the underlying distance value means numerically — callers rely on the ordering, not on whether a lower or higher score is "better."
- **A real quirk worth knowing if you're testing against Chroma yourself:** two separate `EphemeralClient()` instances in the same process are *not* isolated from each other — creating a collection with the same name in both will fail with `Collection already exists`, even though each client was constructed independently. kbguard's own test suite works around this by using a unique, randomly-suffixed collection name per test rather than relying on client-level isolation.

## What's not covered yet

- A remote `HttpClient` connection.
- The shared `contract_tests/` suite (row-count/id-stability/search/metadata-roundtrip checks run identically against every adapter) — tracked in [Roadmap & status](../../project/roadmap.md).
