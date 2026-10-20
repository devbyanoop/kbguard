# Knowledge-base checks: overview

The `Check` Protocol and plugin discovery are implemented and tested. One check (`duplicates`) is built and verified against real data — see the status table below for the rest.

## What a check is

A check reads an already-written snapshot (not the live vector store directly) and yields zero or more `Finding`s. Every check implements:

```python
class Check(Protocol):
    name: str
    default_severity: Severity
    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]: ...
```

Like adapters, checks are **plugins**, discoverable via the same `importlib.metadata` entry-point mechanism (`kbguard.checks` group, `kbguard.registry.load_check`/`list_available("checks")`) — so a third-party check is also "one file," no different in status from a built-in one. This also keeps an optional, heavy dependency honestly optional: `checks/duplicates.py` imports `faiss`/`datasketch` at module level, but that module is only ever imported the moment `load_check("duplicates")` actually runs — confirmed directly: importing `kbguard.registry` and even an adapter pulls in neither library; only loading the duplicates check does.

## Checks (v0.1)

| Check | Catches | Status |
| --- | --- | --- |
| [Duplicates](duplicates.md) | Exact and near-duplicate chunks | Done |
| [Stale versions](stale-versions.md) | Superseded document versions still live in the store | Done |
| [Chunking damage](chunking-damage.md) | Cut tables, orphan headings, broken sentences, oversized/undersized chunks | Planned — Week 2 |
| [Contradictions](contradictions.md) | Conflicting numbers, dates, money, percentages, durations across sources | Planned — Week 2 |

Dead-content, coverage-gap, and citation checks are explicitly **out of scope for v0.1** and planned for a later release.

## Finding identity (fingerprints)

Every `Finding` carries a `fingerprint` — a stable hash of the check name, the chunk ids involved, and whatever evidence keys that specific check says define its identity. This is what lets [`kbguard diff`](../diff-and-ci.md) tell new findings apart from ones that already existed, and what `kbguard.ignore.yaml` suppressions key on. `duplicates` uses this today (`identity_keys=["exact"]`/`["near"]`, so the same chunk pair caught both ways — which can't actually happen, see [Duplicates](duplicates.md) — would still get distinct fingerprints rather than colliding).
