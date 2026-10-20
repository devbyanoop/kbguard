from datetime import datetime, timezone
from pathlib import Path

import typer
from pydantic import ValidationError

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.checks.base import CheckContext
from kbguard.checks.contradictions import ContradictionsCheckError
from kbguard.config import ConfigError, KBGuardConfig
from kbguard.ingest.embeddings import EmbeddingError, get_embedder
from kbguard.ingest.exporter import export_chunks
from kbguard.ingest.metadata import MetadataMappingError
from kbguard.ingest.snapshot import SnapshotError, SnapshotReader, SnapshotWriter, append_findings
from kbguard.judge.cache import JudgeCache
from kbguard.judge.client import JudgeClient
from kbguard.models import Finding, Snapshot
from kbguard.registry import RegistryError, load_adapter, load_check
from kbguard.report.html import render_html
from kbguard.report.results import ScanResults
from kbguard.scoring.health import compute_health, summarize_findings

app = typer.Typer()

_DEFAULT_CONFIG_PATH = Path("kbguard.yaml")

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
)


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


if __name__ == "__main__":
    app()
