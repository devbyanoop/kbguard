# Stale versions check

!!! warning "Planned — Week 2"
    Not implemented yet.

## Planned behavior

1. **Group into document families** — same title, a filename stem with version markers stripped (`_v2`, `2025`, `final`, etc.), or high source-level similarity. This is a best-effort heuristic, not a parser, and is expected to occasionally misfire on real-world naming — that's exactly what [suppressions](../diff-and-ci.md#suppressions) exist for.
2. **Order by `version` / `updated_at`** within a family.
3. **Flag older members still present** in the collection. Severity escalates from `warn` to `error` specifically when a self-retrieval probe — searching with an older chunk's own embedding — shows both the old and new version landing in the same top-k results, meaning a user query is actually likely to retrieve the outdated one.

## Configuration (planned)

```yaml
checks:
  stale_versions: {enabled: true}
```

This page will include real examples once the check is built and tested against a seeded old/new document pair.
