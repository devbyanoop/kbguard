from pathlib import Path
from typing import Any

from kbguard.evals.golden import GoldenRow
from kbguard.evals.retrieval import evaluate_retrieval
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk, Finding


class _FakeAdapter:
    """Returns the same canned ranked id list regardless of the query
    vector — enough control to test against hand-derived IR formulas
    without needing a real embedding model."""

    name = "fake"
    iteration_mode = "full"

    def __init__(self, ranked_ids: list[str]) -> None:
        self._ranked_ids = ranked_ids

    def connect(self, **settings: Any) -> None:
        pass

    def collections(self) -> list[str]:
        return []

    def count(self, collection: str) -> int:
        return 0

    def iter_chunks(self, collection: str, batch_size: int = 500, with_embeddings: bool = True):
        return iter(())

    def search(self, collection: str, query_vector: list[float], k: int, filters: dict[str, Any] | None = None):
        chunks = [Chunk(id=cid, text=f"text {cid}", embedding=[1.0]) for cid in self._ranked_ids[:k]]
        return [(chunk, 1.0 - i * 0.01) for i, chunk in enumerate(chunks)]


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(id=chunk_id, text=f"text {chunk_id}", embedding=[1.0], metadata={})


def _snapshot(tmp_path: Path, chunk_ids: list[str], findings: list[Finding] | None = None) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for cid in chunk_ids:
        writer.write_chunk(_chunk(cid))
    for finding in findings or []:
        writer.write_finding(finding)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def _row(expected: list[str]) -> GoldenRow:
    return GoldenRow(id="q1", question="does not matter -- the fake adapter ignores it", expected_chunk_ids=expected)


def _by_metric(results: list, k: int) -> dict[str, float]:
    return {r.metric: r.value for r in results if r.metric.endswith(f"@{k}")}


# --- hand-derived toy example 1: one relevant doc, found at rank 2 ---
# retrieved (k=3): [a, b, c]; expected = {b}
# hit@1=0 hit@2=1 hit@3=1 | recall@1=0 recall@2=1 recall@3=1
# precision@1=0 precision@2=0.5 precision@3=1/3
# mrr@3 = 1/2 = 0.5
# dcg@3 = 1/log2(3) ~= 0.6309; idcg@3 = 1/log2(2) = 1.0; ndcg@3 ~= 0.6309


