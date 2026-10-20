# Pinecone adapter

`PineconeAdapter` (`pinecone` plugin name) is built and unit-tested against the real `pinecone` package's verified method signatures and response shapes — but not against a live Pinecone index (a managed cloud service with no local/self-hosted way to run it, unlike pgvector/Qdrant's Docker containers). See [Testing](#testing) below for exactly what that does and doesn't cover.

!!! warning "Depend on `pinecone`, not `pinecone-client`"
    The original architecture spec named `pinecone-client>=4.0` as the dependency. That package is **deprecated** — installing it and importing `pinecone` now raises `Exception: The official Pinecone python package has been renamed from pinecone-client to pinecone`, discovered by actually installing it, not assumed from memory. `pyproject.toml`'s `pinecone` extra was fixed to depend on `pinecone>=5.0` before this adapter was built against it.

## Collection and namespace mapping

A Pinecone *index* is this adapter's "collection" — the thing `collections()`/`count()`/`iter_chunks()`/`search()` all take by name, the same role a Chroma collection or a pgvector table plays elsewhere. A Pinecone *namespace* (a further subdivision within one index, with no equivalent in the other three stores) is an adapter-specific setting:

```yaml
store:
  adapter: pinecone
  collection: policies          # the Pinecone index name
  settings:
    api_key_env: PINECONE_API_KEY
    namespace: articles-en      # optional, defaults to Pinecone's default namespace
    text_field: text            # optional -- Pinecone has no distinct text storage
```

## Iteration: list, then fetch

Pinecone's client has no single "page through everything with vectors" call — `index.list()` yields pages of bare ids only (confirmed from the installed client's own docstring), and a separate `index.fetch()` call is needed to get the actual vectors/metadata back. `iter_chunks()` does exactly that: list a page of ids, fetch that page, yield chunks; repeat. `list()`'s own page-size cap (100) is respected even if a larger `batch_size` is requested.

## Testing

Covered by `tests/test_adapters_pinecone.py` (11 tests) using a lightweight fake client that mirrors the real `pinecone` package's verified shapes (`IndexList.names`, `FetchResponse.vectors`, `ScoredVector.{id,score,values,metadata}`, `DescribeIndexStatsResponse.{total_vector_count,namespaces}`) — every method signature and field name was checked against the installed `pinecone` 10.x package by hand before writing the fake, not guessed. What this *doesn't* cover: real network behavior, real auth errors, real rate limits, or any Pinecone-side API drift since. If you use this adapter against a real index and hit something this page doesn't mention, that's expected — please open an issue.
