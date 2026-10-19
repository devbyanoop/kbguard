from datetime import datetime, timezone
from pathlib import Path

import typer
from pydantic import ValidationError

from kbguard.config import ConfigError, KBGuardConfig
from kbguard.ingest.embeddings import EmbeddingError, get_embedder
from kbguard.ingest.exporter import export_chunks
from kbguard.ingest.metadata import MetadataMappingError
from kbguard.ingest.snapshot import SnapshotError, SnapshotWriter
from kbguard.registry import RegistryError, load_adapter

app = typer.Typer()

_DEFAULT_CONFIG_PATH = Path("kbguard.yaml")


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
)


@app.command()
def scan(
    collection: str = typer.Option(..., "--collection", help="Name of the collection to scan"),
    config: Path = typer.Option(_DEFAULT_CONFIG_PATH, "--config", help="Path to kbguard.yaml"),
) -> None:
    """Pull a collection through its configured adapter and write a snapshot."""
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
        writer = SnapshotWriter(snapshot_path, collection, cfg.store.adapter, cfg.embeddings.model)

        chunks = export_chunks(adapter, collection, cfg.metadata_map, embedder, cfg.embeddings.reuse_stored)
        for chunk in chunks:
            writer.write_chunk(chunk)

        snapshot = writer.close()
    except _USER_FACING_ERRORS as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote snapshot {snapshot.id!r}: {snapshot.chunk_count} chunks -> {snapshot.path}")


if __name__ == "__main__":
    app()
