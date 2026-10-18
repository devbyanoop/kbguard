# Knowledge-base checks: overview

!!! warning "Planned — Week 2 (checks/base.py)"
    No checks exist in code yet. This page describes the planned design.

## What a check is

A check reads an already-written snapshot (not the live vector store directly) and yields zero or more `Finding`s. Every check implements:

```python
class Check(Protocol):
    name: str
    default_severity: Severity
    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]: ...
```

Like adapters, checks are plugins — discoverable the same entry-point way, so a third-party check is also "one file," no different in status from a built-in one.

## Planned checks (v0.1)

| Check | Catches | Status |
| --- | --- | --- |
| [Duplicates](duplicates.md) | Exact and near-duplicate chunks | Planned — Week 2 |
| [Stale versions](stale-versions.md) | Superseded document versions still live in the store | Planned — Week 2 |
| [Chunking damage](chunking-damage.md) | Cut tables, orphan headings, broken sentences, oversized/undersized chunks | Planned — Week 2 |
| [Contradictions](contradictions.md) | Conflicting numbers, dates, money, percentages, durations across sources | Planned — Week 2 |

Dead-content, coverage-gap, and citation checks are explicitly **out of scope for v0.1** and planned for a later release.

## Finding identity (fingerprints)

Every `Finding` carries a `fingerprint` — a stable hash of the check name, the chunk ids involved, and whatever evidence keys that specific check says define its identity. This is what lets [`kbguard diff`](../diff-and-ci.md) tell new findings apart from ones that already existed, and what `kbguard.ignore.yaml` suppressions key on. It's defined in `models.py` today, even though no check uses it yet — see the [Roadmap](../../project/roadmap.md).
