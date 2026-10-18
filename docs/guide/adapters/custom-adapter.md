# Writing a custom adapter

!!! warning "Planned — depends on adapters/base.py and contract_tests/ (Week 1)"
    This page will be a full walkthrough once the Protocol and contract test suite are real and verified. The shape below is the planned mechanism, not yet buildable.

## Planned mechanism

A new store needs only one file implementing the `VectorStoreAdapter` Protocol (five methods — see [Adapters: overview](overview.md)), plus one entry in *its own* package's `pyproject.toml`:

```toml
[project.entry-points."kbguard.adapters"]
weaviate = "kbguard_weaviate:WeaviateAdapter"
```

No changes to kbguard's own source are needed — `registry.py` discovers the adapter at runtime via this entry point, the same way it discovers kbguard's own built-in adapters.

## The one requirement: pass the contract tests

Before trusting a new adapter, it must pass `contract_tests/` — the same suite every built-in adapter passes:

- row count matches the number of chunks actually iterated,
- chunk ids are stable across two scans of unchanged data,
- `search` returns a deliberately planted nearest neighbor,
- metadata round-trips through the configured mapping.

This page will include the exact steps to run that suite against a new adapter, plus a worked example, once it exists.
