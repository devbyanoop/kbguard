import dataclasses
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from kbguard.models import Chunk, Finding, Snapshot

# Explicit, not inferred from the buffered data: pyarrow infers an empty
# list's column as `null` type rather than `string`/`int64` (confirmed by
# hand), which would give a snapshot of an empty collection a different,
# incompatible chunks.parquet schema than every non-empty snapshot. An
# explicit schema makes every snapshot's schema identical regardless of
# how many chunks it holds.
# Explicitly typed: pa.string()/pa.int64() return distinct subclasses
# (StringType/Int64Type), and mypy won't cleanly infer a common DataType
# join across a mixed dict literal without this annotation.
_chunks_schema_fields: dict[str, pa.DataType] = {
    "id": pa.string(),
    "text": pa.string(),
    "metadata": pa.string(),  # JSON-encoded: client metadata shape is arbitrary/semi-structured
    "source": pa.string(),
    "position": pa.int64(),
    "version": pa.string(),
    "updated_at": pa.string(),  # ISO-8601, not a native parquet timestamp — simpler, exact round-trip
    "title": pa.string(),
}
_CHUNKS_SCHEMA = pa.schema(_chunks_schema_fields)


class SnapshotError(Exception):
    """Raised for a snapshot-writing or -reading problem: a chunk missing
    its embedding, an embedding dimension mismatch, a duplicate chunk id or
    finding fingerprint, or a chunk id that doesn't exist in this snapshot."""


class SnapshotWriter:
    """Append-only: write_chunk/write_finding any number of times, then
    close() exactly once. Everything is buffered in memory and flushed at
    close() — the simple v0.1 approach; spec's 1M-chunk performance target
    is about the *checks'* own ANN indices, not snapshot writing itself.
    """

    def __init__(self, path: Path, collection: str, adapter_name: str, embedding_model: str) -> None:
        self._path = path
        self._collection = collection
        self._adapter_name = adapter_name
        self._embedding_model = embedding_model
        self._chunks: list[Chunk] = []
        self._findings: list[Finding] = []
        self._seen_chunk_ids: set[str] = set()
        self._embedding_dim: int | None = None
        self._closed = False

    def write_chunk(self, chunk: Chunk) -> None:
        self._require_open()
        if chunk.id in self._seen_chunk_ids:
            raise SnapshotError(f"duplicate chunk id {chunk.id!r} written to snapshot")
        if chunk.embedding is None:
            raise SnapshotError(
                f"chunk {chunk.id!r} has no embedding; SnapshotWriter requires every written chunk "
                f"to already be embedded (see ingest/exporter.py)"
            )
        if self._embedding_dim is None:
            self._embedding_dim = len(chunk.embedding)
        elif len(chunk.embedding) != self._embedding_dim:
            raise SnapshotError(
                f"chunk {chunk.id!r} has embedding dimension {len(chunk.embedding)}, "
                f"expected {self._embedding_dim} (set by the first chunk written to this snapshot)"
            )

        self._seen_chunk_ids.add(chunk.id)
        self._chunks.append(chunk)

    def write_finding(self, finding: Finding) -> None:
        self._require_open()
        self._findings.append(finding)

    def close(self) -> Snapshot:
        self._require_open()
        self._closed = True

        self._path.mkdir(parents=True, exist_ok=True)
        pq.write_table(_chunks_to_table(self._chunks), self._path / "chunks.parquet")

        if self._chunks:
            vectors = np.array([c.embedding for c in self._chunks], dtype=np.float32)
            np.save(self._path / "vectors.npy", vectors)

        self._write_index()
        self._write_findings()

        created_at = datetime.now(timezone.utc)
        manifest = {
            "id": self._path.name,
            "collection": self._collection,
            "adapter": self._adapter_name,
            "created_at": created_at.isoformat(),
            "chunk_count": len(self._chunks),
            "finding_count": len(self._findings),
            "embedding_model": self._embedding_model,
            "embedding_dim": self._embedding_dim or 0,
        }
        (self._path / "manifest.json").write_text(json.dumps(manifest, indent=2))

        return Snapshot(
            id=self._path.name,
            collection=self._collection,
            adapter=self._adapter_name,
            created_at=created_at,
            chunk_count=len(self._chunks),
            path=str(self._path),
        )

    def _require_open(self) -> None:
        if self._closed:
            raise SnapshotError("this SnapshotWriter is already closed")

    def _write_index(self) -> None:
        conn = sqlite3.connect(self._path / "index.sqlite")
        try:
            conn.execute("CREATE TABLE chunks_index (id TEXT PRIMARY KEY, row INTEGER NOT NULL)")
            conn.execute("CREATE TABLE source_index (source TEXT NOT NULL, id TEXT NOT NULL)")
            conn.execute("CREATE INDEX source_index_source ON source_index (source)")
            conn.execute("CREATE TABLE finding_fingerprints (fingerprint TEXT PRIMARY KEY, check_name TEXT NOT NULL)")

            conn.executemany(
                "INSERT INTO chunks_index (id, row) VALUES (?, ?)",
                [(c.id, row) for row, c in enumerate(self._chunks)],
            )
            conn.executemany(
                "INSERT INTO source_index (source, id) VALUES (?, ?)",
                [(c.source, c.id) for c in self._chunks if c.source is not None],
            )
            try:
                conn.executemany(
                    "INSERT INTO finding_fingerprints (fingerprint, check_name) VALUES (?, ?)",
                    [(f.fingerprint, f.check) for f in self._findings if f.fingerprint],
                )
            except sqlite3.IntegrityError as exc:
                raise SnapshotError(f"duplicate finding fingerprint written to snapshot: {exc}") from exc

            conn.commit()
        finally:
            conn.close()

    def _write_findings(self) -> None:
        with (self._path / "findings.jsonl").open("w", encoding="utf-8") as f:
            for finding in self._findings:
                f.write(json.dumps(dataclasses.asdict(finding)) + "\n")


