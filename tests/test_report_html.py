from datetime import datetime, timezone
from pathlib import Path

from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk, Finding, Snapshot
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


def _snapshot_with_chunks(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def test_all_three_tabs_are_present() -> None:
    results = ScanResults(snapshot=_snapshot(), health=92)
    html = _render_to_string(results)

    assert 'id="tab-summary"' in html
    assert 'id="tab-engineering"' in html
    assert 'id="tab-trend"' in html
    assert ">Summary</label>" in html
    assert ">Engineering</label>" in html
    assert ">Trend</label>" in html


def test_a_finding_is_enriched_with_its_real_source_and_snippet_when_a_reader_is_given(tmp_path: Path) -> None:
    chunk = Chunk(
        id="chunk-1",
        text="Refunds are processed within 30 business days of the original request.",
        embedding=[1.0, 0.0],
        title="Refund policy",
        source="docs/refunds.md",
    )
    reader = _snapshot_with_chunks(tmp_path, [chunk])
    finding = Finding(
        check="chunking_damage",
        severity="warn",
        chunk_ids=["chunk-1"],
        message="Chunk has ~12 words, below min_tokens=40",
        evidence={"rule": "size", "min_tokens": 40},
    )
    results = ScanResults(snapshot=_snapshot(), health=80, findings=[finding])

    html = _render_to_string(results, reader=reader)

    assert "Refund policy" in html
    assert "docs/refunds.md" in html
    assert "Refunds are processed within 30 business days" in html  # the snippet
    assert "merging" in html  # the suggested action for a too-small chunk


def test_a_finding_without_a_reader_still_renders_using_the_bare_chunk_id() -> None:
    finding = Finding(check="duplicates", severity="error", chunk_ids=["unresolved-id"], message="dup")
    results = ScanResults(snapshot=_snapshot(), health=80, findings=[finding])

    html = _render_to_string(results)  # no reader passed

    assert "unresolved-id" in html


def test_evidence_renders_as_readable_key_value_pairs_not_a_raw_python_repr() -> None:
    finding = Finding(
        check="chunking_damage",
        severity="warn",
        chunk_ids=["a"],
        message="Chunk has ~5 words, below min_tokens=40",
        evidence={"rule": "size", "min_tokens": 40},
    )
    results = ScanResults(snapshot=_snapshot(), health=80, findings=[finding])

    html = _render_to_string(results)

    assert "rule: size" in html
    assert "min_tokens: 40" in html
    assert "{&#39;rule&#39;" not in html  # the old raw-dict-repr rendering


def test_executive_summary_shows_a_verdict_and_category_breakdown() -> None:
    finding = Finding(check="duplicates", severity="error", chunk_ids=["a", "b"], message="exact duplicate")
    results = ScanResults(snapshot=_snapshot(), health=60, findings=[finding])

    html = _render_to_string(results)

    assert "1 high-priority" in html
    assert "Duplicate or near-duplicate content" in html


def test_trend_tab_says_theres_nothing_to_compare_with_a_single_scan() -> None:
    results = ScanResults(snapshot=_snapshot(), health=90)

    html = _render_to_string(results)

    assert "Only one scan on record" in html


def test_trend_tab_shows_a_delta_with_real_history(tmp_path: Path) -> None:
    older = ScanResults(
        snapshot=Snapshot(
            id="old", collection="c", adapter="chroma",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), chunk_count=5, path="/tmp/old",
        ),
        health=70,
        findings=[Finding(check="duplicates", severity="error", chunk_ids=["a"], message="dup")],
    )
    current = ScanResults(snapshot=_snapshot(), health=92)
    out_path = tmp_path / "report.html"

    render_html(current, out_path, history=[older, current])

    html = out_path.read_text(encoding="utf-8")
    assert "70 → 92" in html
    assert "improved" in html


def _render_to_string(results: ScanResults, reader: SnapshotReader | None = None) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.html"
        render_html(results, out_path, reader=reader)
        return out_path.read_text(encoding="utf-8")
