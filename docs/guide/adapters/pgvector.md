# pgvector adapter

!!! warning "Planned — Week 1"
    Not implemented yet.

## Planned behavior

- **Iteration:** keyset pagination — `WHERE id > :last ORDER BY id LIMIT n` — rather than `OFFSET`, specifically because `OFFSET` can skip or repeat rows if the table is written to while a scan is in progress. This matters for pgvector in particular since it's commonly a live, multi-writer production table, unlike Chroma.
- **Table/column names:** come from `kbguard.yaml`, not hardcoded — validated against an allowlist pattern before being used in SQL (since identifiers can't be passed as query parameters).
- **Testing:** verified against a real `pgvector/pgvector` Docker container in CI, including a test that mutates the table mid-scan to prove no row is skipped or doubled.

This page becomes a real usage guide — connection string format, required Postgres permissions, a worked `kbguard.yaml` snippet — once `adapters/pgvector.py` passes the contract test suite against a live container.
