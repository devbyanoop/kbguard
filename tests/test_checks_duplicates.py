import sys
from pathlib import Path

import pytest

from kbguard.checks.base import CheckContext
from kbguard.checks.duplicates import DuplicatesCheck, DuplicatesCheckError
from kbguard.config import DuplicatesCheckConfig
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk


def _snapshot(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


_DEFAULT_CONFIG = DuplicatesCheckConfig()


def _run(reader: SnapshotReader, config: DuplicatesCheckConfig = _DEFAULT_CONFIG):
    return list(DuplicatesCheck().run(reader, CheckContext(config=config)))


def _chunk(chunk_id: str, text: str, embedding: list[float], source: str | None = None) -> Chunk:
    return Chunk(id=chunk_id, text=text, embedding=embedding, metadata={}, source=source)


def test_exact_duplicate_same_source_stays_warn(tmp_path: Path) -> None:
    chunks = [
        _chunk("a", "Refunds within 30 days.", [1.0, 0.0], source="doc1"),
        _chunk("b", "Refunds within 30 days.", [0.0, 1.0], source="doc1"),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].evidence["duplicate_type"] == "exact"
    assert sorted(findings[0].chunk_ids) == ["a", "b"]


def test_exact_duplicate_cross_source_escalates_to_error(tmp_path: Path) -> None:
    chunks = [
        _chunk("a", "Refunds within 30 days.", [1.0, 0.0], source="doc1"),
        _chunk("b", "Refunds within 30 days.", [0.0, 1.0], source="doc2"),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_near_duplicate_both_signals_pass_is_flagged(tmp_path: Path) -> None:
    chunks = [
        _chunk("a", "the cat sat on the mat quietly today", [1.0, 0.0, 0.0]),
        _chunk("b", "the cat sat on the mat loudly today", [0.999, 0.0, 0.045]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert len(findings) == 1
    assert findings[0].evidence["duplicate_type"] == "near"
    assert sorted(findings[0].chunk_ids) == ["a", "b"]


def test_high_cosine_low_jaccard_not_flagged(tmp_path: Path) -> None:
    # The false positive the two-signal design specifically exists to
    # prevent: near-identical embeddings (same topic/meaning) but
    # completely different wording. Cosine alone would wrongly flag this.
    chunks = [
        _chunk("a", "the cat sat on the mat quietly today", [1.0, 0.0, 0.0]),
        _chunk("b", "quarterly revenue increased significantly across every region", [0.999, 0.0, 0.045]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert findings == []


def test_high_jaccard_low_cosine_not_flagged(tmp_path: Path) -> None:
    # The complementary case: near-identical wording but embeddings judge
    # them unrelated (e.g. a chunking/embedding artifact) — jaccard alone
    # would wrongly flag this too.
    chunks = [
        _chunk("a", "the cat sat on the mat quietly today", [1.0, 0.0, 0.0]),
        _chunk("b", "the cat sat on the mat loudly today", [0.0, 1.0, 0.0]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert findings == []


def test_transitive_near_duplicates_cluster_together(tmp_path: Path) -> None:
    # a~b and b~c both pass (consecutive 9-degree steps -> cosine ~0.988),
    # but a~c does NOT pass directly (18-degree gap -> cosine ~0.951,
    # below the 0.97 default). All three must still end up in one cluster
    # via transitivity, not reported as two separate pairwise findings.
    chunks = [
        _chunk("a", "the cat sat on the mat quietly today", [1.0, 0.0, 0.0]),
        _chunk("b", "the cat sat on the mat loudly today", [0.9877, 0.1564, 0.0]),
        _chunk("c", "the cat sat on the mat noisily today", [0.9511, 0.309, 0.0]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert len(findings) == 1
    assert sorted(findings[0].chunk_ids) == ["a", "b", "c"]


def test_exact_duplicates_excluded_from_near_duplicate_detection(tmp_path: Path) -> None:
    # An exact-duplicate pair trivially passes both near-duplicate
    # thresholds too (cosine=1.0, jaccard=1.0) -- must be reported once,
    # as "exact", not twice.
    chunks = [
        _chunk("a", "Refunds within 30 days.", [1.0, 0.0]),
        _chunk("b", "Refunds within 30 days.", [1.0, 0.0]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert len(findings) == 1
    assert findings[0].evidence["duplicate_type"] == "exact"


def test_disabled_check_yields_nothing(tmp_path: Path) -> None:
    chunks = [
        _chunk("a", "Refunds within 30 days.", [1.0, 0.0]),
        _chunk("b", "Refunds within 30 days.", [1.0, 0.0]),
    ]
    config = DuplicatesCheckConfig(enabled=False)
    findings = _run(_snapshot(tmp_path, chunks), config)

    assert findings == []


def test_fewer_than_two_chunks_yields_nothing(tmp_path: Path) -> None:
    chunks = [_chunk("a", "Refunds within 30 days.", [1.0, 0.0])]
    findings = _run(_snapshot(tmp_path, chunks))

    assert findings == []


def test_empty_snapshot_yields_nothing(tmp_path: Path) -> None:
    findings = _run(_snapshot(tmp_path, []))

    assert findings == []


def test_unrelated_chunks_yield_nothing(tmp_path: Path) -> None:
    chunks = [
        _chunk("a", "Refunds within 30 days.", [1.0, 0.0, 0.0]),
        _chunk("b", "Contact support for help.", [0.0, 1.0, 0.0]),
        _chunk("c", "Shipping takes a week.", [0.0, 0.0, 1.0]),
    ]
    findings = _run(_snapshot(tmp_path, chunks))

    assert findings == []


def test_against_real_example_corpus(tmp_path: Path) -> None:
    # Full real pipeline (ChromaAdapter + export_chunks), not a hand-rolled
    # re-read of Chroma's data -- the same path a real `kbguard scan` uses.
    import importlib.util

    from kbguard.adapters.chroma import ChromaAdapter
    from kbguard.ingest.exporter import export_chunks

    repo_root = Path(__file__).parent.parent
    seed_path = repo_root / "examples" / "policy_corpus" / "seed.py"
    spec = importlib.util.spec_from_file_location("policy_corpus_seed", seed_path)
    assert spec is not None and spec.loader is not None
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    seed_module.seed()  # idempotent; no-op if already seeded

    adapter = ChromaAdapter()
    adapter.connect(path=str(repo_root / "examples" / "policy_corpus" / "chroma_data"))

    # reuse_stored=True and every seeded chunk already has an embedding, so
    # this embedder is never actually called -- same reasoning as the CLI
    # tests that don't need sentence-transformers installed.
    def _unused_embedder(text: str) -> list[float]:
        raise AssertionError("embedder should not be called -- every chunk already has a stored embedding")

    chunks = list(
        export_chunks(adapter, "demo", metadata_map={"source": "doc_id"}, embedder=_unused_embedder)
    )
    reader = _snapshot(tmp_path, chunks)
    findings = _run(reader)

    clusters = {frozenset(f.chunk_ids): f for f in findings}
    assert frozenset({"refund-exact-1", "refund-exact-2"}) in clusters
    assert frozenset({"shipping-near-1", "shipping-near-2"}) in clusters
    assert len(findings) == 2  # nothing else gets flagged


def test_exact_duplicates_work_without_the_dedup_extra_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmed by hand against a real clean-venv install of just
    `kbguard[chroma]` (no `dedup`): `kbguard scan` crashed with a raw
    `ModuleNotFoundError: No module named 'faiss'` the instant this
    module was imported, before the check even ran, let alone needed
    faiss for anything -- exact-duplicate detection is plain text-hash
    matching and never touches faiss/datasketch at all. Simulating the
    same "not installed" condition here via sys.modules, not just
    trusting the earlier manual clean-venv check."""
    monkeypatch.setitem(sys.modules, "faiss", None)
    monkeypatch.setitem(sys.modules, "datasketch", None)

    chunks = [
        _chunk("a", "Refunds within 30 days of purchase.", [1.0, 0.0]),
        _chunk("b", "Refunds within 30 days of purchase.", [0.0, 1.0]),  # exact text dup, unrelated vector
    ]
    reader = _snapshot(tmp_path, chunks)

    findings = _run(reader)

    assert len(findings) == 1
    assert findings[0].evidence["duplicate_type"] == "exact"


def test_near_duplicates_raise_a_clear_error_without_the_dedup_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "faiss", None)
    monkeypatch.setitem(sys.modules, "datasketch", None)

    chunks = [
        _chunk("a", "Standard shipping takes 5 to 7 business days.", [1.0, 0.0]),
        _chunk("b", "Standard shipping usually takes 5 to 7 business days.", [0.999, 0.001]),
    ]
    reader = _snapshot(tmp_path, chunks)

    with pytest.raises(DuplicatesCheckError, match="dedup"):
        _run(reader)
