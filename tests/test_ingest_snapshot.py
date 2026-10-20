import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kbguard.ingest.snapshot import SnapshotError, SnapshotReader, SnapshotWriter
from kbguard.models import Chunk, Finding


def _chunk(chunk_id: str, embedding: list[float], **overrides) -> Chunk:
    defaults: dict = {
        "id": chunk_id,
        "text": f"text for {chunk_id}",
        "embedding": embedding,
        "metadata": {"raw": "value"},
        "source": "doc-a",
        "position": 1,
        "version": "v1",
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "title": "A title",
    }
    defaults.update(overrides)
    return Chunk(**defaults)


def test_round_trip_chunks_and_findings(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap1", collection="policies", adapter_name="chroma", embedding_model="fake")
    chunks = [_chunk(f"c{i}", [float(i), float(i) + 0.5]) for i in range(5)]
    for c in chunks:
        writer.write_chunk(c)
    findings = [
        Finding(check="duplicates", severity="warn", chunk_ids=["c0", "c1"], message="dup", fingerprint="fp1"),
        Finding(check="contradictions", severity="error", chunk_ids=["c2"], message="conflict", fingerprint="fp2"),
    ]
    for f in findings:
        writer.write_finding(f)
    writer.close()

    reader = SnapshotReader(tmp_path / "snap1")
    read_chunks = {c.id: c for c in reader.chunks()}
    assert set(read_chunks) == {"c0", "c1", "c2", "c3", "c4"}
    assert read_chunks["c2"].text == "text for c2"
    assert read_chunks["c2"].metadata == {"raw": "value"}
    assert read_chunks["c2"].source == "doc-a"
    assert read_chunks["c2"].position == 1
    assert read_chunks["c2"].version == "v1"
    assert read_chunks["c2"].updated_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert read_chunks["c2"].title == "A title"
    assert read_chunks["c2"].embedding is None  # not attached by chunks(), see .vector()

    read_findings = list(reader.findings())
    assert len(read_findings) == 2
    assert {f.fingerprint for f in read_findings} == {"fp1", "fp2"}


def test_vector_alignment_not_coincidental(tmp_path: Path) -> None:
    # Distinguishable, non-sequential-looking vectors specifically so a bug
    # that reads the wrong row (e.g. an off-by-one) would be caught rather
    # than accidentally passing because nearby rows look similar.
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    writer.write_chunk(_chunk("alpha", [100.0, 101.0]))
    writer.write_chunk(_chunk("beta", [7.0, 8.0]))
    writer.write_chunk(_chunk("gamma", [-3.0, -4.0]))
    writer.close()

    reader = SnapshotReader(tmp_path / "snap")
    assert reader.vector("gamma") == pytest.approx([-3.0, -4.0])
    assert reader.vector("alpha") == pytest.approx([100.0, 101.0])
    assert reader.vector("beta") == pytest.approx([7.0, 8.0])


def test_bulk_vectors_matches_individual_lookups(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    writer.write_chunk(_chunk("alpha", [100.0, 101.0]))
    writer.write_chunk(_chunk("beta", [7.0, 8.0]))
    writer.write_chunk(_chunk("gamma", [-3.0, -4.0]))
    writer.close()

    reader = SnapshotReader(tmp_path / "snap")
    bulk = dict(reader.vectors())

    assert set(bulk) == {"alpha", "beta", "gamma"}
    assert bulk["alpha"] == pytest.approx([100.0, 101.0])
    assert bulk["gamma"] == pytest.approx([-3.0, -4.0])


def test_vector_unknown_chunk_id_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    writer.write_chunk(_chunk("a", [1.0]))
    writer.close()

    reader = SnapshotReader(tmp_path / "snap")
    with pytest.raises(SnapshotError, match="nope"):
        reader.vector("nope")


def test_manifest_contents(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="policies", adapter_name="qdrant", embedding_model="m1")
    writer.write_chunk(_chunk("a", [1.0, 2.0, 3.0]))
    writer.write_chunk(_chunk("b", [4.0, 5.0, 6.0]))
    writer.write_finding(Finding(check="x", severity="warn", chunk_ids=["a"], message="m"))
    writer.close()

    manifest = SnapshotReader(tmp_path / "snap").manifest()

    assert manifest["collection"] == "policies"
    assert manifest["adapter"] == "qdrant"
    assert manifest["embedding_model"] == "m1"
    assert manifest["chunk_count"] == 2
    assert manifest["finding_count"] == 1
    assert manifest["embedding_dim"] == 3
    assert manifest["id"] == "snap"


def test_write_chunk_without_embedding_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")

    with pytest.raises(SnapshotError, match="no embedding"):
        writer.write_chunk(Chunk(id="a", text="hi", embedding=None))


def test_write_chunk_dimension_mismatch_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0, 2.0]))

    with pytest.raises(SnapshotError, match="dimension"):
        writer.write_chunk(_chunk("b", [1.0, 2.0, 3.0]))


def test_write_chunk_duplicate_id_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0]))

    with pytest.raises(SnapshotError, match="duplicate chunk id"):
        writer.write_chunk(_chunk("a", [2.0]))


def test_write_after_close_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0]))
    writer.close()

    with pytest.raises(SnapshotError, match="already closed"):
        writer.write_chunk(_chunk("b", [2.0]))
    with pytest.raises(SnapshotError, match="already closed"):
        writer.close()


def test_duplicate_finding_fingerprint_raises(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0]))
    writer.write_finding(Finding(check="x", severity="warn", chunk_ids=["a"], message="m1", fingerprint="dup"))
    writer.write_finding(Finding(check="y", severity="error", chunk_ids=["a"], message="m2", fingerprint="dup"))

    with pytest.raises(SnapshotError, match="duplicate finding fingerprint"):
        writer.close()


def test_findings_with_empty_fingerprint_still_written(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0]))
    writer.write_finding(Finding(check="x", severity="warn", chunk_ids=["a"], message="no fingerprint set"))
    writer.close()

    read = list(SnapshotReader(tmp_path / "snap").findings())
    assert len(read) == 1
    assert read[0].fingerprint == ""


def test_findings_filtered_by_check(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0]))
    writer.write_finding(Finding(check="duplicates", severity="warn", chunk_ids=["a"], message="m1"))
    writer.write_finding(Finding(check="contradictions", severity="error", chunk_ids=["a"], message="m2"))
    writer.close()

    reader = SnapshotReader(tmp_path / "snap")
    only_dup = list(reader.findings(check="duplicates"))
    assert len(only_dup) == 1
    assert only_dup[0].message == "m1"


def test_empty_snapshot_round_trips(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.close()

    reader = SnapshotReader(tmp_path / "snap")
    assert list(reader.chunks()) == []
    assert list(reader.findings()) == []
    assert reader.manifest()["chunk_count"] == 0
    assert reader.manifest()["embedding_dim"] == 0


def test_source_index_built_correctly(tmp_path: Path) -> None:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="m")
    writer.write_chunk(_chunk("a", [1.0], source="doc-1"))
    writer.write_chunk(_chunk("b", [2.0], source="doc-1"))
    writer.write_chunk(_chunk("c", [3.0], source=None))
    writer.close()

    conn = sqlite3.connect(tmp_path / "snap" / "index.sqlite")
    try:
        rows = conn.execute("SELECT source, id FROM source_index ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [("doc-1", "a"), ("doc-1", "b")]  # chunk c has no source, not indexed
