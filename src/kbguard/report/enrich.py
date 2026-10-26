"""Turns a flat `list[Finding]` into what each of the report's three
audiences actually needs — resolved source/snippet for an engineer who has
to go fix something, a plain-language verdict for a decision-maker, and a
health-over-time view for someone evaluating whether a change helped.
Kept as pure functions, independent of Jinja, so each is testable without
rendering any HTML.
"""

from collections import Counter
from typing import Any

from kbguard.models import Chunk, Finding
from kbguard.report.results import ScanResults

_SNIPPET_MAX_CHARS = 150

# Severity carries the same meaning everywhere in kbguard (error > warn >
# info) — this is the one place that order is made explicit as a sort key,
# since neither Finding nor the report template otherwise encodes it.
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

_PLAIN_CHECK_LABELS = {
    "duplicates": "Duplicate or near-duplicate content",
    "stale_versions": "Outdated document versions still present",
    "chunking_damage": "Content formatting / chunking issues",
    "contradictions": "Conflicting facts across documents",
}

_TOP_FINDINGS_LIMIT = 8


def _snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_MAX_CHARS].rstrip() + "…"


def resolve_chunks(chunk_ids: list[str], chunks_by_id: dict[str, Chunk]) -> list[dict[str, Any]]:
    """Looks a finding's bare chunk ids up against the snapshot's real
    chunks, so the report can show a title/source/snippet instead of an
    opaque id a reader has no way to act on. `chunks_by_id` can be empty
    (report.html.j2's own fallback path) -- an unresolved id still renders,
    just without the extra context, rather than failing."""
    resolved = []
    for cid in chunk_ids:
        chunk = chunks_by_id.get(cid)
        if chunk is None:
            resolved.append({"id": cid, "title": None, "source": None, "snippet": None})
            continue
        resolved.append(
            {
                "id": cid,
                "title": chunk.title or chunk.source or cid,
                "source": chunk.source,
                "snippet": _snippet(chunk.text) if chunk.text else None,
            }
        )
    return resolved


def suggested_action(finding: Finding) -> str:
    """One sentence telling an engineer what to actually do, per check
    and (for chunking_damage) per rule -- the report's biggest previous
    gap was telling you *what* was found and never *what to do about it*."""
    if finding.check == "duplicates":
        kind = finding.evidence.get("duplicate_type", "duplicate")
        return (
            f"Merge or deduplicate these sources ({kind} match) — a user asking about this "
            "topic may get near-identical, redundant hits instead of varied, useful ones."
        )
    if finding.check == "stale_versions":
        return (
            "Remove or archive the superseded chunk — an outdated version is still being "
            "retrieved alongside the current one."
        )
    if finding.check == "contradictions":
        return (
            "Resolve the conflicting fact between these chunks before a user gets two "
            "different answers to the same question."
        )
    if finding.check == "chunking_damage":
        rule = finding.evidence.get("rule")
        if rule == "size":
            if "max_tokens" in finding.evidence:
                return "Consider splitting this chunk — it may be too large for a retriever to surface just the relevant part."
            return "Consider merging this chunk with a neighbor — it may be too small to carry useful standalone context."
        if rule == "split_table":
            return "A table appears to be cut across chunk boundaries — adjust the chunker to keep tables intact."
        if rule == "orphan_heading":
            return "This chunk is just a heading with no body text — merge it with the content that follows."
        if rule == "broken_sentence":
            return "This chunk starts or ends mid-sentence — adjust chunk boundaries to respect sentence breaks."
        if rule == "missing_metadata":
            return "Add the required metadata field to this chunk's source document."
        if rule == "encoding_noise":
            return "This chunk contains control characters or encoding artifacts — check the document's text-extraction pipeline."
    return "Review this finding and decide whether the source content or the ingestion pipeline needs a fix."


def enrich_findings(findings: list[Finding], chunks_by_id: dict[str, Chunk]) -> list[dict[str, Any]]:
    """Flat list, sorted error-first — so scrolling the engineering tab
    hits the highest-priority items before 80 near-identical size warnings."""
    enriched: list[dict[str, Any]] = [
        {"finding": f, "chunks": resolve_chunks(f.chunk_ids, chunks_by_id), "action": suggested_action(f)}
        for f in findings
    ]
    enriched.sort(key=lambda e: _SEVERITY_ORDER.get(e["finding"].severity, 99))
    return enriched


def group_by_check(enriched: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Groups an already severity-sorted `enrich_findings()` result by
    check name, then orders the groups themselves by their own most severe
    finding first -- a check with real errors should appear before one
    with only warnings, not alphabetically. Done here in Python, not via
    Jinja's groupby filter, since `enriched`'s elements are plain dicts
    mixing a dict key ('finding') with a dataclass attribute access
    (`.check`/`.severity`) that groupby's own dotted-path resolution
    wasn't worth relying on sight-unseen."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in enriched:
        groups.setdefault(item["finding"].check, []).append(item)
    return sorted(groups.items(), key=lambda kv: _SEVERITY_ORDER.get(kv[1][0]["finding"].severity, 99))


def plain_check_label(check: str) -> str:
    return _PLAIN_CHECK_LABELS.get(check, check)


def category_breakdown(findings: list[Finding]) -> list[dict[str, Any]]:
    counts = Counter(f.check for f in findings)
    return [
        {"check": check, "label": plain_check_label(check), "count": count}
        for check, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def executive_verdict(findings: list[Finding]) -> str:
    error_count = sum(1 for f in findings if f.severity == "error")
    warn_count = sum(1 for f in findings if f.severity == "warn")
    if error_count > 0:
        return (
            f"This knowledge base has {error_count} high-priority issue(s) that should be "
            "addressed soon — they're likely affecting answer quality today."
        )
    if warn_count > 0:
        return (
            "No high-priority issues right now, but enough lower-priority ones "
            f"({warn_count}) that it's worth scheduling a cleanup pass."
        )
    return "No issues found — this knowledge base is clean as of this scan."


def top_findings(enriched: list[dict[str, Any]], limit: int = _TOP_FINDINGS_LIMIT) -> list[dict[str, Any]]:
    return enriched[:limit]


def history_summary(history: list[ScanResults]) -> list[dict[str, Any]]:
    """One row per past scan of this collection, oldest first — built
    entirely from `results.json` files that already exist on disk from
    every prior `kbguard scan`/`report`/`eval` run; no new tracking
    mechanism needed to answer "is this getting better or worse over
    time." `history` includes the scan currently being rendered too
    (its results.json is written before render_html is ever called, in
    every caller), so it's always the last row here."""
    return [
        {
            "snapshot_id": r.snapshot.id,
            "created_at": r.snapshot.created_at,
            "health": r.health,
            "chunk_count": r.snapshot.chunk_count,
            "finding_count": len(r.findings),
        }
        for r in sorted(history, key=lambda r: r.snapshot.created_at)
    ]
