from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kbguard.config import FailOnConfig, HealthWeights
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import EvalResult, Finding
from kbguard.scoring.health import compute_health, summarize_findings

_SEVERITY_ORDER = {"info": 0, "warn": 1, "error": 2}


@dataclass
class DiffResult:
    health_delta: int  # current - baseline; negative means health got worse
    new_findings: list[Finding]  # every new finding, including suppressed ones -- never silently hidden
    resolved_findings: list[Finding]
    metric_deltas: dict[str, float]  # current mean - baseline mean, per metric name
    # Not in the architecture spec's own shape sketch, added because the
    # spec's own design note requires it: "a suppressed fingerprint ...
    # should still appear in the diff output as suppressed, not silently
    # vanish" — this is how a caller tells which of new_findings were
    # suppressed without mutating Finding itself (a model shared by every
    # check, not diff-specific).
    suppressed_fingerprints: set[str] = field(default_factory=set)


def load_suppressions(path: Path) -> set[str]:
    """Reads kbguard.ignore.yaml — a flat mapping of fingerprint to
    whatever metadata a team wants to record (a reason, who approved it,
    ...); only the keys matter here. Returns an empty set, not an error,
    when the file doesn't exist at all — most collections never need one.
    """
    if not path.exists():
        return set()
    raw = yaml.safe_load(path.read_text()) or {}
    return set(raw.keys())


def diff_snapshots(
    baseline: SnapshotReader,
    current: SnapshotReader,
    fail_on: FailOnConfig,
    suppressions: set[str],
    weights: HealthWeights | None = None,
    baseline_eval_results: list[EvalResult] | None = None,
    current_eval_results: list[EvalResult] | None = None,
) -> tuple[DiffResult, int]:
    """Compares two snapshots and decides whether this is a passing or
    failing check — spec section 12, as fixed (the single
    `--against <baseline> [--snapshot <new>]` CLI form).

    "New" and "resolved" are nothing fuzzier than a set difference over
    `Finding.fingerprint` — this is the concrete payoff of fingerprints
    being stable across re-scans of unchanged content (models.py's
    `compute_fingerprint`).
    """
    baseline_by_fp = {f.fingerprint: f for f in baseline.findings() if f.fingerprint}
    current_by_fp = {f.fingerprint: f for f in current.findings() if f.fingerprint}

    new_fps = set(current_by_fp) - set(baseline_by_fp)
    resolved_fps = set(baseline_by_fp) - set(current_by_fp)

    new_findings = [current_by_fp[fp] for fp in sorted(new_fps)]
    resolved_findings = [baseline_by_fp[fp] for fp in sorted(resolved_fps)]
    suppressed_among_new = new_fps & suppressions

    weights = weights or HealthWeights()
    baseline_health = compute_health(summarize_findings(baseline), weights)
    current_health = compute_health(summarize_findings(current), weights)
    health_delta = current_health - baseline_health

    metric_deltas = _metric_deltas(baseline_eval_results or [], current_eval_results or [])

    result = DiffResult(
        health_delta=health_delta,
        new_findings=new_findings,
        resolved_findings=resolved_findings,
        metric_deltas=metric_deltas,
        suppressed_fingerprints=suppressed_among_new,
    )
    exit_code = _exit_code(result, fail_on, suppressed_among_new)
    return result, exit_code


def _metric_deltas(baseline_results: list[EvalResult], current_results: list[EvalResult]) -> dict[str, float]:
    baseline_means = _mean_by_metric(baseline_results)
    current_means = _mean_by_metric(current_results)
    return {
        metric: current_means[metric] - baseline_means[metric]
        for metric in current_means
        if metric in baseline_means
    }


def _mean_by_metric(results: list[EvalResult]) -> dict[str, float]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for result in results:
        totals[result.metric] = totals.get(result.metric, 0.0) + result.value
        counts[result.metric] = counts.get(result.metric, 0) + 1
    return {metric: totals[metric] / counts[metric] for metric in totals}


def _exit_code(result: DiffResult, fail_on: FailOnConfig, suppressed_among_new: set[str]) -> int:
    if fail_on.health_drop is not None and -result.health_delta >= fail_on.health_drop:
        return 1

    if fail_on.new_findings is not None:
        threshold = _SEVERITY_ORDER[fail_on.new_findings.severity]
        # Suppressed fingerprints never count toward this gate — spec:
        # "a suppressed finding ... shouldn't count toward
        # fail_on.new_findings" — but they're still in result.new_findings
        # for visibility, counted here only for the pass/fail decision.
        counted = sum(
            1
            for f in result.new_findings
            if f.fingerprint not in suppressed_among_new and _SEVERITY_ORDER[f.severity] >= threshold
        )
        if counted > fail_on.new_findings.max:
            return 1

    for metric, max_drop in fail_on.metric_drop.items():
        delta = result.metric_deltas.get(metric)
        if delta is not None and -delta >= max_drop:
            return 1

    return 0
