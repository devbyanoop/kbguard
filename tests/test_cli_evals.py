import json
import sys
import types
from pathlib import Path
from typing import Any

import chromadb
import pytest
from typer.testing import CliRunner

from kbguard.cli import app

runner = CliRunner()


class _FakeJudgeClient:
    """Stands in for kbguard.cli.JudgeClient -- every cli.py command
    constructs JudgeClient(model=..., cache=...) directly, so tests
    monkeypatch the class itself, same pattern test_cli.py's
    test_report_command_regenerates_without_touching_adapter_or_judge
    already established for proving a judge is (or isn't) touched."""

    def __init__(self, model: str, cache: Any, answer: dict[str, Any] | None = None) -> None:
        self.model = model
        self.calls: list[tuple[str, str]] = []
        self._answer = answer or {"question": "What does this say?"}

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        self.calls.append((prompt, schema_hint))
        return self._answer


def _seed_chroma_collection(path: Path, collection: str = "policies") -> None:
    client = chromadb.PersistentClient(path=str(path))
    col = client.create_collection(name=collection, embedding_function=None)
    col.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["Refunds within 30 days.", "Contact support for help."],
        metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}],
    )


def _write_config(tmp_path: Path, chroma_path: Path, extra: str = "") -> Path:
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text(
        "store:\n"
        "  adapter: chroma\n"
        "  collection: policies\n"
        f"  settings: {{path: {chroma_path.as_posix()}}}\n"
        "metadata_map:\n"
        "  source: doc_id\n"
        f"{extra}"
    )
    return config_path


def _scan(tmp_path: Path, config_path: Path) -> Path:
    result = runner.invoke(app, ["scan", "--collection", "policies", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    return next((tmp_path / ".kbguard" / "snapshots").iterdir())


# --- kbguard golden generate / freeze ---


def test_golden_generate_writes_a_review_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path, "judge:\n  model: fake-model\n")
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)

    monkeypatch.setattr("kbguard.cli.JudgeClient", _FakeJudgeClient)
    out_path = tmp_path / "evals" / "golden.csv"

    result = runner.invoke(
        app, ["golden", "generate", "--collection", "policies", "--n", "2", "--out", str(out_path), "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    assert out_path.exists()
    import pandas as pd

    df = pd.read_csv(out_path)
    assert set(df.columns) == {"question", "expected_chunk_ids", "reference_answer", "approved"}
    assert not df["approved"].any()


def test_golden_generate_without_judge_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path)  # no judge: section
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)

    result = runner.invoke(
        app, ["golden", "generate", "--collection", "policies", "--config", str(config_path)]
    )

    assert result.exit_code == 1
    assert "judge" in result.output
    assert "Traceback" not in result.output


def test_golden_freeze_filters_to_approved_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "golden.csv"
    csv_path.write_text(
        "question,expected_chunk_ids,reference_answer,approved\n"
        "Q1?,a,,True\n"
        "Q2?,b,,False\n"
    )
    out_path = tmp_path / "evals" / "golden.jsonl"

    result = runner.invoke(app, ["golden", "freeze", str(csv_path), "--out", str(out_path)])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["question"] == "Q1?"


# --- kbguard calibrate ---


