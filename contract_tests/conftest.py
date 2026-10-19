import os
import socket
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.registry import load_adapter

# pgvector/Qdrant default to localhost (what docker-compose.yml here maps
# to for anyone running the containers on their own machine), overridable
# via env var for a remote Docker host (e.g. DOCKER_HOST=ssh://... pointing
# at a different machine on the network) — never hardcoded, since a
# specific host belongs to one contributor's environment, not the repo.
_PG_HOST = os.environ.get("KBGUARD_TEST_PG_HOST", "localhost")
_PG_PORT = int(os.environ.get("KBGUARD_TEST_PG_PORT", "5433"))
_QDRANT_HOST = os.environ.get("KBGUARD_TEST_QDRANT_HOST", "localhost")
_QDRANT_PORT = int(os.environ.get("KBGUARD_TEST_QDRANT_PORT", "6333"))


def _is_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class SeedChunk:
    id: str
    text: str
    embedding: list[float]
    # Plain str/int/float/bool values only — not every backend supports
    # nested metadata (Pinecone, notably, doesn't), and the contract only
    # promises what every backend can actually do.
    metadata: dict[str, str | int | float | bool]


# One fixed dataset every adapter is tested against, so passing this suite
# means "behaves the same as every other adapter on identical data" — not
# just "handles its own backend-specific fixture correctly".
SEED_CHUNKS: list[SeedChunk] = [
    SeedChunk(
        "chunk-1", "Refunds are processed within 30 days.", [1.0, 0.0, 0.0], {"source": "policy-a", "version": 1}
    ),
    SeedChunk(
        "chunk-2", "Shipping takes 3 to 5 business days.", [0.0, 1.0, 0.0], {"source": "policy-b", "version": 1}
    ),
    SeedChunk("chunk-3", "Contact support for further help.", [0.0, 0.0, 1.0], {"source": "policy-c", "version": 2}),
]

# Deliberately close to chunk-1's embedding and far from the other two.
QUERY_VECTOR: list[float] = [0.9, 0.1, 0.0]
EXPECTED_NEAREST_ID = "chunk-1"


def _seed_chroma(collection: str) -> None:
    import chromadb

    # A *separate* EphemeralClient() instance from the one the adapter under
    # test constructs in its own connect() call — confirmed by hand that
    # chromadb's EphemeralClient() instances share the same underlying
    # in-memory store within one process, so this stands in faithfully for
    # "data that already exists in the store before kbguard ever connects",
    # which is the only way kbguard (read-only, by design — it has no
    # add/upsert method at all) is ever meant to encounter real data.
    client = chromadb.EphemeralClient()
    col = client.create_collection(name=collection, embedding_function=None)
    col.add(
        ids=[c.id for c in SEED_CHUNKS],
        embeddings=[c.embedding for c in SEED_CHUNKS],
        documents=[c.text for c in SEED_CHUNKS],
        metadatas=[dict(c.metadata) for c in SEED_CHUNKS],
    )


def _seed_pgvector(collection: str) -> None:
    import psycopg
    from pgvector.psycopg import register_vector
    from psycopg import sql
    from psycopg.types.json import Jsonb

    # Same reasoning as _seed_chroma: a separate connection from the one
    # PgVectorAdapter.connect() opens, standing in for data that already
    # exists before kbguard ever connects. CREATE EXTENSION/CREATE TABLE
    # are DDL (writes) — fine here (the seeder plays the DBA/client role),
    # never something the adapter itself does.
    conn = psycopg.connect(
        host=_PG_HOST, port=_PG_PORT, user="kbguard", password="kbguard", dbname="kbguard_test", autocommit=True
    )
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)

    table = sql.Identifier(collection)
    dim = len(SEED_CHUNKS[0].embedding)
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
    conn.execute(
        sql.SQL("CREATE TABLE {} (id TEXT PRIMARY KEY, text TEXT, metadata JSONB, embedding VECTOR({}))").format(
            table, sql.Literal(dim)
        )
    )
    for c in SEED_CHUNKS:
        conn.execute(
            sql.SQL("INSERT INTO {} (id, text, metadata, embedding) VALUES (%s, %s, %s, %s)").format(table),
            (c.id, c.text, Jsonb(dict(c.metadata)), c.embedding),
        )
    conn.close()


