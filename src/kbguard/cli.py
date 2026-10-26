from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from kbguard.adapters.base import AdapterConnectionError, VectorStoreAdapter
from kbguard.checks.base import CheckContext
from kbguard.checks.contradictions import ContradictionsCheckError
from kbguard.checks.duplicates import DuplicatesCheckError
from kbguard.config import ConfigError, KBGuardConfig
from kbguard.evals.golden import freeze as freeze_golden
from kbguard.evals.golden import generate as generate_golden
from kbguard.evals.golden import load_golden
from kbguard.evals.retrieval import evaluate_retrieval
from kbguard.evals.target import RagTarget, RagTargetError
from kbguard.ingest.embeddings import EmbeddingError, get_embedder
from kbguard.ingest.exporter import export_chunks
from kbguard.ingest.metadata import MetadataMappingError
from kbguard.ingest.snapshot import SnapshotError, SnapshotReader, SnapshotWriter, append_findings
from kbguard.judge.cache import JudgeCache
from kbguard.judge.calibrate import calibrate as run_calibration
from kbguard.judge.client import JudgeClient, JudgeError
from kbguard.models import EvalResult, Finding, Snapshot
from kbguard.registry import RegistryError, load_adapter, load_check
from kbguard.report.html import render_html
from kbguard.report.results import ScanResults
from kbguard.scoring.diff import diff_snapshots, load_suppressions
from kbguard.scoring.health import compute_health, summarize_findings

app = typer.Typer()
golden_app = typer.Typer()
app.add_typer(golden_app, name="golden")

_DEFAULT_CONFIG_PATH = Path("kbguard.yaml")
_DEFAULT_IGNORE_PATH = Path("kbguard.ignore.yaml")
_CALIBRATION_PATH = Path(".kbguard") / "calibration.json"

# metrics: name -> (module path, class name) -- lazily imported, never at
# cli.py's own top level, so `kbguard scan` (the common case) never pays
# for ragas/deepeval's genuinely heavy dependency trees just because this
# file knows these names exist.
_METRIC_PLUGINS = {
    "ragas.faithfulness": ("kbguard.evals.metrics.ragas_plugin", "RagasFaithfulness"),
    "ragas.answer_relevancy": ("kbguard.evals.metrics.ragas_plugin", "RagasAnswerRelevancy"),
    "ragas.context_precision": ("kbguard.evals.metrics.ragas_plugin", "RagasContextPrecision"),
    "ragas.context_recall": ("kbguard.evals.metrics.ragas_plugin", "RagasContextRecall"),
    "deepeval.faithfulness": ("kbguard.evals.metrics.deepeval_plugin", "DeepevalFaithfulness"),
    "deepeval.answer_relevancy": ("kbguard.evals.metrics.deepeval_plugin", "DeepevalAnswerRelevancy"),
    "deepeval.context_precision": ("kbguard.evals.metrics.deepeval_plugin", "DeepevalContextualPrecision"),
    "deepeval.context_recall": ("kbguard.evals.metrics.deepeval_plugin", "DeepevalContextualRecall"),
}

# Run in this fixed order on every scan, each against the config section of
# the same name — the only built-in checks wired into the CLI today. A
# third-party check registered via the same "kbguard.checks" entry-point
# group still works when invoked directly (registry.load_check), just
# isn't automatically included in `scan`'s pipeline yet — that's a real,
# documented v0.1 scope limit, not an oversight.
_BUILTIN_CHECK_NAMES = ["duplicates", "stale_versions", "chunking_damage", "contradictions"]


@app.callback()
def main() -> None:
    """kbguard: knowledge-base QA and evals for RAG systems."""
    # Deliberately empty. Typer collapses a Typer() app with exactly one
    # registered command into a bare top-level command (no subcommand name
    # needed) — "kbguard --collection x" instead of "kbguard scan
    # --collection x" — unless a callback is registered, which forces
    # subcommand ("group") mode regardless of command count. `scan` is the
    # only command today, but `golden`/`eval`/`calibrate`/`diff`/`report`
    # are coming (Weeks 2-3), so this needs to behave as a subcommand from
    # the start, not be restructured once a second command arrives.

