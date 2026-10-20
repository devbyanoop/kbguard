import json
from pathlib import Path
from typing import Any

from kbguard.evals.golden import GoldenRow, freeze, generate, load_golden
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk


class _FakeJudge:
    def __init__(self, questions: dict[str, str] | None = None, default: str | None = "What happens here?") -> None:
        self._questions = questions or {}
        self._default = default
        self.calls: list[str] = []
        self.model = "fake-model"  # JudgeLike now requires this (ragas/deepeval plugins read it)

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        self.calls.append(prompt)
        for chunk_text, question in self._questions.items():
            if chunk_text in prompt:
                return {"question": question}
        if self._default is None:
            return {}
        return {"question": self._default}


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(id=chunk_id, text=text, embedding=[1.0], metadata={})


def _snapshot(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def test_generate_produces_one_row_per_sampled_chunk_never_approved(tmp_path: Path) -> None:
    chunks = [_chunk("a", "Refunds within 30 days."), _chunk("b", "Shipping takes 5 days.")]
    judge = _FakeJudge()
    reader = _snapshot(tmp_path, chunks)

    df = generate(reader, n=2, judge=judge)

    assert len(df) == 2
    assert set(df.columns) == {"question", "expected_chunk_ids", "reference_answer", "approved"}
    assert not df["approved"].any()  # never auto-approved, even for n == available chunk count
    assert set(df["expected_chunk_ids"]) == {"a", "b"}


def test_generate_n_larger_than_available_chunks_does_not_crash(tmp_path: Path) -> None:
    chunks = [_chunk("a", "Refunds within 30 days.")]
    reader = _snapshot(tmp_path, chunks)

    df = generate(reader, n=100, judge=_FakeJudge())

    assert len(df) == 1  # clamped, not an error


def test_generate_empty_snapshot_returns_empty_dataframe_with_columns(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [])

    df = generate(reader, n=5, judge=_FakeJudge())

    assert len(df) == 0
    assert list(df.columns) == ["question", "expected_chunk_ids", "reference_answer", "approved"]


def test_generate_skips_a_chunk_when_judge_returns_no_question(tmp_path: Path) -> None:
    chunks = [_chunk("a", "Refunds within 30 days.")]
    reader = _snapshot(tmp_path, chunks)
    judge = _FakeJudge(default=None)

    df = generate(reader, n=1, judge=judge)

    assert len(df) == 0
    assert len(judge.calls) == 1  # the judge was still asked -- it just gave nothing usable


def test_generate_is_reproducible_across_calls_against_the_same_snapshot(tmp_path: Path) -> None:
    chunks = [_chunk(f"c{i}", f"Chunk number {i} text here.") for i in range(10)]
    reader = _snapshot(tmp_path, chunks)

    df1 = generate(reader, n=3, judge=_FakeJudge())
    df2 = generate(reader, n=3, judge=_FakeJudge())

    assert sorted(df1["expected_chunk_ids"]) == sorted(df2["expected_chunk_ids"])


def _write_csv(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    import pandas as pd

    path = tmp_path / "review.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_freeze_filters_to_approved_rows_only(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        [
            {"question": "Q1?", "expected_chunk_ids": "a", "reference_answer": "", "approved": True},
            {"question": "Q2?", "expected_chunk_ids": "b", "reference_answer": "", "approved": False},
        ],
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)

    lines = out_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["question"] == "Q1?"


def test_freeze_tolerates_a_blank_approved_cell_without_crashing(tmp_path: Path) -> None:
    # The exact real bug this test guards against: a human leaves one
    # row's `approved` cell blank while reviewing the rest. Writing this
    # CSV by hand (not via to_csv on a clean bool column) reproduces the
    # mixed-dtype column a real reviewer's half-finished CSV would have.
    csv_path = tmp_path / "review.csv"
    csv_path.write_text(
        "question,expected_chunk_ids,reference_answer,approved\n"
        "Q1?,a,,TRUE\n"
        "Q2?,b,,\n"  # blank -- not yet reviewed
        "Q3?,c,,FALSE\n"
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)  # must not raise

    lines = out_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["question"] == "Q1?"


