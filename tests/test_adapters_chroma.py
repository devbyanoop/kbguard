import uuid
from pathlib import Path

import pytest

from kbguard.adapters.base import AdapterConnectionError
from kbguard.adapters.chroma import ChromaAdapter


def test_connect_wraps_a_real_connection_failure(tmp_path: Path) -> None:
    """Local-only (no remote host to misconfigure), but an unwritable
    path still fails eagerly right here -- confirmed by hand: a file
    sitting where the persistent directory needs to go blocks chromadb
    from creating it, cross-platform (no OS-specific bad path needed)."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    adapter = ChromaAdapter()

    with pytest.raises(AdapterConnectionError, match="could not open the Chroma store"):
        adapter.connect(path=str(blocker / "sub"))


@pytest.fixture
def seeded_adapter() -> tuple[ChromaAdapter, str]:
    # chromadb's EphemeralClient() instances are NOT isolated from each
    # other within one process (confirmed by hand: two separate
    # EphemeralClient() objects both fail to create a collection named
    # "demo" if either one already has — they share a process-wide
    # namespace). A fresh, random collection name per test sidesteps that
    # entirely, and is also the pattern the pgvector/Qdrant contract tests
    # will need anyway, since those run against one shared Docker container
    # for the whole test session rather than getting a fresh store each time.
    collection = f"demo-{uuid.uuid4().hex[:8]}"

    adapter = ChromaAdapter()
    adapter.connect()  # no `path` -> ephemeral, in-memory
    client = adapter._require_client()
    col = client.create_collection(name=collection, embedding_function=None)
    col.add(
        ids=["a", "b", "c"],
        embeddings=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
        documents=["alpha text", "beta text", "gamma text"],
        metadatas=[{"source": "doc1"}, {"source": "doc2"}, {"source": "doc3"}],
    )
    return adapter, collection


def test_require_client_raises_before_connect() -> None:
    adapter = ChromaAdapter()

    with pytest.raises(RuntimeError, match="connect"):
        adapter.collections()


def test_collections_lists_created_collections(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    assert adapter.collections() == [collection]


def test_count_returns_number_of_chunks(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    assert adapter.count(collection) == 3


def test_iter_chunks_returns_all_chunks_with_embeddings(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    chunks = {c.id: c for c in adapter.iter_chunks(collection)}

    assert set(chunks) == {"a", "b", "c"}
    assert chunks["a"].text == "alpha text"
    assert chunks["a"].metadata == {"source": "doc1"}
    assert chunks["a"].embedding == pytest.approx([1.0, 0.0], abs=1e-6)


def test_iter_chunks_respects_with_embeddings_false(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    chunks = list(adapter.iter_chunks(collection, with_embeddings=False))

    assert all(c.embedding is None for c in chunks)


def test_iter_chunks_pages_across_multiple_batches(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    # batch_size=2 against 3 chunks forces the pagination loop to run twice —
    # this is the real test that offset accounting doesn't skip or repeat.
    chunks = list(adapter.iter_chunks(collection, batch_size=2))

    assert sorted(c.id for c in chunks) == ["a", "b", "c"]


def test_search_returns_nearest_first(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    results = adapter.search(collection, query_vector=[1.0, 0.0], k=3)

    ids_in_order = [chunk.id for chunk, _score in results]
    assert ids_in_order == ["a", "b", "c"]  # a is exact match, b is close, c is far


def test_search_respects_k(seeded_adapter: tuple[ChromaAdapter, str]) -> None:
    adapter, collection = seeded_adapter

    results = adapter.search(collection, query_vector=[1.0, 0.0], k=1)

    assert len(results) == 1
    assert results[0][0].id == "a"