# Every exception type a scan can legitimately raise for a *user* mistake
# (bad config, unknown adapter, bad metadata_map, missing credentials, a
# snapshot-writing invariant violated) — caught once here so the CLI prints
# one clear line, not a Python traceback. Anything NOT in this tuple is an
# actual bug, and should surface as a real traceback, not be swallowed.
_USER_FACING_ERRORS = (
    FileNotFoundError,
    ValidationError,
    ConfigError,
    RegistryError,
    MetadataMappingError,
    EmbeddingError,
    SnapshotError,
    ContradictionsCheckError,
    DuplicatesCheckError,
    AdapterConnectionError,
    JudgeError,
)


def _resolve_snapshot_path(collection: str, snapshot_id: str | None) -> Path:
    if snapshot_id is not None:
        path = Path(".kbguard") / "snapshots" / snapshot_id
        if not path.is_dir():
            raise FileNotFoundError(f"no snapshot directory at {path}")
        return path

    # Omitting --snapshot uses the most recent snapshot for the
    # collection (spec section 12) -- snapshot ids are ISO-timestamp-
    # prefixed (cli.py's own `scan` builds them that way), so lexical
    # sort is chronological sort, no parsing needed.
    snapshots_dir = Path(".kbguard") / "snapshots"
    candidates = sorted(
        p for p in snapshots_dir.glob(f"*_{collection}") if p.is_dir()
    ) if snapshots_dir.is_dir() else []
    if not candidates:
        raise FileNotFoundError(f"no snapshot found for collection {collection!r} under {snapshots_dir}")
    return candidates[-1]


def _load_metric_plugin(name: str, embedder: Any) -> Any:
    if name not in _METRIC_PLUGINS:
        raise ConfigError(f"unknown metric {name!r} in evals.metrics -- known metrics: {sorted(_METRIC_PLUGINS)}")
    module_path, class_name = _METRIC_PLUGINS[name]
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    if class_name == "RagasAnswerRelevancy":
        return cls(embedder=embedder)  # the one metric that also needs an embedding model, not just a judge
    return cls()


def _run_checks(cfg: KBGuardConfig, adapter: VectorStoreAdapter, collection: str, snapshot_path: Path) -> None:
    """Runs every built-in check against the just-closed snapshot at
    snapshot_path, appending whatever they find back into it. Needs a
    SnapshotReader (not the SnapshotWriter that just closed) — see
    ingest/snapshot.py's append_findings docstring for why that ordering
    is unavoidable, not an oversight.
    """
    reader = SnapshotReader(snapshot_path)

    judge = None
    if cfg.judge is not None:
        judge = JudgeClient(model=cfg.judge.model, cache=JudgeCache(snapshot_path / "judge_cache.sqlite"))

    findings: list[Finding] = []
    for name in _BUILTIN_CHECK_NAMES:
        check_config = getattr(cfg.checks, name)
        if not check_config.enabled:
            continue
        check = load_check(name)()
        ctx = CheckContext(config=check_config, adapter=adapter, collection=collection, judge=judge)
        findings.extend(check.run(reader, ctx))

    if findings:
        append_findings(snapshot_path, findings)


def _write_report(cfg: KBGuardConfig, snapshot: Snapshot, snapshot_path: Path) -> None:
    reader = SnapshotReader(snapshot_path)
    summary = summarize_findings(reader)
    health = compute_health(summary, cfg.health)
    results = ScanResults(snapshot=snapshot, health=health, findings=list(reader.findings()))
    results.to_json(snapshot_path / "results.json")
    render_html(results, snapshot_path / "report.html")


