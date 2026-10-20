from typing import Any, TypedDict

from kbguard.config import HealthWeights
from kbguard.ingest.snapshot import SnapshotReader

# Spec section 11's literal "/20" cap: a 21st simultaneous contradiction
# contributes no more to the score than the 20th did. Contradictions are
# counted as findings, not as a fraction of chunk_count (unlike the other
# three dimensions), since a single finding already involves two chunks
# and a corpus-size-relative ratio would make the same 20 conflicts mean
# wildly different things on a 50-chunk vs. a 50,000-chunk collection.
_CONTRADICTIONS_SATURATION = 20


class FindingsSummary(TypedDict):
    chunk_count: int
    duplicate_chunk_count: int
    stale_chunk_count: int
    damaged_chunk_count: int
    contradiction_count: int


def summarize_findings(snapshot: SnapshotReader) -> FindingsSummary:
    """Reduces a snapshot's findings to exactly what compute_health needs:
    for the three per-chunk checks, the *distinct* chunk ids they flagged
    (not a raw finding count — two findings sharing a chunk must not count
    that chunk twice), and for contradictions, a plain finding count.
    """
    duplicate_ids: set[str] = set()
    stale_ids: set[str] = set()
    damaged_ids: set[str] = set()
    contradiction_count = 0

    for finding in snapshot.findings():
        # Deliberately only these four — compute_health's formula (spec
        # section 11) is defined over exactly these dimensions. A future
        # check's findings simply don't move the health score until the
        # formula itself is extended to include them; that's a decision
        # for whoever adds that check, not a silent gap to discover later.
        if finding.check == "duplicates":
            duplicate_ids.update(finding.chunk_ids)
        elif finding.check == "stale_versions":
            stale_ids.update(finding.chunk_ids)
        elif finding.check == "chunking_damage":
            damaged_ids.update(finding.chunk_ids)
        elif finding.check == "contradictions":
            contradiction_count += 1

    return FindingsSummary(
        chunk_count=snapshot.manifest()["chunk_count"],
        duplicate_chunk_count=len(duplicate_ids),
        stale_chunk_count=len(stale_ids),
        damaged_chunk_count=len(damaged_ids),
        contradiction_count=contradiction_count,
    )


def compute_health(findings_summary: FindingsSummary | dict[str, Any], weights: HealthWeights) -> int:
    """Spec section 11's formula, clamped to [0, 100] regardless of
    configured weights — the fix called out explicitly in the original
    architecture review: weights that don't sum to 1 (a careless override)
    must not be able to push the result outside a 0-100 "percent-like"
    range a non-technical buyer will read at face value.
    """
    chunk_count = findings_summary["chunk_count"]

    def ratio(count: int) -> float:
        return count / chunk_count if chunk_count > 0 else 0.0

    duplicate_ratio = ratio(findings_summary["duplicate_chunk_count"])
    stale_ratio = ratio(findings_summary["stale_chunk_count"])
    damaged_ratio = ratio(findings_summary["damaged_chunk_count"])
    conflict_ratio = min(1.0, findings_summary["contradiction_count"] / _CONTRADICTIONS_SATURATION)

    score = 100.0
    score -= weights.duplicates * duplicate_ratio * 100
    score -= weights.stale_versions * stale_ratio * 100
    score -= weights.chunking_damage * damaged_ratio * 100
    score -= weights.contradictions * conflict_ratio * 100

    return max(0, min(100, round(score)))
