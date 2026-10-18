import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.registry import load_adapter


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


# One entry per backend this suite covers. Adding a new adapter to the
# contract suite is: write its seeder here (using that store's own native
# client — never the kbguard adapter, which must stay read-only), add its
# connect() settings below, and add its name to BACKENDS.
_SEEDERS: dict[str, Callable[[str], None]] = {
    "chroma": _seed_chroma,
}
_CONNECT_SETTINGS: dict[str, dict[str, Any]] = {
    "chroma": {},  # no `path` -> ephemeral
}
BACKENDS: list[str] = list(_SEEDERS)


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


@pytest.fixture(params=BACKENDS)
def adapter(request: pytest.FixtureRequest) -> Iterator[ContractCase]:
    backend: str = request.param
    collection = f"contract-{backend}-{uuid.uuid4().hex[:8]}"

    _SEEDERS[backend](collection)

    instance: VectorStoreAdapter = load_adapter(backend)()
    instance.connect(**_CONNECT_SETTINGS[backend])

    yield ContractCase(
        backend=backend,
        adapter=instance,
        collection=collection,
        chunks=SEED_CHUNKS,
        query_vector=QUERY_VECTOR,
        expected_nearest_id=EXPECTED_NEAREST_ID,
    )
