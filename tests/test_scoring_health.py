from pathlib import Path

from kbguard.config import HealthWeights
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk, Finding
from kbguard.scoring.health import FindingsSummary, compute_health, summarize_findings

_DEFAULT_WEIGHTS = HealthWeights()


def _summary(
    chunk_count: int = 100,
    duplicate_chunk_count: int = 0,
    stale_chunk_count: int = 0,
    damaged_chunk_count: int = 0,
    contradiction_count: int = 0,
) -> FindingsSummary:
    return FindingsSummary(
        chunk_count=chunk_count,
        duplicate_chunk_count=duplicate_chunk_count,
        stale_chunk_count=stale_chunk_count,
        damaged_chunk_count=damaged_chunk_count,
        contradiction_count=contradiction_count,
    )


def test_every_ratio_at_zero_scores_100() -> None:
    assert compute_health(_summary(), _DEFAULT_WEIGHTS) == 100


def test_every_ratio_at_max_with_default_weights_scores_0() -> None:
    summary = _summary(
        chunk_count=100,
        duplicate_chunk_count=100,
        stale_chunk_count=100,
        damaged_chunk_count=100,
        contradiction_count=20,  # saturates the /20 cap
    )
    assert compute_health(summary, _DEFAULT_WEIGHTS) == 0


def test_zero_chunk_count_does_not_crash_and_scores_100() -> None:
    # 0/0 for the per-chunk ratios -- defined as 0.0, not NaN or a crash.
    # Contradiction count is also 0, so nothing to divide there either.
    summary = _summary(chunk_count=0)
    assert compute_health(summary, _DEFAULT_WEIGHTS) == 100


def test_overridden_weights_summing_above_one_still_clamp_to_0() -> None:
    # A careless user override: each weight set to 1.0 (sums to 4.0, not
    # 1.0). The uncapped formula would compute 100 - 400 = -300.
    weights = HealthWeights(duplicates=1.0, stale_versions=1.0, chunking_damage=1.0, contradictions=1.0)
    summary = _summary(chunk_count=100, duplicate_chunk_count=100, stale_chunk_count=100, damaged_chunk_count=100)

    assert compute_health(summary, weights) == 0


def test_all_weights_zero_means_nothing_affects_the_score() -> None:
    weights = HealthWeights(duplicates=0.0, stale_versions=0.0, chunking_damage=0.0, contradictions=0.0)
    summary = _summary(chunk_count=100, duplicate_chunk_count=100, stale_chunk_count=100, damaged_chunk_count=100)

    assert compute_health(summary, weights) == 100


def test_partial_ratio_matches_hand_computed_value() -> None:
    # 20% of chunks duplicated, nothing else flagged, default weights:
    # 100 - 0.15 * 0.20 * 100 = 100 - 3 = 97.
    summary = _summary(chunk_count=100, duplicate_chunk_count=20)

    assert compute_health(summary, _DEFAULT_WEIGHTS) == 97


def test_contradiction_count_above_saturation_caps_at_twenty() -> None:
    at_cap = _summary(contradiction_count=20)
    above_cap = _summary(contradiction_count=25)

    assert compute_health(at_cap, _DEFAULT_WEIGHTS) == compute_health(above_cap, _DEFAULT_WEIGHTS)


def test_combined_dimensions_match_hand_computed_value() -> None:
    # 10% duplicated + 10% stale + 5 contradictions (5/20 = 0.25 of cap),
    # default weights: 100 - (0.15*0.10 + 0.30*0.10 + 0.35*0.25)*100
    #                = 100 - (0.015 + 0.030 + 0.0875)*100 = 100 - 13.25 = 86.75 -> rounds to 87.
    summary = _summary(chunk_count=100, duplicate_chunk_count=10, stale_chunk_count=10, contradiction_count=5)

    assert compute_health(summary, _DEFAULT_WEIGHTS) == 87


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(id=chunk_id, text="text", embedding=[1.0], metadata={})


def _snapshot_with_findings(tmp_path: Path, chunk_ids: list[str], findings: list[Finding]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for cid in chunk_ids:
        writer.write_chunk(_chunk(cid))
    for finding in findings:
        writer.write_finding(finding)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def test_summarize_findings_reads_chunk_count_from_manifest(tmp_path: Path) -> None:
    reader = _snapshot_with_findings(tmp_path, ["a", "b", "c"], [])

    summary = summarize_findings(reader)

    assert summary["chunk_count"] == 3
    assert summary["duplicate_chunk_count"] == 0
    assert summary["contradiction_count"] == 0


def test_summarize_findings_counts_distinct_chunk_ids_not_raw_finding_count(tmp_path: Path) -> None:
    findings = [
        Finding(check="duplicates", severity="warn", chunk_ids=["a", "b"], message="m1", fingerprint="f1"),
        Finding(check="duplicates", severity="error", chunk_ids=["b", "c"], message="m2", fingerprint="f2"),
    ]
    reader = _snapshot_with_findings(tmp_path, ["a", "b", "c", "d"], findings)

    summary = summarize_findings(reader)

    # "b" appears in both findings but must only be counted once.
    assert summary["duplicate_chunk_count"] == 3


def test_summarize_findings_counts_contradictions_as_raw_finding_count(tmp_path: Path) -> None:
    findings = [
        Finding(check="contradictions", severity="error", chunk_ids=["a", "b"], message="m1", fingerprint="f1"),
        Finding(check="contradictions", severity="error", chunk_ids=["c", "d"], message="m2", fingerprint="f2"),
    ]
    reader = _snapshot_with_findings(tmp_path, ["a", "b", "c", "d"], findings)

    summary = summarize_findings(reader)

    assert summary["contradiction_count"] == 2


def test_summarize_findings_groups_each_check_independently(tmp_path: Path) -> None:
    findings = [
        Finding(check="duplicates", severity="warn", chunk_ids=["a"], message="m1", fingerprint="f1"),
        Finding(check="stale_versions", severity="warn", chunk_ids=["b"], message="m2", fingerprint="f2"),
        Finding(check="chunking_damage", severity="warn", chunk_ids=["c"], message="m3", fingerprint="f3"),
    ]
    reader = _snapshot_with_findings(tmp_path, ["a", "b", "c", "d"], findings)

    summary = summarize_findings(reader)

    assert summary["duplicate_chunk_count"] == 1
    assert summary["stale_chunk_count"] == 1
    assert summary["damaged_chunk_count"] == 1


def test_summarize_findings_then_compute_health_end_to_end(tmp_path: Path) -> None:
    findings = [Finding(check="duplicates", severity="warn", chunk_ids=["a", "b"], message="m", fingerprint="f1")]
    reader = _snapshot_with_findings(tmp_path, ["a", "b", "c", "d"], findings)

    summary = summarize_findings(reader)
    health = compute_health(summary, _DEFAULT_WEIGHTS)

    # 2 of 4 chunks duplicated (50%): 100 - 0.15*0.50*100 = 100 - 7.5 = 92.5 -> rounds to 92 (banker's rounding).
    assert health == 92
