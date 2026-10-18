# Pinecone adapter

!!! warning "Planned — Week 2"
    Not implemented yet.

## Planned behavior

- **Iteration:** `list` ids within a namespace, then `fetch` in batches — Pinecone doesn't offer a single "page through everything with vectors" call the way Chroma/Qdrant do.
- **Text location:** Pinecone has no native text field — the chunk's text normally lives inside the metadata payload, under a field name you specify via `kbguard.yaml`'s `text_field`.

This page becomes a real usage guide once `adapters/pinecone.py` passes the contract test suite.
