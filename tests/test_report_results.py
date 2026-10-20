from datetime import datetime, timezone
from pathlib import Path

from kbguard.models import EvalResult, Finding, Snapshot
from kbguard.report.results import ScanResults


def _snapshot() -> Snapshot:
    return Snapshot(
        id="snap-1",
        collection="policies",
        adapter="chroma",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        chunk_count=10,
        path="/tmp/snap-1",
    )


def _finding() -> Finding:
    return Finding(
        check="duplicates",
        severity="warn",
        chunk_ids=["a", "b"],
        message="2 chunks are exact duplicates",
        evidence={"duplicate_type": "exact"},
        fingerprint="abc123",
    )


def test_defaults_are_empty_lists_not_shared_mutable_state() -> None:
    results_a = ScanResults(snapshot=_snapshot(), health=100)
    results_b = ScanResults(snapshot=_snapshot(), health=90)

    results_a.findings.append(_finding())

    assert results_a.findings == [_finding()]
    assert results_b.findings == []  # confirms the default isn't one shared list instance


def test_to_json_then_from_json_round_trips(tmp_path: Path) -> None:
    results = ScanResults(
        snapshot=_snapshot(),
        health=92,
        findings=[_finding()],
        eval_results=[EvalResult(question_id="q1", metric="recall@5", value=0.8, passed=True, cause="none")],
    )
    path = tmp_path / "results.json"

    results.to_json(path)
    loaded = ScanResults.from_json(path)

    assert loaded == results


def test_to_json_output_is_byte_for_byte_stable_across_calls(tmp_path: Path) -> None:
    results = ScanResults(snapshot=_snapshot(), health=92, findings=[_finding()])
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"

    results.to_json(path_a)
    results.to_json(path_b)

    assert path_a.read_text() == path_b.read_text()


def test_json_field_order_matches_declaration_order(tmp_path: Path) -> None:
    results = ScanResults(snapshot=_snapshot(), health=92)
    path = tmp_path / "results.json"

    results.to_json(path)

    text = path.read_text()
    assert text.index('"snapshot"') < text.index('"health"') < text.index('"findings"') < text.index(
        '"eval_results"'
    )
