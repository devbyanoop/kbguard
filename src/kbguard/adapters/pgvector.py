import re
from collections.abc import Iterator
from typing import Any

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import sql

from kbguard.config import resolve_env
from kbguard.models import Chunk

# Table/column names come from config (spec: pgvector adapter must work
# against a client's existing schema, not impose its own). Identifiers
# can't be passed as query parameters the way values can (no %s for a
# table/column name) — psycopg.sql.Identifier() safely quotes whatever
# string it's given, but this still validates against a strict allowlist
# first and fails with a clear message, rather than silently accepting an
# unusual identifier that merely happens not to be a SQL injection vector.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str, *, what: str) -> sql.Identifier:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"{what} {name!r} is not a valid SQL identifier (letters, digits, underscore, "
            f"can't start with a digit) — refusing to use it in a query"
        )
    return sql.Identifier(name)


def _require_setting(settings: dict[str, Any], key: str) -> Any:
    if key not in settings:
        raise ValueError(f"store.settings.{key} is required for the pgvector adapter")
    return settings[key]


class PgVectorAdapter:
    name = "pgvector"

    def __init__(self) -> None:
        self._conn: psycopg.Connection[Any] | None = None
        self._id_column = "id"
        self._text_column = "text"
        self._metadata_column = "metadata"
        self._embedding_column = "embedding"

    def connect(self, **settings: Any) -> None:
        host = settings.get("host", "localhost")
        port = settings.get("port", 5432)
        user = _require_setting(settings, "user")
        dbname = _require_setting(settings, "dbname")
        password_env = settings.get("password_env")
        password = resolve_env(password_env) if password_env else settings.get("password")

        self._id_column = settings.get("id_column", "id")
        self._text_column = settings.get("text_column", "text")
        self._metadata_column = settings.get("metadata_column", "metadata")
        self._embedding_column = settings.get("embedding_column", "embedding")
        # Validated once here, not per-query — a bad identifier should fail
        # at connect() time, not confusingly deep inside the first scan.
        for value, what in [
            (self._id_column, "id_column"),
            (self._text_column, "text_column"),
            (self._metadata_column, "metadata_column"),
            (self._embedding_column, "embedding_column"),
        ]:
            _safe_identifier(value, what=what)

        # autocommit: kbguard never writes, so there's nothing to commit or
        # roll back — no reason to hold an open transaction across calls.
        self._conn = psycopg.connect(
            host=host, port=port, user=user, password=password, dbname=dbname, autocommit=True
        )
        # Requires the vector extension already enabled on the target
        # database — kbguard never runs CREATE EXTENSION itself (DDL is a
        # write; read-only is a hard design constraint, not a default).
        register_vector(self._conn)

    def _require_conn(self) -> psycopg.Connection[Any]:
        if self._conn is None:
            raise RuntimeError("PgVectorAdapter.connect() must be called before use")
        return self._conn

    def collections(self) -> list[str]:
        rows = self._require_conn().execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
        return [row[0] for row in rows]

    def count(self, collection: str) -> int:
        table = _safe_identifier(collection, what="collection")
        row = self._require_conn().execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()
        assert row is not None
        return row[0]  # type: ignore[no-any-return]

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        conn = self._require_conn()
        table = _safe_identifier(collection, what="collection")
        id_col = sql.Identifier(self._id_column)
        select_cols = [id_col, sql.Identifier(self._text_column), sql.Identifier(self._metadata_column)]
        if with_embeddings:
            select_cols.append(sql.Identifier(self._embedding_column))

        # Keyset (id > :last), not OFFSET: a row inserted or deleted mid-scan
        # can make OFFSET skip or repeat rows on a live, multi-writer table
        # — a real risk for pgvector specifically, unlike Chroma, which is
        # typically local and single-writer.
        query = sql.SQL("SELECT {} FROM {} WHERE {} > %s ORDER BY {} LIMIT %s").format(
            sql.SQL(", ").join(select_cols), table, id_col, id_col
        )

        last_id = ""
        while True:
            rows = conn.execute(query, (last_id, batch_size)).fetchall()
            if not rows:
                return
            for row in rows:
                chunk_id, text, metadata = row[0], row[1], row[2]
                embedding = row[3].to_list() if with_embeddings and row[3] is not None else None
                yield Chunk(id=chunk_id, text=text, embedding=embedding, metadata=dict(metadata or {}))
            last_id = rows[-1][0]

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if filters is not None:
            # Silently ignoring filters would return unfiltered results to
            # a caller that explicitly asked for filtered ones — wrong in
            # a way that's hard to notice. No caller passes filters yet;
            # pgvector's filter translation lands when one actually needs it.
            raise NotImplementedError("PgVectorAdapter.search() doesn't support filters yet")

        conn = self._require_conn()
        table = _safe_identifier(collection, what="collection")
        id_col = sql.Identifier(self._id_column)
        text_col = sql.Identifier(self._text_column)
        meta_col = sql.Identifier(self._metadata_column)
        emb_col = sql.Identifier(self._embedding_column)

        # <=> is pgvector's cosine distance operator (lower = closer);
        # ORDER BY distance ASC satisfies the Protocol's best-match-first
        # guarantee directly — no re-sorting needed.
        query = sql.SQL("SELECT {}, {}, {}, {}, {} <=> %s AS distance FROM {} ORDER BY distance LIMIT %s").format(
            id_col, text_col, meta_col, emb_col, emb_col, table
        )
        rows = conn.execute(query, (Vector(query_vector), k)).fetchall()

        results: list[tuple[Chunk, float]] = []
        for row in rows:
            chunk_id, text, metadata, raw_embedding, distance = row
            embedding = raw_embedding.to_list() if raw_embedding is not None else None
            chunk = Chunk(id=chunk_id, text=text, embedding=embedding, metadata=dict(metadata or {}))
            results.append((chunk, float(distance)))
        return results
