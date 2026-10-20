from pathlib import Path
from typing import Any

from kbguard.checks.base import CheckContext
from kbguard.checks.chunking_damage import ChunkingDamageCheck
from kbguard.config import ChunkingDamageCheckConfig
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk

_DEFAULT_TEXT = "This is a perfectly ordinary chunk of policy text with plenty of words in it, nothing wrong here at all."


def _chunk(chunk_id: str, **overrides: Any) -> Chunk:
    defaults: dict[str, Any] = {"id": chunk_id, "text": _DEFAULT_TEXT, "embedding": [1.0], "metadata": {}}
    defaults.update(overrides)
    return Chunk(**defaults)


def _snapshot(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def _run(reader: SnapshotReader, config: ChunkingDamageCheckConfig):
    return list(ChunkingDamageCheck().run(reader, CheckContext(config=config)))


_DEFAULT_CONFIG = ChunkingDamageCheckConfig(min_tokens=10, max_tokens=800)


def _rules(findings: list) -> set[str]:
    return {f.evidence["rule"] for f in findings}


def test_clean_chunk_triggers_nothing(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a")])

    assert _run(reader, _DEFAULT_CONFIG) == []


# --- size ---


def test_undersized_chunk_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", text="Too short.")])

    findings = _run(reader, _DEFAULT_CONFIG)

    assert "size" in _rules(findings)


def test_oversized_chunk_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", text=" ".join(["word"] * 900))])

    findings = _run(reader, _DEFAULT_CONFIG)

    assert "size" in _rules(findings)


def test_size_within_bounds_not_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", text=_DEFAULT_TEXT)])  # ~19 words, between 10 and 800

    assert "size" not in _rules(_run(reader, _DEFAULT_CONFIG))


# --- split_table ---


def test_table_cut_at_end_flagged(tmp_path: Path) -> None:
    text = "| Plan | Price |\n| --- | --- |\n| Basic | $10/mo"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    findings = _run(reader, _DEFAULT_CONFIG)

    assert "split_table" in _rules(findings)
    matching = [f for f in findings if f.evidence["rule"] == "split_table"]
    assert matching[0].evidence["edge"] == "end"


def test_table_cut_at_start_flagged(tmp_path: Path) -> None:
    text = "Price | Users |\n| Basic | $10/mo | 1 |"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    findings = _run(reader, _DEFAULT_CONFIG)

    matching = [f for f in findings if f.evidence["rule"] == "split_table"]
    assert matching[0].evidence["edge"] == "start"


def test_complete_table_row_not_flagged(tmp_path: Path) -> None:
    text = "Some intro text here with enough words to pass size.\n| Plan | Price |\n| Basic | $10/mo |"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "split_table" not in _rules(_run(reader, _DEFAULT_CONFIG))


# --- orphan_heading ---


def test_chunk_that_is_only_a_heading_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", text="## Frequently Asked Questions")])

    assert "orphan_heading" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_chunk_ending_with_a_heading_flagged(tmp_path: Path) -> None:
    text = _DEFAULT_TEXT + "\nNext Section Heading"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "orphan_heading" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_table_row_not_misclassified_as_heading(tmp_path: Path) -> None:
    # Regression: a cut-off table row ("| Pro | $25/mo") is short, ends
    # without terminal punctuation, and its one real word is capitalized —
    # found by hand to be misclassified as a heading before pipes were
    # explicitly excluded.
    text = "| Plan | Price | Users |\n| --- | --- | --- |\n| Basic | $10/mo | 1 |\n| Pro | $25/mo"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "orphan_heading" not in _rules(_run(reader, _DEFAULT_CONFIG))


def test_ordinary_paragraph_not_flagged_as_heading(tmp_path: Path) -> None:
    assert "orphan_heading" not in _rules(_run(_snapshot(tmp_path, [_chunk("a")]), _DEFAULT_CONFIG))


# --- broken_sentence ---


def test_starts_mid_sentence_with_no_predecessor_flagged(tmp_path: Path) -> None:
    text = "...and therefore the company reserves the right to modify these terms at any time."
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "broken_sentence" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_lowercase_start_flagged(tmp_path: Path) -> None:
    text = "are the terms that apply to every purchase made through this store at any time of year."
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "broken_sentence" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_normal_sentence_start_not_flagged(tmp_path: Path) -> None:
    assert "broken_sentence" not in _rules(_run(_snapshot(tmp_path, [_chunk("a")]), _DEFAULT_CONFIG))


def test_mid_sentence_start_with_overlapping_predecessor_not_flagged(tmp_path: Path) -> None:
    predecessor = _chunk(
        "a", source="doc1", position=0,
        text="The company reserves certain rights and the following terms apply to every purchase made here",
    )
    this_chunk = _chunk(
        "b", source="doc1", position=1,
        text="apply to every purchase made here and therefore cannot be waived under any circumstances at all.",
    )
    reader = _snapshot(tmp_path, [predecessor, this_chunk])

    findings = _run(reader, _DEFAULT_CONFIG)
    b_findings = [f for f in findings if f.chunk_ids == ["b"]]

    assert "broken_sentence" not in {f.evidence["rule"] for f in b_findings}


def test_mid_sentence_start_with_non_overlapping_predecessor_flagged(tmp_path: Path) -> None:
    predecessor = _chunk("a", source="doc1", position=0, text="This paragraph is about something else entirely.")
    this_chunk = _chunk(
        "b", source="doc1", position=1,
        text="and therefore cannot be waived under any circumstances at all without written consent first.",
    )
    reader = _snapshot(tmp_path, [predecessor, this_chunk])

    findings = _run(reader, _DEFAULT_CONFIG)
    b_findings = [f for f in findings if f.chunk_ids == ["b"]]

    assert "broken_sentence" in {f.evidence["rule"] for f in b_findings}


# --- missing_metadata ---


def test_missing_required_field_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", source=None)])
    config = ChunkingDamageCheckConfig(min_tokens=10, max_tokens=800, required_metadata=["source"])

    findings = _run(reader, config)

    assert "missing_metadata" in _rules(findings)


def test_present_required_field_not_flagged(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", source="doc1")])
    config = ChunkingDamageCheckConfig(min_tokens=10, max_tokens=800, required_metadata=["source"])

    assert "missing_metadata" not in _rules(_run(reader, config))


def test_no_required_metadata_configured_never_flags(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", source=None)])

    assert "missing_metadata" not in _rules(_run(reader, _DEFAULT_CONFIG))  # required_metadata=[] by default


# --- encoding_noise ---


def test_control_characters_flagged(tmp_path: Path) -> None:
    text = "Payment methods include credit card\x00\x00 debit card\x01 and bank transfer\x02\x02 for all purchases."
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "encoding_noise" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_repeated_line_within_chunk_flagged(tmp_path: Path) -> None:
    text = "Confidential Internal Document\nSome real content goes here about the policy itself.\nConfidential Internal Document"
    reader = _snapshot(tmp_path, [_chunk("a", text=text)])

    assert "encoding_noise" in _rules(_run(reader, _DEFAULT_CONFIG))


def test_clean_text_not_flagged_for_encoding_noise(tmp_path: Path) -> None:
    assert "encoding_noise" not in _rules(_run(_snapshot(tmp_path, [_chunk("a")]), _DEFAULT_CONFIG))


# --- disabled / against real corpus ---


def test_disabled_check_yields_nothing(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_chunk("a", text="Too short.")])
    config = ChunkingDamageCheckConfig(enabled=False)

    assert _run(reader, config) == []


def test_against_real_example_corpus(tmp_path: Path) -> None:
    import importlib.util

    from kbguard.adapters.chroma import ChromaAdapter
    from kbguard.ingest.exporter import export_chunks

    repo_root = Path(__file__).parent.parent
    seed_path = repo_root / "examples" / "policy_corpus" / "seed.py"
    spec = importlib.util.spec_from_file_location("policy_corpus_seed", seed_path)
    assert spec is not None and spec.loader is not None
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    seed_module.seed()

    adapter = ChromaAdapter()
    adapter.connect(path=str(repo_root / "examples" / "policy_corpus" / "chroma_data"))

    def _unused_embedder(text: str) -> list[float]:
        raise AssertionError("embedder should not be called")

    metadata_map = {"source": "doc_id", "title": "title", "version": "version", "updated_at": "updated_at"}
    chunks = list(export_chunks(adapter, "demo", metadata_map=metadata_map, embedder=_unused_embedder))
    reader = _snapshot(tmp_path, chunks)

    # Matches examples/policy_corpus/kbguard.yaml's demo-specific override —
    # this corpus's chunks are deliberately short, so the global min_tokens
    # default (40) would flag nearly everything.
    config = ChunkingDamageCheckConfig(min_tokens=10, max_tokens=800, required_metadata=["source"])
    findings = _run(reader, config)

    by_rule: dict[str, set[str]] = {}
    for f in findings:
        by_rule.setdefault(f.evidence["rule"], set()).add(f.chunk_ids[0])

    assert by_rule == {
        "size": {"tiny-chunk-1", "orphan-heading-1"},
        "split_table": {"pricing-table-cut"},
        "orphan_heading": {"orphan-heading-1"},
        "broken_sentence": {"broken-sentence-1"},
        "missing_metadata": {"no-source-chunk"},
        "encoding_noise": {"encoding-noise-1"},
    }
