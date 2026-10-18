# Qdrant adapter

!!! warning "Planned — Week 1"
    Not implemented yet.

## Planned behavior

- **Iteration:** Qdrant's own `scroll` API with `offset`, requesting `with_vectors=True` explicitly — without that flag, chunks would come back with no embedding even when `with_embeddings=True` was requested, silently breaking that contract.
- **Metadata:** the payload dict becomes `Chunk.metadata` directly; mapping payload fields to kbguard's standard fields (`source`, `version`, etc.) happens one layer up, via `metadata_map` in `kbguard.yaml` — the adapter itself does no field renaming.
- **Testing:** verified against a real `qdrant/qdrant` Docker container in CI.

This page becomes a real usage guide once `adapters/qdrant.py` passes the contract test suite against a live container.