def test_freeze_assigns_stable_ids_based_on_question_text(tmp_path: Path) -> None:
    import hashlib

    csv_path = _write_csv(
        tmp_path, [{"question": "What is the refund window?", "expected_chunk_ids": "a", "reference_answer": "", "approved": True}]
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)

    record = json.loads(out_path.read_text().splitlines()[0])
    expected_id = hashlib.sha256(b"What is the refund window?").hexdigest()[:16]
    assert record["id"] == expected_id


def test_freeze_twice_on_the_same_csv_produces_identical_ids(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path, [{"question": "What is the refund window?", "expected_chunk_ids": "a", "reference_answer": "", "approved": True}]
    )
    out_path_1 = tmp_path / "golden1.jsonl"
    out_path_2 = tmp_path / "golden2.jsonl"

    freeze(csv_path, out_path_1)
    freeze(csv_path, out_path_2)

    id1 = json.loads(out_path_1.read_text().splitlines()[0])["id"]
    id2 = json.loads(out_path_2.read_text().splitlines()[0])["id"]
    assert id1 == id2


def test_freeze_missing_reference_answer_becomes_json_null(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path, [{"question": "Q1?", "expected_chunk_ids": "a", "reference_answer": "", "approved": True}]
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)

    record = json.loads(out_path.read_text().splitlines()[0])
    assert record["reference_answer"] is None


def test_freeze_present_reference_answer_is_kept(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        [{"question": "Q1?", "expected_chunk_ids": "a", "reference_answer": "within 30 days", "approved": True}],
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)

    record = json.loads(out_path.read_text().splitlines()[0])
    assert record["reference_answer"] == "within 30 days"


def test_freeze_parses_comma_separated_expected_chunk_ids(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path, [{"question": "Q1?", "expected_chunk_ids": "a, b", "reference_answer": "", "approved": True}]
    )
    out_path = tmp_path / "golden.jsonl"

    freeze(csv_path, out_path)

    record = json.loads(out_path.read_text().splitlines()[0])
    assert record["expected_chunk_ids"] == ["a", "b"]


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
    reader = _snapshot(tmp_path, chunks)

    judge = _FakeJudge(default="What does this chunk say?")
    df = generate(reader, n=5, judge=judge)

    assert len(df) == 5
    assert len(judge.calls) == 5

    # Simulate a human approving two of the five rows, leaving the
    # `approved` cells of the other three blank (not explicitly False) --
    # the real-world shape this whole module is built to handle.
    df.loc[df.index[:2], "approved"] = True
    csv_path = tmp_path / "review.csv"
    df.to_csv(csv_path, index=False)

    out_path = tmp_path / "golden.jsonl"
    freeze(csv_path, out_path)

    lines = out_path.read_text().splitlines()
    assert len(lines) == 2


def test_load_golden_round_trips_freeze_output(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path,
        [{"question": "What is the refund window?", "expected_chunk_ids": "a, b", "reference_answer": "30 days", "approved": True}],
    )
    out_path = tmp_path / "golden.jsonl"
    freeze(csv_path, out_path)

    rows = load_golden(out_path)

    assert len(rows) == 1
    assert isinstance(rows[0], GoldenRow)
    assert rows[0].question == "What is the refund window?"
    assert rows[0].expected_chunk_ids == ["a", "b"]
    assert rows[0].reference_answer == "30 days"
    assert len(rows[0].id) == 16


def test_load_golden_empty_file_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    assert load_golden(path) == []


def test_load_golden_tolerates_trailing_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text('{"id": "abc123", "question": "Q?", "expected_chunk_ids": ["a"], "reference_answer": null}\n\n')

    rows = load_golden(path)

    assert len(rows) == 1
    assert rows[0].id == "abc123"