def test_calibrate_writes_calibration_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path, "judge:\n  model: fake-model\n")
    monkeypatch.chdir(tmp_path)

    labels_path = tmp_path / "evals" / "calibration.jsonl"
    labels_path.parent.mkdir(parents=True)
    labels_path.write_text('{"prompt": "p1", "schema_hint": "{}", "key": "conflict", "human_label": true}\n')

    monkeypatch.setattr(
        "kbguard.cli.JudgeClient",
        lambda model, cache: _FakeJudgeClient(model, cache, answer={"conflict": True}),
    )

    result = runner.invoke(app, ["calibrate", "--labels", str(labels_path), "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    written = json.loads((tmp_path / ".kbguard" / "calibration.json").read_text())
    assert written["agreement"] == 1.0
    assert written["model"] == "fake-model"


def test_calibrate_without_judge_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text("store:\n  adapter: chroma\n  collection: x\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["calibrate", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "judge" in result.output


# --- kbguard eval ---


def _fake_embedder_matching_test_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    # The seeded chroma fixture uses 2-dim toy embeddings (never a real
    # model, same reasoning as examples/policy_corpus/'s hand-crafted
    # vectors). get_embedder()'s real default (sentence-transformers,
    # 384-dim) would raise a genuine Chroma dimension mismatch against
    # this fixture -- confirmed by hand, not a cli.py bug. Faked here
    # since these tests exercise the eval *command's* wiring, not a real
    # embedding model.
    monkeypatch.setattr("kbguard.cli.get_embedder", lambda cfg: (lambda text: [1.0, 0.0]))


def test_eval_runs_retrieval_metrics_and_updates_results_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path, "evals:\n  golden: evals/golden.jsonl\n  k: [1, 2]\n")
    monkeypatch.chdir(tmp_path)
    snapshot_dir = _scan(tmp_path, config_path)
    _fake_embedder_matching_test_fixtures(monkeypatch)

    golden_path = tmp_path / "evals" / "golden.jsonl"
    golden_path.parent.mkdir(parents=True)
    golden_path.write_text('{"id": "g1", "question": "refund question", "expected_chunk_ids": ["a"], "reference_answer": null}\n')

    result = runner.invoke(app, ["eval", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    results = json.loads((snapshot_dir / "results.json").read_text())
    assert len(results["eval_results"]) > 0
    assert any(r["metric"].startswith("hit@") for r in results["eval_results"])
    # health/findings from the original scan must survive untouched -- eval never reruns checks.
    assert "health" in results


def test_eval_without_golden_set_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path, "evals:\n  golden: evals/does-not-exist.jsonl\n")
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)

    result = runner.invoke(app, ["eval", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_eval_with_answer_metrics_but_no_calibration_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(
        tmp_path, chroma_path,
        "evals:\n  golden: evals/golden.jsonl\n  metrics: [ragas.faithfulness]\n"
        "judge:\n  model: fake-model\n"
        "target:\n  type: python\n  callable: fake_rag:answer\n",
    )
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)
    _fake_embedder_matching_test_fixtures(monkeypatch)
    golden_path = tmp_path / "evals" / "golden.jsonl"
    golden_path.parent.mkdir(parents=True)
    golden_path.write_text('{"id": "g1", "question": "q", "expected_chunk_ids": ["a"], "reference_answer": null}\n')

    result = runner.invoke(app, ["eval", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "calibrate" in result.output.lower()


def test_eval_with_stale_calibration_model_mismatch_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(
        tmp_path, chroma_path,
        "evals:\n  golden: evals/golden.jsonl\n  metrics: [ragas.faithfulness]\n"
        "judge:\n  model: new-model\n"
        "target:\n  type: python\n  callable: fake_rag:answer\n",
    )
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)
    _fake_embedder_matching_test_fixtures(monkeypatch)
    golden_path = tmp_path / "evals" / "golden.jsonl"
    golden_path.parent.mkdir(parents=True)
    golden_path.write_text('{"id": "g1", "question": "q", "expected_chunk_ids": ["a"], "reference_answer": null}\n')

    calibration_path = tmp_path / ".kbguard" / "calibration.json"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_path.write_text(json.dumps({"model": "old-model", "agreement": 1.0, "kappa": 1.0, "n": 5, "created_at": "2026-01-01T00:00:00+00:00"}))

    result = runner.invoke(app, ["eval", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "old-model" in result.output or "new-model" in result.output


def test_eval_metric_scoring_failure_is_recorded_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real metric.score() call can fail for many reasons beyond
    ValueError -- confirmed by hand with a real Groq 429 rate limit
    during a real `kbguard eval` run, which propagated past the previous
    `except ValueError` and crashed the whole run, discarding every
    already-computed result. `eval`'s own docstring promises one broken
    question never aborts the rest; this locks that promise in for
    metric-scoring failures specifically (the RagTargetError branch
    above already covers target-call failures)."""
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(
        tmp_path, chroma_path,
        "evals:\n  golden: evals/golden.jsonl\n  metrics: [ragas.faithfulness]\n"
        "judge:\n  model: fake-model\n"
        "target:\n  type: python\n  callable: fake_rag:answer\n",
    )
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)
    _fake_embedder_matching_test_fixtures(monkeypatch)

    golden_path = tmp_path / "evals" / "golden.jsonl"
    golden_path.parent.mkdir(parents=True)
    golden_path.write_text('{"id": "g1", "question": "q", "expected_chunk_ids": ["a"], "reference_answer": null}\n')

    calibration_path = tmp_path / ".kbguard" / "calibration.json"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_path.write_text(
        json.dumps(
            {"model": "fake-model", "agreement": 1.0, "kappa": 1.0, "n": 5, "created_at": "2026-01-01T00:00:00+00:00"}
        )
    )

    fake_rag_module = types.ModuleType("fake_rag")
    fake_rag_module.answer = lambda q: {"answer": "an answer", "contexts": ["ctx"]}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_rag", fake_rag_module)

    class _ExplodingMetric:
        name = "faithfulness"

        def score(self, question: str, answer: str, contexts: list[str], reference: str | None, judge: Any) -> Any:
            raise RuntimeError("simulated rate limit from the real provider")

    monkeypatch.setattr("kbguard.cli._load_metric_plugin", lambda name, embedder: _ExplodingMetric())

    result = runner.invoke(app, ["eval", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    snapshot_dir = next((tmp_path / ".kbguard" / "snapshots").iterdir())
    results = json.loads((snapshot_dir / "results.json").read_text())
    faithfulness_results = [r for r in results["eval_results"] if r["metric"] == "faithfulness"]
    assert len(faithfulness_results) == 1
    assert faithfulness_results[0]["passed"] is False
    assert "simulated rate limit" in faithfulness_results[0]["details"]["error"]


# --- kbguard diff ---


def _second_snapshot_with_extra_finding(tmp_path: Path, name: str, finding: Any | None) -> Path:
    # Builds a second snapshot directly via SnapshotWriter rather than a
    # real second `kbguard scan` -- avoids two real issues found by hand:
    # snapshot ids are second-resolution timestamps (a quick real rescan
    # can collide with the first one), and re-adding to an
    # already-persisted Chroma collection in the same process hit a real
    # `InternalError: Error finding id`. This test is about `diff`'s own
    # wiring (reading two snapshot dirs, calling diff_snapshots, exit
    # code), not about re-proving duplicates.py's detection, so
    # constructing the snapshot directly is the more robust, more
    # targeted choice.
    from kbguard.ingest.snapshot import SnapshotWriter
    from kbguard.models import Chunk

    writer = SnapshotWriter(tmp_path / ".kbguard" / "snapshots" / name, collection="policies", adapter_name="chroma", embedding_model="fake")
    writer.write_chunk(Chunk(id="a", text="Refunds within 30 days.", embedding=[1.0, 0.0], metadata={}, source="d1"))
    writer.write_chunk(Chunk(id="b", text="Contact support for help.", embedding=[0.0, 1.0], metadata={}, source="d2"))
    if finding is not None:
        writer.write_finding(finding)
    writer.close()
    return tmp_path / ".kbguard" / "snapshots" / name


def test_diff_with_no_fail_on_always_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path)
    monkeypatch.chdir(tmp_path)
    baseline_dir = _scan(tmp_path, config_path)
    current_dir = _second_snapshot_with_extra_finding(tmp_path, "current_snap_policies", finding=None)
    assert current_dir != baseline_dir

    result = runner.invoke(
        app, ["diff", "--collection", "policies", "--against", baseline_dir.name, "--snapshot", current_dir.name, "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    assert "Health:" in result.output


def test_diff_fails_on_a_new_error_finding_and_suppression_file_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kbguard.models import Finding

    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(
        tmp_path, chroma_path, "fail_on:\n  new_findings: {severity: error, max: 0}\n"
    )
    monkeypatch.chdir(tmp_path)
    baseline_dir = _scan(tmp_path, config_path)

    new_finding = Finding(
        check="duplicates", severity="error", chunk_ids=["a", "b"], message="hand-constructed new finding",
        fingerprint="hand-constructed-fp-1",
    )
    current_dir = _second_snapshot_with_extra_finding(tmp_path, "current_snap_policies", finding=new_finding)

    result = runner.invoke(
        app,
        [
            "diff", "--collection", "policies", "--against", baseline_dir.name,
            "--snapshot", current_dir.name, "--config", str(config_path),
        ],
    )
    assert result.exit_code == 1, result.output

    ignore_path = tmp_path / "kbguard.ignore.yaml"
    ignore_path.write_text("hand-constructed-fp-1:\n  reason: known, accepted for this test\n")

    suppressed_result = runner.invoke(
        app,
        [
            "diff", "--collection", "policies", "--against", baseline_dir.name,
            "--snapshot", current_dir.name, "--config", str(config_path), "--ignore-file", str(ignore_path),
        ],
    )
    assert suppressed_result.exit_code == 0, suppressed_result.output


def test_diff_missing_baseline_snapshot_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = _write_config(tmp_path, chroma_path)
    monkeypatch.chdir(tmp_path)
    _scan(tmp_path, config_path)

    result = runner.invoke(
        app, ["diff", "--collection", "policies", "--against", "does-not-exist", "--config", str(config_path)]
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output
