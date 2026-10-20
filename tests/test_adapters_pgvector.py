import uuid
from typing import Any

import pytest

from kbguard.adapters.base import AdapterConnectionError
from kbguard.adapters.pgvector import PgVectorAdapter


def test_require_conn_raises_before_connect() -> None:
    adapter = PgVectorAdapter()

    with pytest.raises(RuntimeError, match="connect"):
        adapter.collections()


def test_connect_requires_user_setting() -> None:
    adapter = PgVectorAdapter()

    with pytest.raises(ValueError, match="user"):
        adapter.connect(dbname="x")


def test_connect_requires_dbname_setting() -> None:
    adapter = PgVectorAdapter()

    with pytest.raises(ValueError, match="dbname"):
        adapter.connect(user="x")


def test_connect_wraps_a_real_connection_failure() -> None:
    """psycopg.connect() is eager -- a bad host/port raises right here,
    confirmed by hand (also confirmed by hand: with no connect_timeout at
    all, a real unresponsive port took 260 real seconds to give up, which
    is why connect() now always passes one). A small override keeps this
    test itself fast -- libpq enforces an effective floor of 2s/attempt
    regardless of a smaller requested value, and "localhost" resolves to
    both ::1 and 127.0.0.1, so the real worst case here is ~4s, not 0."""
    adapter = PgVectorAdapter()

    with pytest.raises(AdapterConnectionError, match="could not connect to pgvector"):
        adapter.connect(host="localhost", port=1, user="x", dbname="x", password="x", connect_timeout=2)


def test_connect_rejects_unsafe_column_name(pgvector_connect_settings: dict[str, Any]) -> None:
    adapter = PgVectorAdapter()
    bad_settings = {**pgvector_connect_settings, "text_column": "text; DROP TABLE chunks"}

    with pytest.raises(ValueError, match="text_column"):
        adapter.connect(**bad_settings)


def test_search_with_filters_raises_not_implemented(pgvector_connect_settings: dict[str, Any]) -> None:
    adapter = PgVectorAdapter()
    adapter.connect(**pgvector_connect_settings)

    with pytest.raises(NotImplementedError):
        adapter.search("any_table", [1.0], k=1, filters={"source": "x"})


def test_count_rejects_unsafe_collection_name(pgvector_connect_settings: dict[str, Any]) -> None:
    adapter = PgVectorAdapter()
    adapter.connect(**pgvector_connect_settings)

    with pytest.raises(ValueError, match="collection"):
        adapter.count("chunks; DROP TABLE chunks")


def test_custom_column_names(pgvector_connect_settings: dict[str, Any]) -> None:
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg import sql
    from psycopg.types.json import Jsonb

    table_name = f"custom_cols_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(**pgvector_connect_settings, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    table = sql.Identifier(table_name)
    try:
        # Deliberately non-default column names — proves the adapter
        # actually uses the configured names, not just its own defaults.
        conn.execute(
            sql.SQL(
                "CREATE TABLE {} (chunk_id TEXT PRIMARY KEY, body TEXT, extra JSONB, vec VECTOR(2))"
            ).format(table)
        )
        conn.execute(
            sql.SQL("INSERT INTO {} (chunk_id, body, extra, vec) VALUES (%s, %s, %s, %s)").format(table),
            ("x1", "hello custom", Jsonb({"k": "v"}), [1.0, 2.0]),
        )

        adapter = PgVectorAdapter()
        adapter.connect(
            **pgvector_connect_settings,
            id_column="chunk_id",
            text_column="body",
            metadata_column="extra",
            embedding_column="vec",
        )

        chunks = list(adapter.iter_chunks(table_name))
        assert len(chunks) == 1
        assert chunks[0].id == "x1"
        assert chunks[0].text == "hello custom"
        assert chunks[0].metadata == {"k": "v"}
        assert chunks[0].embedding == pytest.approx([1.0, 2.0])
    finally:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
        conn.close()


def test_iter_chunks_pages_across_multiple_batches(pgvector_connect_settings: dict[str, Any]) -> None:
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg import sql

    table_name = f"paging_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(**pgvector_connect_settings, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    table = sql.Identifier(table_name)
    try:
        conn.execute(
            sql.SQL("CREATE TABLE {} (id TEXT PRIMARY KEY, text TEXT, metadata JSONB, embedding VECTOR(1))").format(
                table
            )
        )
        for i in range(5):
            conn.execute(
                sql.SQL("INSERT INTO {} (id, text, metadata, embedding) VALUES (%s, %s, %s, %s)").format(table),
                (f"c{i}", f"text{i}", None, [float(i)]),
            )

        adapter = PgVectorAdapter()
        adapter.connect(**pgvector_connect_settings)

        chunks = list(adapter.iter_chunks(table_name, batch_size=2))
        assert sorted(c.id for c in chunks) == ["c0", "c1", "c2", "c3", "c4"]
    finally:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
        conn.close()
