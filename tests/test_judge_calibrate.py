import json
from pathlib import Path
from typing import Any

import pytest

from kbguard.judge.calibrate import calibrate


class _FakeJudge:
    def __init__(self, answers: dict[str, bool]) -> None:
        # answers keyed by the prompt text -- lets a test control exactly
        # what the judge says for each labeled row.
        self._answers = answers
        self.calls: list[tuple[str, str]] = []
        self.model = "fake-model"

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        self.calls.append((prompt, schema_hint))
        return {"conflict": self._answers[prompt]}


def _write_labels(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "calibration.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def test_full_agreement_gives_kappa_near_one(tmp_path: Path) -> None:
    rows = [
        {"prompt": "pair1", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "pair2", "schema_hint": "{}", "key": "conflict", "human_label": False},
        {"prompt": "pair3", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "pair4", "schema_hint": "{}", "key": "conflict", "human_label": False},
    ]
    labels_path = _write_labels(tmp_path, rows)
    judge = _FakeJudge({"pair1": True, "pair2": False, "pair3": True, "pair4": False})  # judge matches human exactly

    result = calibrate(labels_path, judge, tmp_path / "calibration.json")

    assert result.agreement == 1.0
    assert result.kappa == 1.0


def test_deliberate_disagreement_drops_kappa(tmp_path: Path) -> None:
    rows = [
        {"prompt": "pair1", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "pair2", "schema_hint": "{}", "key": "conflict", "human_label": False},
        {"prompt": "pair3", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "pair4", "schema_hint": "{}", "key": "conflict", "human_label": False},
    ]
    labels_path = _write_labels(tmp_path, rows)
    # Judge disagrees with every single human label.
    judge = _FakeJudge({"pair1": False, "pair2": True, "pair3": False, "pair4": True})

    result = calibrate(labels_path, judge, tmp_path / "calibration.json")

    assert result.agreement == 0.0
    assert result.kappa < 1.0  # strictly worse than the perfect-agreement case


def test_calibration_json_contains_model_id_and_timestamp(tmp_path: Path) -> None:
    rows = [{"prompt": "p1", "schema_hint": "{}", "key": "conflict", "human_label": True}]
    labels_path = _write_labels(tmp_path, rows)
    judge = _FakeJudge({"p1": True})
    out_path = tmp_path / "calibration.json"

    calibrate(labels_path, judge, out_path)

    written = json.loads(out_path.read_text())
    assert written["model"] == "fake-model"
    assert "created_at" in written
    assert written["n"] == 1
    assert written["agreement"] == 1.0


def test_undefined_kappa_from_all_identical_labels_does_not_crash_and_is_zero(tmp_path: Path) -> None:
    # Every human label and every judge answer is True -- no variance at
    # all, which makes Cohen's kappa mathematically undefined (confirmed
    # by hand against sklearn directly: NaN unless replace_undefined_by
    # is set). Must not propagate a NaN into calibration.json.
    rows = [
        {"prompt": "p1", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "p2", "schema_hint": "{}", "key": "conflict", "human_label": True},
        {"prompt": "p3", "schema_hint": "{}", "key": "conflict", "human_label": True},
    ]
    labels_path = _write_labels(tmp_path, rows)
    judge = _FakeJudge({"p1": True, "p2": True, "p3": True})

    result = calibrate(labels_path, judge, tmp_path / "calibration.json")

    assert result.agreement == 1.0
    assert result.kappa == 0.0  # undefined, replaced with 0.0, never NaN


def test_empty_labels_file_raises_clear_error(tmp_path: Path) -> None:
    labels_path = tmp_path / "empty.jsonl"
    labels_path.write_text("")
    judge = _FakeJudge({})

    with pytest.raises(ValueError, match="no calibration labels"):
        calibrate(labels_path, judge, tmp_path / "calibration.json")


def test_blank_lines_in_labels_file_are_tolerated(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        '{"prompt": "p1", "schema_hint": "{}", "key": "conflict", "human_label": true}\n'
        "\n"
        '{"prompt": "p2", "schema_hint": "{}", "key": "conflict", "human_label": false}\n'
    )
    judge = _FakeJudge({"p1": True, "p2": False})

    result = calibrate(labels_path, judge, tmp_path / "calibration.json")

    assert result.n == 2


def test_judge_is_called_once_per_row_with_its_own_prompt_and_schema(tmp_path: Path) -> None:
    rows = [
        {"prompt": "p1", "schema_hint": "schemaA", "key": "conflict", "human_label": True},
        {"prompt": "p2", "schema_hint": "schemaB", "key": "conflict", "human_label": False},
    ]
    labels_path = _write_labels(tmp_path, rows)
    judge = _FakeJudge({"p1": True, "p2": False})

    calibrate(labels_path, judge, tmp_path / "calibration.json")

    assert judge.calls == [("p1", "schemaA"), ("p2", "schemaB")]


def test_key_extraction_reads_the_configured_response_field(tmp_path: Path) -> None:
    class _CustomKeyJudge:
        model = "fake-model"

        def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
            return {"is_duplicate": True, "other_field": "ignored"}

    rows = [{"prompt": "p1", "schema_hint": "{}", "key": "is_duplicate", "human_label": True}]
    labels_path = _write_labels(tmp_path, rows)

    result = calibrate(labels_path, _CustomKeyJudge(), tmp_path / "calibration.json")

    assert result.agreement == 1.0
