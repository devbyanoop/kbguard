# pgvector adapter

Implemented, registered as a real plugin (`kbguard.adapters.pgvector:PgVectorAdapter`), and covered by both the shared `contract_tests/` suite and adapter-specific tests — all run against a real `pgvector/pgvector:pg16` container, not mocked.

## Connecting

```yaml
store:
  adapter: pgvector
  collection: chunks        # the table name
  settings:
    host: localhost
    port: 5433
    user: kbguard
    dbname: my_app
    password_env: PGVECTOR_PASSWORD   # name of an env var, never the password itself
    # Optional — override only if your table doesn't use these column names:
    id_column: id
    text_column: text
    metadata_column: metadata
    embedding_column: embedding
```

`collection` in every adapter call maps to a **table name** — table and column names come from config so kbguard can work against a table a client already has, without asking them to rename anything.

## Behavior notes (verified)

- **Iteration uses keyset pagination** (`WHERE id > :last ORDER BY id LIMIT n`), not `OFFSET` — a row inserted or deleted mid-scan can make `OFFSET` skip or repeat rows on a live, multi-writer table, which is a real risk for pgvector specifically (unlike Chroma, typically local and single-writer).
- **Table/column names are validated against a strict allowlist** (letters, digits, underscore; can't start with a digit) before being used in SQL — they can't be passed as query parameters the way values can, so `psycopg.sql.Identifier()` safely quotes them, with the allowlist check failing loudly first rather than silently accepting an unusual name.
- **`<=>` (cosine distance) orders results nearest-first**, satisfying the Protocol's best-match-first guarantee directly — no re-sorting needed.
- **Never runs `CREATE EXTENSION` or any DDL.** Read-only is enforced structurally, not just by convention — the adapter has no write code path at all. The `vector` extension must already be enabled on the target database; if it isn't, `register_vector()` fails with a clear error (`vector type not found in the database`) at `connect()` time.
- **`search(..., filters=...)` isn't supported yet** — raises `NotImplementedError` rather than silently ignoring the filter and returning unfiltered results, since no current caller passes filters.
- Uses `autocommit=True` — kbguard never writes, so there's nothing to commit or roll back.

## Testing against a real container

```bash
docker compose up -d   # starts pgvector + Qdrant, see docker-compose.yml
```

If your Docker engine isn't local (e.g. a remote host over SSH via `DOCKER_HOST`), override the test connection with environment variables rather than assuming `localhost`:

```bash
export KBGUARD_TEST_PG_HOST=<host>
export KBGUARD_TEST_PG_PORT=<port>
```

See [Contributing](../../project/contributing.md) for the full test setup.
