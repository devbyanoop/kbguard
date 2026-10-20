from pathlib import Path

from kbguard.config import FailOnConfig, HealthWeights, NewFindingsRule
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk, EvalResult, Finding
from kbguard.scoring.diff import diff_snapshots, load_suppressions

_NO_FAIL_ON = FailOnConfig()


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(id=chunk_id, text=f"text {chunk_id}", embedding=[1.0], metadata={})


def _snapshot(tmp_path: Path, name: str, chunk_ids: list[str], findings: list[Finding]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / name, collection="c", adapter_name="chroma", embedding_model="fake")
    for cid in chunk_ids:
        writer.write_chunk(_chunk(cid))
    for finding in findings:
        writer.write_finding(finding)
    writer.close()
    return SnapshotReader(tmp_path / name)


def test_new_finding_is_detected(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(
        tmp_path, "current", ["a"], [Finding(check="x", severity="error", chunk_ids=["a"], message="m", fingerprint="new1")]
    )

    result, exit_code = diff_snapshots(baseline, current, _NO_FAIL_ON, suppressions=set())

    assert [f.fingerprint for f in result.new_findings] == ["new1"]
    assert result.resolved_findings == []
    assert exit_code == 0  # no fail_on rules configured at all


def test_resolved_finding_is_detected(tmp_path: Path) -> None:
    baseline = _snapshot(
        tmp_path, "baseline", ["a"], [Finding(check="x", severity="warn", chunk_ids=["a"], message="m", fingerprint="old1")]
    )
    current = _snapshot(tmp_path, "current", ["a"], [])

    result, _ = diff_snapshots(baseline, current, _NO_FAIL_ON, suppressions=set())

    assert [f.fingerprint for f in result.resolved_findings] == ["old1"]
    assert result.new_findings == []


def test_unchanged_finding_appears_in_neither_list(tmp_path: Path) -> None:
    finding = Finding(check="x", severity="warn", chunk_ids=["a"], message="m", fingerprint="same1")
    baseline = _snapshot(tmp_path, "baseline", ["a"], [finding])
    current = _snapshot(tmp_path, "current", ["a"], [finding])

    result, _ = diff_snapshots(baseline, current, _NO_FAIL_ON, suppressions=set())

    assert result.new_findings == []
    assert result.resolved_findings == []


def test_new_error_finding_with_max_zero_fails_the_build(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a"],
        [Finding(check="x", severity="error", chunk_ids=["a"], message="m", fingerprint="new1")],
    )
    fail_on = FailOnConfig(new_findings=NewFindingsRule(severity="error", max=0))

    result, exit_code = diff_snapshots(baseline, current, fail_on, suppressions=set())

    assert exit_code == 1
    assert "new1" not in result.suppressed_fingerprints


def test_suppressing_the_fingerprint_flips_exit_code_back_to_zero_but_keeps_it_visible(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a"],
        [Finding(check="x", severity="error", chunk_ids=["a"], message="m", fingerprint="new1")],
    )
    fail_on = FailOnConfig(new_findings=NewFindingsRule(severity="error", max=0))

    result, exit_code = diff_snapshots(baseline, current, fail_on, suppressions={"new1"})

    assert exit_code == 0
    # Still visible in new_findings -- suppressing never makes it vanish.
    assert [f.fingerprint for f in result.new_findings] == ["new1"]
    assert result.suppressed_fingerprints == {"new1"}


def test_new_finding_below_the_configured_severity_does_not_count(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a"],
        [Finding(check="x", severity="warn", chunk_ids=["a"], message="m", fingerprint="new1")],
    )
    fail_on = FailOnConfig(new_findings=NewFindingsRule(severity="error", max=0))  # gate only cares about error+

    result, exit_code = diff_snapshots(baseline, current, fail_on, suppressions=set())

    assert exit_code == 0
    assert [f.fingerprint for f in result.new_findings] == ["new1"]  # still listed, just doesn't fail the gate


def test_new_findings_max_allows_up_to_that_many(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a"],
        [
            Finding(check="x", severity="error", chunk_ids=["a"], message="m1", fingerprint="new1"),
            Finding(check="x", severity="error", chunk_ids=["a"], message="m2", fingerprint="new2"),
        ],
    )
    fail_on = FailOnConfig(new_findings=NewFindingsRule(severity="error", max=2))

    _, exit_code_at_limit = diff_snapshots(baseline, current, fail_on, suppressions=set())
    assert exit_code_at_limit == 0  # exactly at the limit -- not over it

    fail_on_stricter = FailOnConfig(new_findings=NewFindingsRule(severity="error", max=1))
    _, exit_code_over_limit = diff_snapshots(baseline, current, fail_on_stricter, suppressions=set())
    assert exit_code_over_limit == 1


def test_health_drop_triggers_failure(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a", "b", "c", "d"], [])  # health 100
    current = _snapshot(
        tmp_path,
        "current",
        ["a", "b", "c", "d"],
        [Finding(check="duplicates", severity="warn", chunk_ids=["a", "b"], message="m", fingerprint="new1")],
    )
    # duplicates weight 0.15 * ratio 0.5 * 100 = 7.5 points dropped -> health 92 (rounds)
    fail_on = FailOnConfig(health_drop=3)

    result, exit_code = diff_snapshots(baseline, current, fail_on, suppressions=set())

    assert result.health_delta < 0
    assert exit_code == 1


def test_health_drop_within_tolerance_does_not_fail(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a", "b", "c", "d"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a", "b", "c", "d"],
        [Finding(check="duplicates", severity="warn", chunk_ids=["a", "b"], message="m", fingerprint="new1")],
    )
    fail_on = FailOnConfig(health_drop=50)  # generous tolerance

    _, exit_code = diff_snapshots(baseline, current, fail_on, suppressions=set())

    assert exit_code == 0


def test_metric_drop_triggers_failure(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(tmp_path, "current", ["a"], [])
    fail_on = FailOnConfig(metric_drop={"recall@5": 0.02})
    baseline_results = [EvalResult(question_id="q1", metric="recall@5", value=0.80, passed=True)]
    current_results = [EvalResult(question_id="q1", metric="recall@5", value=0.75, passed=True)]  # dropped 0.05

    result, exit_code = diff_snapshots(
        baseline, current, fail_on, suppressions=set(),
        baseline_eval_results=baseline_results, current_eval_results=current_results,
    )

    assert abs(result.metric_deltas["recall@5"] - (-0.05)) < 1e-9
    assert exit_code == 1


def test_metric_improvement_never_fails(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(tmp_path, "current", ["a"], [])
    fail_on = FailOnConfig(metric_drop={"recall@5": 0.02})
    baseline_results = [EvalResult(question_id="q1", metric="recall@5", value=0.70, passed=True)]
    current_results = [EvalResult(question_id="q1", metric="recall@5", value=0.90, passed=True)]  # improved

    result, exit_code = diff_snapshots(
        baseline, current, fail_on, suppressions=set(),
        baseline_eval_results=baseline_results, current_eval_results=current_results,
    )

    assert result.metric_deltas["recall@5"] > 0
    assert exit_code == 0


def test_metric_not_present_in_baseline_is_not_a_delta(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(tmp_path, "current", ["a"], [])
    current_results = [EvalResult(question_id="q1", metric="faithfulness", value=0.9, passed=True)]

    result, exit_code = diff_snapshots(
        baseline, current, _NO_FAIL_ON, suppressions=set(), current_eval_results=current_results
    )

    assert result.metric_deltas == {}  # no baseline value to compare against
    assert exit_code == 0


def test_averages_multiple_results_for_the_same_metric(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a"], [])
    current = _snapshot(tmp_path, "current", ["a"], [])
    baseline_results = [
        EvalResult(question_id="q1", metric="recall@5", value=0.8, passed=True),
        EvalResult(question_id="q2", metric="recall@5", value=1.0, passed=True),
    ]
    current_results = [
        EvalResult(question_id="q1", metric="recall@5", value=0.6, passed=True),
        EvalResult(question_id="q2", metric="recall@5", value=0.6, passed=True),
    ]

    result, _ = diff_snapshots(
        baseline, current, _NO_FAIL_ON, suppressions=set(),
        baseline_eval_results=baseline_results, current_eval_results=current_results,
    )

    # baseline mean 0.9, current mean 0.6 -> delta -0.3
    assert abs(result.metric_deltas["recall@5"] - (-0.3)) < 1e-9


def test_health_weights_affect_the_delta_computed(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path, "baseline", ["a", "b"], [])
    current = _snapshot(
        tmp_path,
        "current",
        ["a", "b"],
        [Finding(check="chunking_damage", severity="warn", chunk_ids=["a"], message="m", fingerprint="new1")],
    )

    light_weights = HealthWeights(chunking_damage=0.01)
    heavy_weights = HealthWeights(chunking_damage=0.9)

    result_light, _ = diff_snapshots(baseline, current, _NO_FAIL_ON, suppressions=set(), weights=light_weights)
    result_heavy, _ = diff_snapshots(baseline, current, _NO_FAIL_ON, suppressions=set(), weights=heavy_weights)

    assert result_heavy.health_delta < result_light.health_delta


# --- load_suppressions ---


def test_load_suppressions_missing_file_returns_empty_set(tmp_path: Path) -> None:
    assert load_suppressions(tmp_path / "does-not-exist.yaml") == set()


def test_load_suppressions_reads_fingerprint_keys(tmp_path: Path) -> None:
    path = tmp_path / "kbguard.ignore.yaml"
    path.write_text(
        "fp1:\n  reason: known issue\nfp2:\n  reason: accepted risk\n"
    )

    assert load_suppressions(path) == {"fp1", "fp2"}


def test_load_suppressions_empty_file_returns_empty_set(tmp_path: Path) -> None:
    path = tmp_path / "kbguard.ignore.yaml"
    path.write_text("")

    assert load_suppressions(path) == set()