class SnapshotReader:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._vectors: np.ndarray | None = None  # lazy-loaded, cached after first use

    def manifest(self) -> dict[str, Any]:
        return json.loads((self._path / "manifest.json").read_text())  # type: ignore[no-any-return]

    def chunks(self) -> Iterator[Chunk]:
        table = pq.read_table(self._path / "chunks.parquet")
        for row in table.to_pylist():
            yield Chunk(
                id=row["id"],
                text=row["text"],
                embedding=None,  # fetch explicitly via .vector(id) — see module docstring
                metadata=json.loads(row["metadata"]),
                source=row["source"],
                position=row["position"],
                version=row["version"],
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                title=row["title"],
            )

    def vector(self, chunk_id: str) -> list[float]:
        conn = sqlite3.connect(self._path / "index.sqlite")
        try:
            result = conn.execute("SELECT row FROM chunks_index WHERE id = ?", (chunk_id,)).fetchone()
        finally:
            conn.close()
        if result is None:
            raise SnapshotError(f"no chunk {chunk_id!r} in this snapshot")
        row = result[0]

        if self._vectors is None:
            # Not mmap_mode="r": a memory-mapped file keeps an open handle
            # that Windows refuses to delete while mapped (confirmed by
            # hand — it broke a temp-directory cleanup), which would risk
            # flaky "file in use" failures in this project's own test suite.
            # Loading fully into memory is simpler and avoids that platform
            # -specific failure mode; worth revisiting only if snapshot
            # vector files actually become large enough to matter.
            self._vectors = np.load(self._path / "vectors.npy")

        return [float(x) for x in self._vectors[row]]

    def vectors(self) -> Iterator[tuple[str, list[float]]]:
        """Bulk access to every chunk's vector, id-aligned — for checks
        (e.g. duplicates) that need to build an index over all of them at
        once rather than looking each one up individually. Deferred from
        when SnapshotWriter/SnapshotReader were first built (Week 1); built
        now that checks/duplicates.py is the real caller that needs it,
        rather than speculatively.
        """
        conn = sqlite3.connect(self._path / "index.sqlite")
        try:
            rows = conn.execute("SELECT id, row FROM chunks_index ORDER BY row").fetchall()
        finally:
            conn.close()

        if self._vectors is None:
            self._vectors = np.load(self._path / "vectors.npy")

        for chunk_id, row in rows:
            yield chunk_id, [float(x) for x in self._vectors[row]]

    def findings(self, check: str | None = None) -> Iterator[Finding]:
        with (self._path / "findings.jsonl").open(encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                if check is not None and data["check"] != check:
                    continue
                yield Finding(**data)


def _chunks_to_table(chunks: list[Chunk]) -> pa.Table:
    return pa.table(
        {
            "id": [c.id for c in chunks],
            "text": [c.text for c in chunks],
            "metadata": [json.dumps(c.metadata) for c in chunks],
            "source": [c.source for c in chunks],
            "position": [c.position for c in chunks],
            "version": [c.version for c in chunks],
            "updated_at": [c.updated_at.isoformat() if c.updated_at else None for c in chunks],
            "title": [c.title for c in chunks],
        },
        schema=_CHUNKS_SCHEMA,
    )
