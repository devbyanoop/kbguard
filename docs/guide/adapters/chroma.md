# Chroma adapter

!!! warning "Planned — Week 1, building first"
    Chroma is the first adapter being built, specifically because it runs in-process with no server or Docker container required — fastest feedback loop, and it becomes the baseline every other adapter's contract test is checked against.

## Planned behavior

- **Iteration:** `collection.get(limit, offset, include=["documents", "metadatas", "embeddings"])`, paged with offset-based pagination.
- **Why offset pagination is acceptable here:** Chroma is typically a local, single-writer store, so the usual risk with offset pagination (rows shifting under you from concurrent writes) doesn't apply the way it does for a shared Postgres table. The [pgvector adapter](pgvector.md) uses keyset pagination instead, specifically because that risk is real there.
- **Search:** native similarity search, used for self-retrieval probes (e.g. the stale-versions check) and for retrieval evals.

This page becomes a real usage guide — connection settings, a worked `kbguard.yaml` snippet, known limitations — once `adapters/chroma.py` passes the contract test suite.
