from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Finding, Severity


@dataclass
class CheckContext:
    """Everything a Check's run() might need beyond the snapshot itself.

    `config` is the check's own resolved config sub-object (e.g.
    DuplicatesCheckConfig) — typed Any here because CheckContext is shared
    infrastructure that doesn't know which check it's for; each check casts
    it to its own config type.

    `adapter`/`collection` are only set for checks that need to query the
    live store directly, not just read from the snapshot (e.g.
    stale_versions' self-retrieval probe). `judge` isn't a field yet —
    added when judge/client.py exists and contradictions.py actually needs
    it, not speculatively.
    """

    config: Any
    adapter: VectorStoreAdapter | None = None
    collection: str | None = None


class Check(Protocol):
    """Same Protocol pattern as VectorStoreAdapter (adapters/base.py) —
    structural typing, no base-class coupling, discovered via the same
    registry.py entry-point mechanism once a "checks" group exists."""

    name: str
    default_severity: Severity

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]: ...
