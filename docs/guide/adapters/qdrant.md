# Qdrant adapter

Implemented, registered as a real plugin (`kbguard.adapters.qdrant:QdrantAdapter`), and covered by both the shared `contract_tests/` suite and adapter-specific tests — all run against a real Qdrant container, not mocked.

## Connecting

```yaml
store:
  adapter: qdrant
  collection: chunks
  settings:
    host: localhost
    port: 6333
    api_key_env: QDRANT_API_KEY   # name of an env var, only if your instance needs one
    id_field: external_id          # optional, see "Point ids" below
  text_field: text                 # where chunk text lives inside the payload
```

`text_field` is a sibling of `settings` in the config schema (`store.text_field`, not `store.settings.text_field`) — `kbguard scan` merges it into what the adapter receives.

## Point ids

Qdrant point ids must be an **unsigned integer or a UUID** — confirmed directly against a real server: a plain string id is rejected outright (`"value chunk-a is not a valid point ID"`). Two situations this creates:

- **Default (no `id_field` configured):** `Chunk.id` is the native point id, stringified. This is the right default for an arbitrary existing collection kbguard knows nothing about.
- **A client whose real external id didn't fit Qdrant's id constraint** typically preserves it inside the payload instead (e.g. under `external_id`). Set `id_field` to that payload key, and the adapter reads the real id from there rather than reporting Qdrant's own internal numeric/UUID id.

## Behavior notes (verified)

- **Iteration uses Qdrant's own `scroll` cursor** (`offset`, passed back in from the previous page's response) — not a hand-rolled pagination scheme.
- **`query_points()`, not `.search()`** — the client library's `.search()` method doesn't exist on current versions (confirmed against the installed `qdrant-client`; an older remembered API would have been wrong here).
- **Payload becomes `Chunk.metadata` whole, including the text field** — unlike Chroma/pgvector, Qdrant has no distinct text storage; text lives inside the same payload metadata comes from. The [knowledge-base checks' contract tests](custom-adapter.md) account for this explicitly (a superset check, not exact equality) rather than pretending every backend's storage model is identical.
- **Qdrant's own result ordering already satisfies best-match-first** — no re-sorting needed.
- **Named/multi-vector points aren't handled** — a point whose vector comes back as something other than a plain list (Qdrant's multi-vector feature) is treated as having no embedding. No current caller has a multi-vector collection to test against; this is an accepted, documented gap, not silently assumed to be safe.
- **`search(..., filters=...)` isn't supported yet** — raises `NotImplementedError`, same reasoning as pgvector.

## Testing against a real container

```bash
docker compose up -d
```

For a non-local Docker engine, override the test connection:

```bash
export KBGUARD_TEST_QDRANT_HOST=<host>
export KBGUARD_TEST_QDRANT_PORT=<port>
```

See [Contributing](../../project/contributing.md).
