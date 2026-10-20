# Pinecone adapter

`PineconeAdapter` (`pinecone` plugin name) is built, unit-tested against a fake client matching the real `pinecone` package's verified shapes, **and** verified end-to-end against a real, live Pinecone index (free "Starter" tier). See [Testing](#testing) below for what each layer covers.

!!! warning "The fake-client tests alone missed a real bug — this is why the live test exists"
    `collections()` originally called `self._require_client().list_indexes().names` as a plain attribute. It compiled, type-checked, and passed all 11 fake-client unit tests, because the fake was built to the same (wrong) assumption. Running the real adapter against a real Pinecone index immediately raised `TypeError: 'method' object is not iterable` — `IndexList.names` is a **method** on the real client (`names()`), not an attribute. `dir()` lists both the same way, which is exactly how this got written wrong in the first place and how a fake built from `dir()` output, not confirmed call behavior, can still hide a real bug. Fixed in both the adapter and the fake (so the fake can't silently regress to the wrong shape again).

!!! warning "Depend on `pinecone`, not `pinecone-client`"
    The original architecture spec named `pinecone-client>=4.0` as the dependency. That package is **deprecated** — installing it and importing `pinecone` now raises `Exception: The official Pinecone python package has been renamed from pinecone-client to pinecone`, discovered by actually installing it, not assumed from memory. `pyproject.toml`'s `pinecone` extra was fixed to depend on `pinecone>=5.0` before this adapter was built against it.

!!! warning "Every call carries an explicit timeout — found the hard way"
    A real live-index test run hung indefinitely during this project's own development, after many repeated test runs against the same free-tier index in one session (almost certainly rate-limiting, not a code bug). The cause: none of `collections()`/`count()`/`iter_chunks()`/`search()` ever passed a `timeout` to the underlying `pinecone` client calls, which default to `timeout=None` — no timeout at all, confirmed from the real client's own method signatures. A throttled or stalled connection could block forever rather than failing cleanly. Fixed with a `timeout` setting (default 30 seconds) passed to every call that accepts one. `Pinecone.list_indexes()` (used by `collections()`) has no timeout parameter at all in the real client — a gap in the client itself, not something this adapter can work around.

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
    timeout: 30.0               # optional, this is the default -- per-call timeout in seconds
```

## Iteration: list, then fetch

Pinecone's client has no single "page through everything with vectors" call — `index.list()` yields pages of bare ids only (confirmed from the installed client's own docstring), and a separate `index.fetch()` call is needed to get the actual vectors/metadata back. `iter_chunks()` does exactly that: list a page of ids, fetch that page, yield chunks; repeat. `list()`'s own page-size cap (100) is respected even if a larger `batch_size` is requested.

## Testing

Two layers:

- **`tests/test_adapters_pinecone.py`** (11 tests): a lightweight fake client mirroring the real `pinecone` package's shapes (`IndexList.names()`, `FetchResponse.vectors`, `ScoredVector.{id,score,values,metadata}`, `DescribeIndexStatsResponse.{total_vector_count,namespaces}`). Fast, no network, no account needed — but as the warning above shows, a fake only catches what it was built correctly to mirror.
- **`tests/test_adapters_pinecone_live.py`** (5 tests): the real adapter against a real, live Pinecone index — seeds real vectors, exercises `iter_chunks`/`search`/`count`/`collections`/`with_embeddings=False`, cleans up after itself. Needs `PINECONE_API_KEY` + `PINECONE_TEST_INDEX` (dimension 4, metric cosine — the free Starter tier is enough) set via `.env` or the real environment; skips cleanly, not an error, when they aren't set — see [Contributing](../../project/contributing.md).

What even the live tests don't cover: real auth-failure modes, rate limits, or any Pinecone-side API drift after this was written. If you hit something this page doesn't mention, that's expected — please open an issue.
