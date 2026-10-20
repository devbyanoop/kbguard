import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any, cast

from kbguard.checks.base import CheckContext
from kbguard.config import StaleVersionsCheckConfig
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Chunk, Finding, Severity, compute_fingerprint

# How many of the live store's own nearest neighbors to a stale chunk's
# embedding we check for the current version also appearing — not
# configurable yet, nothing has asked for it to be.
_SELF_RETRIEVAL_TOP_K = 5

# Best-effort, single-pass: strips one trailing version-ish marker from a
# source/filename so "refund-policy-2024" and "refund-policy-2025" group
# as the same document family. A heuristic, not a parser — expected to
# misfire on unusual real-world naming, which is exactly what
# kbguard.ignore.yaml suppressions (spec §12, not built yet) exist for.
_VERSION_MARKER_RE = re.compile(r"[-_]?(v\d+(\.\d+)*|final|draft|\d{4}(-\d{2}-\d{2})?)$", re.IGNORECASE)


class StaleVersionsCheck:
    name = "stale_versions"
    default_severity: Severity = "warn"

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]:
        config = cast(StaleVersionsCheckConfig, ctx.config)
        if not config.enabled:
            return

        chunks = {c.id: c for c in snapshot.chunks()}
        for family in _document_families(chunks):
            # Precomputed once into a dict, not recomputed inside sorted()'s
            # key function: lets the None case be filtered here, where mypy
            # can actually narrow it away, rather than inside a lambda
            # sorted() calls repeatedly during comparisons.
            sort_keys = {cid: key for cid in family if (key := _sort_key(chunks[cid])) is not None}
            if len(sort_keys) < 2:
                continue  # fewer than 2 members we can actually order -> nothing to flag

            ordered = sorted(sort_keys, key=sort_keys.__getitem__)
            newest_id = ordered[-1]
            for older_id in ordered[:-1]:
                yield _build_finding(snapshot, chunks, older_id, newest_id, ctx, config.severity)


def _document_families(chunks: dict[str, Chunk]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for chunk_id, chunk in chunks.items():
        if chunk.title:
            key = f"title:{chunk.title.strip().lower()}"
        elif chunk.source:
            key = f"source:{_normalize_source_stem(chunk.source).strip().lower()}"
        else:
            continue  # no reliable grouping signal at all
        groups[key].append(chunk_id)
    return [ids for ids in groups.values() if len(ids) > 1]


def _normalize_source_stem(source: str) -> str:
    return _VERSION_MARKER_RE.sub("", source)


def _sort_key(chunk: Chunk) -> tuple[int, Any] | None:
    # Tiered: anything with updated_at sorts by that (more reliable than a
    # free-text version string); anything without falls back to comparing
    # `version` as a plain string (best-effort — "v10" < "v9" lexically,
    # not handled). A member with neither returns None and is excluded from
    # ordering entirely upstream, rather than guessed at. Any, not a
    # concrete comparable type, for the second slot: datetime and str are
    # each comparable within their own tier, but never need to be
    # compared against each other, since Python's tuple comparison
    # short-circuits on the first (tier) element whenever tiers differ —
    # a guarantee this type can't express statically, so it's asserted
    # here rather than fought.
    if chunk.updated_at is not None:
        return (1, chunk.updated_at)
    if chunk.version is not None:
        return (0, chunk.version)
    return None


def _build_finding(
    snapshot: SnapshotReader,
    chunks: dict[str, Chunk],
    older_id: str,
    newest_id: str,
    ctx: CheckContext,
    base_severity: Severity,
) -> Finding:
    severity = base_severity

    # Self-retrieval probe: query the *live* store with the stale chunk's
    # own embedding (the best available stand-in for "a real query whose
    # topic matches this chunk's content") and check whether both the
    # stale and current versions come back together — meaning a real user
    # query could plausibly retrieve the outdated one. Only attempted when
    # a live adapter connection was actually provided; the check still
    # reports stale members without one, just without escalation.
    if ctx.adapter is not None and ctx.collection is not None:
        query_vector = snapshot.vector(older_id)
        results = ctx.adapter.search(ctx.collection, query_vector, k=_SELF_RETRIEVAL_TOP_K)
        result_ids = {result_chunk.id for result_chunk, _score in results}
        if older_id in result_ids and newest_id in result_ids:
            severity = "error"

    return Finding(
        check="stale_versions",
        severity=severity,
        chunk_ids=[older_id, newest_id],
        message=f"Chunk {older_id!r} appears superseded by {newest_id!r} but is still in the collection",
        evidence={"older_id": older_id, "newest_id": newest_id},
        fingerprint=compute_fingerprint("stale_versions", [older_id, newest_id]),
    )