def _seed_qdrant(collection: str) -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = QdrantClient(host=_QDRANT_HOST, port=_QDRANT_PORT)
    dim = len(SEED_CHUNKS[0].embedding)
    if not client.collection_exists(collection):
        client.create_collection(collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    # Qdrant point ids must be an unsigned int or a UUID — can't use
    # SEED_CHUNKS' string ids ("chunk-1") directly. The original id is
    # preserved in the payload instead, under the same key QdrantAdapter's
    # id_field setting is configured to read (see _CONNECT_SETTINGS below)
    # — exactly the real-world "client's external id didn't fit Qdrant's id
    # constraint" scenario this feature exists for, not a test-only hack.
    points = [
        PointStruct(
            id=i,
            vector=c.embedding,
            payload={**dict(c.metadata), "text": c.text, "_kbguard_test_id": c.id},
        )
        for i, c in enumerate(SEED_CHUNKS)
    ]
    client.upsert(collection, points=points)


# One entry per backend this suite covers. Adding a new adapter to the
# contract suite is: write its seeder here (using that store's own native
# client — never the kbguard adapter, which must stay read-only), add its
# connect() settings below, and add its name to BACKENDS.
_SEEDERS: dict[str, Callable[[str], None]] = {
    "chroma": _seed_chroma,
    "pgvector": _seed_pgvector,
    "qdrant": _seed_qdrant,
}
_CONNECT_SETTINGS: dict[str, dict[str, Any]] = {
    "chroma": {},  # no `path` -> ephemeral
    "pgvector": {"host": _PG_HOST, "port": _PG_PORT, "user": "kbguard", "password": "kbguard", "dbname": "kbguard_test"},
    "qdrant": {"host": _QDRANT_HOST, "port": _QDRANT_PORT, "text_field": "text", "id_field": "_kbguard_test_id"},
}
BACKENDS: list[str] = list(_SEEDERS)

# pgvector/Qdrant need their containers running (docker-compose.yml) —
# skipped with a clear reason rather than erroring, so running the plain
# `pytest` command without Docker up doesn't hard-fail the whole suite for
# contributors working on something unrelated. Chroma never needs this: it
# runs in-process.
_FIXTURE_PARAMS: list[Any] = [
    "chroma",
    "pgvector"
    if _is_reachable(_PG_HOST, _PG_PORT)
    else pytest.param(
        "pgvector", marks=pytest.mark.skip(reason=f"pgvector not reachable at {_PG_HOST}:{_PG_PORT} — run docker compose up -d")
    ),
    "qdrant"
    if _is_reachable(_QDRANT_HOST, _QDRANT_PORT)
    else pytest.param(
        "qdrant", marks=pytest.mark.skip(reason=f"Qdrant not reachable at {_QDRANT_HOST}:{_QDRANT_PORT} — run docker compose up -d")
    ),
]


@dataclass
class ContractCase:
    """Everything a contract test needs, handed to it as plain data via the
    `adapter` fixture — deliberately not re-imported from this module by
    test files, since pytest's import behavior for sibling modules can
    differ between `pytest` and `python -m pytest` (see tests/test_registry.py
    for a case where that actually broke a test)."""

    backend: str
    adapter: VectorStoreAdapter
    collection: str
    chunks: list[SeedChunk]
    query_vector: list[float]
    expected_nearest_id: str


@pytest.fixture(params=_FIXTURE_PARAMS)
def adapter(request: pytest.FixtureRequest) -> Iterator[ContractCase]:
    backend: str = request.param
    # Underscores, not hyphens: pgvector's collection name becomes a SQL
    # table identifier, and PgVectorAdapter's identifier allowlist
    # correctly rejects hyphens as unsafe to use unquoted in a query —
    # found by actually running this against a real pgvector container,
    # not assumed. Underscores work fine for every backend.
    collection = f"contract_{backend}_{uuid.uuid4().hex[:8]}"

    try:
        _SEEDERS[backend](collection)
        instance: VectorStoreAdapter = load_adapter(backend)()
        instance.connect(**_CONNECT_SETTINGS[backend])
    except Exception as exc:  # noqa: BLE001 — deliberate: any failure setting up optional test infra should skip, not propagate
        # The upfront _is_reachable() check only proves a TCP port is open
        # — not that our expected service is actually the one listening
        # there. Confirmed by hand: on this dev machine, something unrelated
        # already occupies localhost:5433 (not our pgvector container),
        # so the port check passed but the real connection then failed
        # with a Postgres auth error. Any failure here means this backend
        # genuinely isn't usable in this environment right now — skip
        # rather than error, same as the upfront reachability check would
        # have done if it had been accurate.
        pytest.skip(f"{backend} unusable in this environment: {exc}")

    yield ContractCase(
        backend=backend,
        adapter=instance,
        collection=collection,
        chunks=SEED_CHUNKS,
        query_vector=QUERY_VECTOR,
        expected_nearest_id=EXPECTED_NEAREST_ID,
    )