def test_single_relevant_doc_at_rank_two_matches_hand_derived_values(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a", "b", "c"])
    snapshot = _snapshot(tmp_path, ["a", "b", "c"])
    golden = [_row(["b"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[1, 2, 3], embedder=lambda q: [0.0])

    m1, m2, m3 = _by_metric(results, 1), _by_metric(results, 2), _by_metric(results, 3)
    assert m1["hit@1"] == 0.0
    assert m2["hit@2"] == 1.0
    assert m3["hit@3"] == 1.0
    assert m1["recall@1"] == 0.0
    assert m2["recall@2"] == 1.0
    assert m3["recall@3"] == 1.0
    assert m1["precision@1"] == 0.0
    assert m2["precision@2"] == 0.5
    assert abs(m3["precision@3"] - (1 / 3)) < 1e-9
    assert m3["mrr@3"] == 0.5
    assert abs(m3["ndcg@3"] - 0.6309297535714574) < 1e-9


# --- hand-derived toy example 2: two relevant docs ---
# retrieved (k=3): [a, b, c]; expected = {a, c}
# recall@1=0.5 recall@2=0.5 recall@3=1.0
# precision@1=1.0 precision@2=0.5 precision@3=2/3
# mrr@3 = 1/1 = 1.0 (a found first, at rank 1)
# dcg@3 = 1/log2(2) + 1/log2(4) = 1.0 + 0.5 = 1.5
# idcg@3 = 1/log2(2) + 1/log2(3) = 1.0 + 0.6309297535714574 = 1.6309297535714575
# ndcg@3 = 1.5 / 1.6309297535714575 = 0.9197207891481876


def test_two_relevant_docs_matches_hand_derived_values(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a", "b", "c"])
    snapshot = _snapshot(tmp_path, ["a", "b", "c"])
    golden = [_row(["a", "c"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[1, 2, 3], embedder=lambda q: [0.0])

    m1, m2, m3 = _by_metric(results, 1), _by_metric(results, 2), _by_metric(results, 3)
    assert m1["recall@1"] == 0.5
    assert m2["recall@2"] == 0.5
    assert m3["recall@3"] == 1.0
    assert m1["precision@1"] == 1.0
    assert m2["precision@2"] == 0.5
    assert abs(m3["precision@3"] - (2 / 3)) < 1e-9
    assert m3["mrr@3"] == 1.0
    assert abs(m3["ndcg@3"] - 0.9197207891481876) < 1e-9


def test_no_relevant_doc_retrieved_scores_everything_zero(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["x", "y", "z"])
    snapshot = _snapshot(tmp_path, ["x", "y", "z", "b"])
    golden = [_row(["b"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[3], embedder=lambda q: [0.0])

    m = _by_metric(results, 3)
    assert m["hit@3"] == 0.0
    assert m["recall@3"] == 0.0
    assert m["precision@3"] == 0.0
    assert m["mrr@3"] == 0.0
    assert m["ndcg@3"] == 0.0


def test_empty_expected_set_does_not_crash_and_scores_zero(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a", "b"])
    snapshot = _snapshot(tmp_path, ["a", "b"])
    golden = [_row([])]  # malformed/edge golden row with no expected chunks at all

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[2], embedder=lambda q: [0.0])

    m = _by_metric(results, 2)
    assert m["recall@2"] == 0.0
    assert m["ndcg@2"] == 0.0  # idcg is 0 -> defined as 0, not a ZeroDivisionError


def test_empty_golden_set_returns_no_results(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a"])
    snapshot = _snapshot(tmp_path, ["a"])

    results = evaluate_retrieval([], adapter, "c", snapshot, k_values=[1, 5], embedder=lambda q: [0.0])

    assert results == []


def test_k_larger_than_retrieved_results_does_not_crash(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a"])  # only one id to ever retrieve
    snapshot = _snapshot(tmp_path, ["a"])
    golden = [_row(["a"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[10], embedder=lambda q: [0.0])

    m = _by_metric(results, 10)
    assert m["hit@10"] == 1.0
    assert m["recall@10"] == 1.0


# --- cause tagging ---


def test_cause_is_none_when_hit(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a", "b"])
    snapshot = _snapshot(tmp_path, ["a", "b"])
    golden = [_row(["a"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[2], embedder=lambda q: [0.0])

    assert all(r.cause == "none" for r in results)
    assert all(r.passed for r in results)


def test_cause_is_content_when_expected_chunk_missing_from_snapshot(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["x", "y"])
    snapshot = _snapshot(tmp_path, ["x", "y"])  # "missing-chunk" was never written to this snapshot at all
    golden = [_row(["missing-chunk"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[2], embedder=lambda q: [0.0])

    assert all(r.cause == "content" for r in results)
    assert all(not r.passed for r in results)


def test_cause_is_content_when_expected_chunk_is_flagged_by_a_check(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["x", "y"])
    finding = Finding(check="chunking_damage", severity="warn", chunk_ids=["b"], message="damaged", fingerprint="f1")
    snapshot = _snapshot(tmp_path, ["x", "y", "b"], findings=[finding])
    golden = [_row(["b"])]  # exists, but flagged -- fixing retrieval wouldn't help

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[2], embedder=lambda q: [0.0])

    assert all(r.cause == "content" for r in results)


def test_cause_is_retrieval_when_expected_chunk_exists_unflagged_but_not_retrieved(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["x", "y"])  # "b" exists in the snapshot but the adapter never returns it
    snapshot = _snapshot(tmp_path, ["x", "y", "b"])
    golden = [_row(["b"])]

    results = evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[2], embedder=lambda q: [0.0])

    assert all(r.cause == "retrieval" for r in results)


def test_embedder_is_called_with_the_question_text(tmp_path: Path) -> None:
    adapter = _FakeAdapter(["a"])
    snapshot = _snapshot(tmp_path, ["a"])
    golden = [GoldenRow(id="q1", question="what is the refund window?", expected_chunk_ids=["a"])]
    calls = []

    evaluate_retrieval(golden, adapter, "c", snapshot, k_values=[1], embedder=lambda q: calls.append(q) or [0.0])

    assert calls == ["what is the refund window?"]


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

    chunks = list(export_chunks(adapter, "demo", metadata_map={"source": "doc_id"}, embedder=_unused_embedder))
    snapshot = _snapshot(tmp_path, [c.id for c in chunks])

    # A real golden question whose answer is verifiably in "privacy-1",
    # using that chunk's own real hand-crafted embedding as the "query" --
    # the nearest real neighbor to its own vector is itself.
    seed_vecs = {c["id"]: c["embedding"] for c in seed_module.CHUNKS}
    golden = [GoldenRow(id="q1", question="does our policy sell personal data?", expected_chunk_ids=["privacy-1"])]

    results = evaluate_retrieval(
        golden, adapter, "demo", snapshot, k_values=[1], embedder=lambda q: seed_vecs["privacy-1"]
    )

    m = _by_metric(results, 1)
    assert m["hit@1"] == 1.0
    assert all(r.cause == "none" for r in results)
