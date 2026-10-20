import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kbguard.checks.base import JudgeLike

# A calibration row is deliberately generic, not tied to the
# contradictions check's own {"conflict": bool, ...} schema — spec
# section 10's judge contract is shared by contradiction confirmation
# today and future metric plugins, so a calibration label records which
# JSON key of the judge's own response holds its decision ("key"), not a
# hardcoded field name:
#   {"prompt": str, "schema_hint": str, "key": str, "human_label": Any}


@dataclass
class CalibrationResult:
    agreement: float  # plain fraction of labels where judge == human
    kappa: float  # Cohen's kappa -- agreement corrected for chance
    model: str
    n: int
    created_at: datetime


def calibrate(labels_path: Path, judge: JudgeLike, out_path: Path) -> CalibrationResult:
    """Scores every row of a human-labeled calibration set with the judge,
    reports plain agreement and Cohen's kappa, and writes the result to
    `out_path` (spec: `.kbguard/calibration.json`) as a side effect —
    `calibrate` is the only thing that writes this file; `eval` only
    ever reads it (judge/client.py's own docstring, and this file's,
    agree on that boundary so `eval` never re-derives kappa itself).
    """
    rows = _load_labels(labels_path)
    if not rows:
        raise ValueError(f"no calibration labels found in {labels_path}")

    judge_labels: list[Any] = []
    human_labels: list[Any] = []
    for row in rows:
        response = judge.ask_json(row["prompt"], row["schema_hint"])
        judge_labels.append(response.get(row["key"]))
        human_labels.append(row["human_label"])

    agreement = sum(1 for j, h in zip(judge_labels, human_labels, strict=True) if j == h) / len(rows)
    kappa = _cohen_kappa(human_labels, judge_labels)

    result = CalibrationResult(
        agreement=agreement, kappa=kappa, model=judge.model, n=len(rows), created_at=datetime.now(timezone.utc)
    )
    _write_result(result, out_path)
    return result


def _load_labels(labels_path: Path) -> list[dict[str, Any]]:
    rows = []
    with labels_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _cohen_kappa(human_labels: list[Any], judge_labels: list[Any]) -> float:
    # sklearn, not a hand-rolled formula -- this is exactly the kind of
    # statistic where a library implementation is more trustworthy than a
    # quick derivation (verified: 1.0 for identical label lists, 0.0 for
    # chance-level agreement, confirmed by hand against sklearn directly
    # before trusting it).
    from sklearn.metrics import cohen_kappa_score

    # replace_undefined_by=0.0: confirmed by hand that sklearn's own
    # default (NaN) only occurs when kappa is mathematically undefined
    # (e.g. every human label is identical, making the chance-agreement
    # term 1.0) -- passing this directly means sklearn itself returns
    # 0.0 in that case, never NaN, so there's nothing left to patch up
    # afterward. 0.0 reads as "no measurable agreement beyond chance," a
    # safer default for a gate than a NaN silently flowing into
    # calibration.json.
    return float(cohen_kappa_score(human_labels, judge_labels, replace_undefined_by=0.0))


def _write_result(result: CalibrationResult, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agreement": result.agreement,
        "kappa": result.kappa,
        "model": result.model,
        "n": result.n,
        "created_at": result.created_at.isoformat(),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