@app.command()
def scan(
    collection: str = typer.Option(..., "--collection", help="Name of the collection to scan"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config", help="Path to kbguard.yaml"),
) -> None:
    """Pull a collection through its configured adapter, run every enabled
    check, and write a snapshot plus results.json/report.html."""
    try:
        cfg = KBGuardConfig.from_yaml(config)

        adapter = load_adapter(cfg.store.adapter)()
        connect_settings = dict(cfg.store.settings)
        if cfg.store.text_field is not None:
            # store.text_field is a sibling of store.settings in the config
            # schema (for stores that keep chunk text inside metadata/payload
            # rather than a distinct field, e.g. Qdrant) — merged in here so
            # every adapter receives it as a plain settings key uniformly,
            # rather than connect() needing two separate parameters.
            connect_settings["text_field"] = cfg.store.text_field
        adapter.connect(**connect_settings)

        embedder = get_embedder(cfg.embeddings)

        snapshot_id = f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%S}_{collection}"
        snapshot_path = Path(".kbguard") / "snapshots" / snapshot_id
        writer = SnapshotWriter(
            snapshot_path, collection, cfg.store.adapter, cfg.embeddings.model, iteration_mode=adapter.iteration_mode
        )

        chunks = export_chunks(adapter, collection, cfg.metadata_map, embedder, cfg.embeddings.reuse_stored)
        for chunk in chunks:
            writer.write_chunk(chunk)

        snapshot = writer.close()

        _run_checks(cfg, adapter, collection, snapshot_path)
        _write_report(cfg, snapshot, snapshot_path)
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Wrote snapshot {snapshot.id!r}: {snapshot.chunk_count} chunks -> {snapshot.path} "
        f"(report.html, results.json)"
    )


