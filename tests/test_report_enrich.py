from datetime import datetime, timezone

from kbguard.models import Chunk, Finding, Snapshot
from kbguard.report.enrich import (
    category_breakdown,
    enrich_findings,
    executive_verdict,
    group_by_check,
    history_summary,
    resolve_chunks,
    suggested_action,
    top_findings,
)
from kbguard.report.results import ScanResults


def _chunk(id_: str, text: str, title: str | None = None, source: str | None = None) -> Chunk:
    return Chunk(id=id_, text=text, embedding=None, title=title, source=source)


def _finding(check: str, severity: str, chunk_ids: list[str], evidence: dict | None = None) -> Finding:
    return Finding(
        check=check, severity=severity, chunk_ids=chunk_ids, message=f"{check} finding", evidence=evidence or {}
    )


def _snapshot(snapshot_id: str = "s1", chunk_count: int = 10) -> Snapshot:
    return Snapshot(
        id=snapshot_id,
        collection="c",
        adapter="chroma",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        chunk_count=chunk_count,
        path="/tmp/" + snapshot_id,
    )


# --- resolve_chunks ---


def test_resolve_chunks_prefers_title_falls_back_to_source_then_id() -> None:
    chunks_by_id = {
        "a": _chunk("a", "some text", title="Install guide"),
        "b": _chunk("b", "some text", source="docs/setup.md"),
        "c": _chunk("c", "some text"),
    }
    resolved = resolve_chunks(["a", "b", "c"], chunks_by_id)

    assert resolved[0]["title"] == "Install guide"
    assert resolved[1]["title"] == "docs/setup.md"
    assert resolved[2]["title"] == "c"


def test_resolve_chunks_unresolvable_id_still_renders_something() -> None:
    resolved = resolve_chunks(["missing"], {})

    assert resolved == [{"id": "missing", "title": None, "source": None, "snippet": None}]


def test_resolve_chunks_snippet_is_collapsed_and_truncated() -> None:
    long_text = ("word " * 100).strip()
    chunks_by_id = {"a": _chunk("a", long_text)}

    resolved = resolve_chunks(["a"], chunks_by_id)

    assert len(resolved[0]["snippet"]) <= 151  # 150 chars + ellipsis
    assert resolved[0]["snippet"].endswith("…")


def test_resolve_chunks_short_text_snippet_is_not_truncated() -> None:
    chunks_by_id = {"a": _chunk("a", "short chunk")}

    resolved = resolve_chunks(["a"], chunks_by_id)

    assert resolved[0]["snippet"] == "short chunk"


# --- suggested_action ---


def test_suggested_action_duplicates_names_the_match_type() -> None:
    finding = _finding("duplicates", "error", ["a", "b"], {"duplicate_type": "exact"})
    assert "exact match" in suggested_action(finding)


def test_suggested_action_chunking_damage_size_distinguishes_too_big_vs_too_small() -> None:
    too_big = _finding("chunking_damage", "warn", ["a"], {"rule": "size", "max_tokens": 800})
    too_small = _finding("chunking_damage", "warn", ["a"], {"rule": "size", "min_tokens": 40})

    assert "splitting" in suggested_action(too_big)
    assert "merging" in suggested_action(too_small)


def test_suggested_action_every_known_chunking_damage_rule_has_a_real_action() -> None:
    for rule in ["split_table", "orphan_heading", "broken_sentence", "missing_metadata", "encoding_noise"]:
        finding = _finding("chunking_damage", "warn", ["a"], {"rule": rule})
        action = suggested_action(finding)
        assert action and "Review this finding" not in action  # not the generic fallback


def test_suggested_action_unknown_check_gets_a_generic_fallback() -> None:
    finding = _finding("some_future_check", "warn", ["a"])
    assert "Review this finding" in suggested_action(finding)


# --- enrich_findings / group_by_check ---


def test_enrich_findings_sorts_error_before_warn_before_info() -> None:
    findings = [
        _finding("chunking_damage", "info", ["a"]),
        _finding("duplicates", "error", ["b"]),
        _finding("stale_versions", "warn", ["c"]),
    ]

    enriched = enrich_findings(findings, {})

    assert [e["finding"].severity for e in enriched] == ["error", "warn", "info"]


def test_group_by_check_orders_groups_by_their_own_most_severe_finding() -> None:
    findings = [
        _finding("chunking_damage", "warn", ["a"]),
        _finding("duplicates", "error", ["b"]),
    ]
    enriched = enrich_findings(findings, {})

    grouped = group_by_check(enriched)

    assert [check for check, _ in grouped] == ["duplicates", "chunking_damage"]


def test_group_by_check_keeps_all_findings_for_each_check() -> None:
    findings = [
        _finding("chunking_damage", "warn", ["a"]),
        _finding("chunking_damage", "warn", ["b"]),
        _finding("duplicates", "error", ["c"]),
    ]
    enriched = enrich_findings(findings, {})

    grouped = dict(group_by_check(enriched))

    assert len(grouped["chunking_damage"]) == 2
    assert len(grouped["duplicates"]) == 1


# --- category_breakdown / executive_verdict ---


def test_category_breakdown_counts_and_sorts_by_count_descending() -> None:
    findings = [
        _finding("chunking_damage", "warn", ["a"]),
        _finding("chunking_damage", "warn", ["b"]),
        _finding("duplicates", "error", ["c"]),
    ]

    breakdown = category_breakdown(findings)

    assert breakdown[0]["check"] == "chunking_damage"
    assert breakdown[0]["count"] == 2
    assert breakdown[1]["check"] == "duplicates"
    assert breakdown[1]["count"] == 1


def test_executive_verdict_no_findings_says_clean() -> None:
    assert "clean" in executive_verdict([]).lower()


def test_executive_verdict_errors_present_calls_out_count_and_urgency() -> None:
    findings = [_finding("duplicates", "error", ["a"]), _finding("duplicates", "error", ["b"])]
    verdict = executive_verdict(findings)
    assert "2 high-priority" in verdict


def test_executive_verdict_warn_only_is_lower_urgency_than_error() -> None:
    verdict = executive_verdict([_finding("chunking_damage", "warn", ["a"])])
    assert "high-priority" not in verdict or "No high-priority" in verdict


# --- top_findings ---


def test_top_findings_respects_the_limit() -> None:
    findings = [_finding("chunking_damage", "warn", [str(i)]) for i in range(20)]
    enriched = enrich_findings(findings, {})

    assert len(top_findings(enriched, limit=5)) == 5


# --- history_summary ---


def test_history_summary_sorts_oldest_first_and_extracts_the_right_fields() -> None:
    newer = ScanResults(snapshot=_snapshot("s2", chunk_count=20), health=90, findings=[])
    older = ScanResults(
        snapshot=Snapshot(
            id="s1",
            collection="c",
            adapter="chroma",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            chunk_count=10,
            path="/tmp/s1",
        ),
        health=70,
        findings=[_finding("duplicates", "error", ["a"])],
    )
    newer.snapshot.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    summary = history_summary([newer, older])

    assert [row["snapshot_id"] for row in summary] == ["s1", "s2"]
    assert summary[0]["health"] == 70
    assert summary[0]["finding_count"] == 1
    assert summary[1]["chunk_count"] == 20
