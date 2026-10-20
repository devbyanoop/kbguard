"""Real integration tests against a live Pinecone index — the live-service
counterpart to tests/test_adapters_pinecone.py's fake-client unit tests.

Needs PINECONE_API_KEY and PINECONE_TEST_INDEX (dimension 4, metric cosine)
set via .env or the real environment — see .env.example. Skips cleanly
(not an error) when they aren't set, same as pgvector/Qdrant's Docker-
dependent tests do when their container isn't reachable.
"""

import os
from collections.abc import Iterator
from typing import Any

import pytest

from kbguard.adapters.pinecone import PineconeAdapter

_NAMESPACE = "kbguard-test"
_SEEDED_IDS = ["kbguard-test-a", "kbguard-test-b", "kbguard-test-c"]


@pytest.fixture
def seeded_index(pinecone_index: Any) -> Iterator[Any]:
    pinecone_index.upsert(
        vectors=[
            {"id": "kbguard-test-a", "values": [1.0, 0.0, 0.0, 0.0], "metadata": {"text": "chunk a", "source": "doc1"}},
            {"id": "kbguard-test-b", "values": [0.0, 1.0, 0.0, 0.0], "metadata": {"text": "chunk b", "source": "doc1"}},
            {"id": "kbguard-test-c", "values": [0.0, 0.0, 1.0, 0.0], "metadata": {"text": "chunk c", "source": "doc2"}},
        ],
        namespace=_NAMESPACE,
    )
    try:
        yield pinecone_index
    finally:
        pinecone_index.delete(ids=_SEEDED_IDS, namespace=_NAMESPACE)


@pytest.fixture
def adapter_and_index(seeded_index: Any) -> tuple[PineconeAdapter, str]:
    adapter = PineconeAdapter()
    adapter.connect(api_key_env="PINECONE_API_KEY", namespace=_NAMESPACE)
    return adapter, os.environ["PINECONE_TEST_INDEX"]


def test_collections_lists_the_real_test_index(adapter_and_index: tuple[PineconeAdapter, str]) -> None:
    adapter, index_name = adapter_and_index

    assert index_name in adapter.collections()


def test_iter_chunks_finds_real_seeded_vectors(adapter_and_index: tuple[PineconeAdapter, str]) -> None:
    adapter, index_name = adapter_and_index

    chunks = {c.id: c for c in adapter.iter_chunks(index_name, batch_size=10)}

    for seeded_id in _SEEDED_IDS:
        assert seeded_id in chunks
    assert chunks["kbguard-test-a"].text == "chunk a"
    assert chunks["kbguard-test-a"].metadata["source"] == "doc1"
    assert chunks["kbguard-test-a"].embedding == [1.0, 0.0, 0.0, 0.0]


def test_iter_chunks_without_embeddings_still_finds_text(adapter_and_index: tuple[PineconeAdapter, str]) -> None:
    adapter, index_name = adapter_and_index

    chunks = {c.id: c for c in adapter.iter_chunks(index_name, batch_size=10, with_embeddings=False)}

    assert chunks["kbguard-test-a"].text == "chunk a"
    assert chunks["kbguard-test-a"].embedding is None


def test_search_returns_the_nearest_real_seeded_vector(adapter_and_index: tuple[PineconeAdapter, str]) -> None:
    adapter, index_name = adapter_and_index

    results = adapter.search(index_name, [1.0, 0.0, 0.0, 0.0], k=1)

    assert len(results) == 1
    assert results[0][0].id == "kbguard-test-a"
    assert results[0][0].text == "chunk a"


def test_count_reflects_real_namespace(adapter_and_index: tuple[PineconeAdapter, str]) -> None:
    adapter, index_name = adapter_and_index

    count = adapter.count(index_name)

    assert count >= len(_SEEDED_IDS)  # >= in case the namespace already has other leftover data
