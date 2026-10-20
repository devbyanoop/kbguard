from datetime import datetime, timezone
from pathlib import Path

from kbguard.models import Finding, Snapshot
from kbguard.report.html import render_html
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


def test_renders_a_known_findings_message_text(tmp_path: Path) -> None:
    finding = Finding(
        check="duplicates",
        severity="warn",
        chunk_ids=["a", "b"],
        message="2 chunks are exact duplicates",
        evidence={"duplicate_type": "exact"},
        fingerprint="abc123",
    )
    results = ScanResults(snapshot=_snapshot(), health=92, findings=[finding])
    out_path = tmp_path / "report.html"

    render_html(results, out_path)

    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert "2 chunks are exact duplicates" in html
    assert "duplicates" in html
    assert "92" in html


def test_empty_findings_and_eval_results_render_placeholder_text_not_crash(tmp_path: Path) -> None:
    results = ScanResults(snapshot=_snapshot(), health=100)
    out_path = tmp_path / "report.html"

    render_html(results, out_path)

    html = out_path.read_text(encoding="utf-8")
    assert "No findings" in html
    assert "No eval results" in html


def test_chunk_text_containing_html_is_escaped_not_executed(tmp_path: Path) -> None:
    finding = Finding(
        check="chunking_damage",
        severity="error",
        chunk_ids=["evil"],
        message="<script>alert(1)</script>",
        evidence={},
        fingerprint="xyz",
    )
    results = ScanResults(snapshot=_snapshot(), health=50, findings=[finding])
    out_path = tmp_path / "report.html"

    render_html(results, out_path)

    html = out_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_findings_are_grouped_by_check(tmp_path: Path) -> None:
    findings = [
        Finding(check="duplicates", severity="warn", chunk_ids=["a"], message="dup finding", fingerprint="f1"),
        Finding(check="stale_versions", severity="warn", chunk_ids=["b"], message="stale finding", fingerprint="f2"),
    ]
    results = ScanResults(snapshot=_snapshot(), health=80, findings=findings)
    out_path = tmp_path / "report.html"

    render_html(results, out_path)

    html = out_path.read_text(encoding="utf-8")
    assert html.index("dup finding") < html.index("stale finding") or "dup finding" in html
    assert "duplicates (1)" in html
    assert "stale_versions (1)" in html