@app.command()
def report(
    snapshot_id: str = typer.Argument(..., help="Snapshot id under .kbguard/snapshots/ to report on"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config", help="Path to kbguard.yaml (for health weights)"),
) -> None:
    """Regenerate results.json and report.html from an existing snapshot's
    already-computed findings, without re-scanning the store or re-running
    any check (so no adapter connection and no judge call happen here)."""
    try:
        snapshot_path = Path(".kbguard") / "snapshots" / snapshot_id
        if not snapshot_path.is_dir():
            raise FileNotFoundError(f"no snapshot directory at {snapshot_path}")

        cfg = KBGuardConfig.from_yaml(config)
        reader = SnapshotReader(snapshot_path)
        manifest = reader.manifest()
        snapshot = Snapshot(
            id=manifest["id"],
            collection=manifest["collection"],
            adapter=manifest["adapter"],
            created_at=datetime.fromisoformat(manifest["created_at"]),
            chunk_count=manifest["chunk_count"],
            path=str(snapshot_path),
        )
        _write_report(cfg, snapshot, snapshot_path)
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Regenerated report for snapshot {snapshot_id!r} -> {snapshot_path / 'report.html'}")


@golden_app.command("generate")
def golden_generate(
    collection: str = typer.Option(..., "--collection", help="Collection whose snapshot to sample chunks from"),
    n: int = typer.Option(100, "--n", help="How many chunks to sample"),
    out: Path = typer.Option(Path("evals/golden.csv"), "--out", help="Where to write the review CSV"),
    snapshot_id: str | None = typer.Option(None, "--snapshot", help="Defaults to the most recent snapshot"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
) -> None:
    """Samples chunks and asks the judge to write candidate questions for
    human review — nothing is approved automatically."""
    try:
        cfg = KBGuardConfig.from_yaml(config)
        if cfg.judge is None:
            raise ConfigError("judge: must be configured in kbguard.yaml to run `kbguard golden generate`")

        snapshot_path = _resolve_snapshot_path(collection, snapshot_id)
        reader = SnapshotReader(snapshot_path)
        judge = JudgeClient(model=cfg.judge.model, cache=JudgeCache(snapshot_path / "judge_cache.sqlite"))

        df = generate_golden(reader, n, judge)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote {len(df)} candidate questions to {out} -- review and mark 'approved' before freezing")


@golden_app.command("freeze")
def golden_freeze(
    csv_path: Path = typer.Argument(..., help="Reviewed CSV from `kbguard golden generate`"),
    out: Path = typer.Option(Path("evals/golden.jsonl"), "--out", help="Where to write the frozen golden set"),
) -> None:
    """Filters a reviewed CSV down to approved rows and assigns each a
    stable id."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        freeze_golden(csv_path, out)
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote frozen golden set to {out}")


@app.command("calibrate")
def calibrate_command(
    labels: Path = typer.Option(Path("evals/calibration.jsonl"), "--labels", help="Human-labeled calibration set"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
) -> None:
    """Scores the calibration set with the judge, reports agreement and
    Cohen's kappa, and writes .kbguard/calibration.json — the one file
    `kbguard eval` reads to decide whether to gate on judge quality."""
    try:
        cfg = KBGuardConfig.from_yaml(config)
        if cfg.judge is None:
            raise ConfigError("judge: must be configured in kbguard.yaml to run `kbguard calibrate`")

        judge = JudgeClient(model=cfg.judge.model, cache=JudgeCache(Path(".kbguard") / "calibrate_cache.sqlite"))
        result = run_calibration(labels, judge, _CALIBRATION_PATH)
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Calibration ({result.n} labels): agreement={result.agreement:.2f} kappa={result.kappa:.2f} "
        f"-> {_CALIBRATION_PATH}"
    )


def _check_calibration_gate(cfg: KBGuardConfig) -> None:
    assert cfg.judge is not None  # only called when answer metrics (which need a judge) are configured
    if not _CALIBRATION_PATH.is_file():
        raise ConfigError(f"no calibration found at {_CALIBRATION_PATH} -- run `kbguard calibrate` first")
    import json

    data = json.loads(_CALIBRATION_PATH.read_text())
    if data["model"] != cfg.judge.model:
        raise ConfigError(
            f"calibration.json was written for judge model {data['model']!r}, "
            f"but judge.model is now {cfg.judge.model!r} -- run `kbguard calibrate` again"
        )
    if data["agreement"] < cfg.judge.min_agreement:
        raise ConfigError(
            f"judge agreement {data['agreement']:.2f} is below judge.min_agreement {cfg.judge.min_agreement} "
            f"-- `kbguard eval` refuses to trust an uncalibrated judge for answer-quality metrics"
        )


@app.command("eval")
def eval_command(
    collection: str = typer.Option(..., "--collection"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    snapshot_id: str | None = typer.Option(None, "--snapshot", help="Defaults to the most recent snapshot"),
) -> None:
    """Runs retrieval metrics (always) and configured answer-quality
    metrics (if evals.metrics/target/judge are all set) against the
    golden set, merging results into the snapshot's results.json and
    report.html. One broken question's target call never aborts the
    rest — it's reported as a failed EvalResult instead."""
    try:
        cfg = KBGuardConfig.from_yaml(config)
        if cfg.evals is None:
            raise ConfigError("evals: must be configured in kbguard.yaml to run `kbguard eval`")

        snapshot_path = _resolve_snapshot_path(collection, snapshot_id)
        reader = SnapshotReader(snapshot_path)
        manifest = reader.manifest()

        golden = load_golden(cfg.evals.golden)
        if not golden:
            raise ConfigError(f"no golden rows found at {cfg.evals.golden}")

        adapter = load_adapter(manifest["adapter"])()
        connect_settings = dict(cfg.store.settings)
        if cfg.store.text_field is not None:
            connect_settings["text_field"] = cfg.store.text_field
        adapter.connect(**connect_settings)
        embedder = get_embedder(cfg.embeddings)

        eval_results = evaluate_retrieval(golden, adapter, collection, reader, cfg.evals.k, embedder)

        if cfg.evals.metrics:
            if cfg.judge is None:
                raise ConfigError("judge: must be configured to run answer-quality metrics (evals.metrics)")
            if cfg.target is None:
                raise ConfigError("target: must be configured to run answer-quality metrics (evals.metrics)")
            _check_calibration_gate(cfg)

            judge = JudgeClient(model=cfg.judge.model, cache=JudgeCache(snapshot_path / "judge_cache.sqlite"))
            target = RagTarget(cfg.target)
            metrics = [_load_metric_plugin(name, embedder) for name in cfg.evals.metrics]

            for row in golden:
                try:
                    answer, contexts = target.answer(row.question)
                except RagTargetError as exc:
                    for metric in metrics:
                        eval_results.append(
                            EvalResult(
                                question_id=row.id, metric=metric.name, value=0.0, passed=False,
                                cause="generation", details={"error": str(exc)},
                            )
                        )
                    continue
                for metric in metrics:
                    try:
                        result = metric.score(row.question, answer, contexts, row.reference_answer, judge)
                    except Exception as exc:  # noqa: BLE001 -- deliberately broad: ragas/deepeval/litellm
                        # each raise their own library-specific exceptions for real-world judge-call
                        # failures (rate limits, timeouts, auth errors), not just ValueError (e.g.
                        # context_recall on a golden row with no reference_answer) -- confirmed by
                        # hand: a real Groq 429 during a real eval run previously propagated past a
                        # narrower `except ValueError` and crashed the whole eval, discarding every
                        # already-computed result, which contradicts this command's own documented
                        # "one broken question never aborts the rest" contract.
                        eval_results.append(
                            EvalResult(
                                question_id=row.id, metric=metric.name, value=0.0, passed=False,
                                cause="generation", details={"error": str(exc)},
                            )
                        )
                        continue
                    result.question_id = row.id
                    eval_results.append(result)

        results_path = snapshot_path / "results.json"
        existing = ScanResults.from_json(results_path) if results_path.is_file() else None
        snapshot = existing.snapshot if existing is not None else Snapshot(
            id=manifest["id"], collection=manifest["collection"], adapter=manifest["adapter"],
            created_at=datetime.fromisoformat(manifest["created_at"]), chunk_count=manifest["chunk_count"],
            path=str(snapshot_path),
        )
        findings = existing.findings if existing is not None else list(reader.findings())
        health = existing.health if existing is not None else compute_health(summarize_findings(reader), cfg.health)

        results = ScanResults(snapshot=snapshot, health=health, findings=findings, eval_results=eval_results)
        results.to_json(results_path)
        render_html(results, snapshot_path / "report.html")
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote {len(eval_results)} eval results -> {snapshot_path / 'results.json'}")


@app.command("diff")
def diff_command(
    collection: str = typer.Option(..., "--collection"),
    against: str = typer.Option(..., "--against", help="Baseline snapshot id"),
    snapshot_id: str | None = typer.Option(None, "--snapshot", help="Defaults to the most recent snapshot"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config"),
    ignore_file: Path = typer.Option(_DEFAULT_IGNORE_PATH, "--ignore-file"),
) -> None:
    """Compares a snapshot against a baseline and exits non-zero when any
    fail_on rule triggers — the single `--against <baseline> [--snapshot
    <new>]` CLI form (spec section 12, as fixed)."""
    try:
        cfg = KBGuardConfig.from_yaml(config)
        baseline_path = Path(".kbguard") / "snapshots" / against
        if not baseline_path.is_dir():
            raise FileNotFoundError(f"no snapshot directory at {baseline_path}")
        current_path = _resolve_snapshot_path(collection, snapshot_id)

        baseline = SnapshotReader(baseline_path)
        current = SnapshotReader(current_path)
        suppressions = load_suppressions(ignore_file)
        baseline_evals = _read_eval_results(baseline_path)
        current_evals = _read_eval_results(current_path)

        result, exit_code = diff_snapshots(
            baseline, current, cfg.fail_on, suppressions, cfg.health, baseline_evals, current_evals
        )
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Health: {result.health_delta:+d} | "
        f"New findings: {len(result.new_findings)} ({len(result.suppressed_fingerprints)} suppressed) | "
        f"Resolved: {len(result.resolved_findings)}"
    )
    for metric, delta in sorted(result.metric_deltas.items()):
        typer.echo(f"  {metric}: {delta:+.3f}")
    raise typer.Exit(code=exit_code)


def _read_eval_results(snapshot_path: Path) -> list[EvalResult]:
    results_path = snapshot_path / "results.json"
    if not results_path.is_file():
        return []
    return ScanResults.from_json(results_path).eval_results


if __name__ == "__main__":
    app()
