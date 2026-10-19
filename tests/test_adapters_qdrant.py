import uuid
from typing import Any

import pytest

from kbguard.adapters.qdrant import QdrantAdapter


def test_require_client_raises_before_connect() -> None:
    adapter = QdrantAdapter()

    with pytest.raises(RuntimeError, match="connect"):
        adapter.collections()


def test_search_with_filters_raises_not_implemented(qdrant_connect_settings: dict[str, Any]) -> None:
    adapter = QdrantAdapter()
    adapter.connect(**qdrant_connect_settings)

    with pytest.raises(NotImplementedError):
        adapter.search("any_collection", [1.0], k=1, filters={"source": "x"})


def _seed_collection(connect_settings: dict[str, Any], collection: str, text_field: str = "text") -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = QdrantClient(host=connect_settings["host"], port=connect_settings["port"])
    client.create_collection(collection, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    client.upsert(
        collection,
        points=[
            PointStruct(id=1, vector=[1.0, 0.0], payload={text_field: "hello", "k": "v"}),
            PointStruct(id=2, vector=[0.0, 1.0], payload={text_field: "world", "k": "v2"}),
        ],
    )
    return client


def test_default_id_is_native_point_id_stringified(qdrant_connect_settings: dict[str, Any]) -> None:
    collection = f"qa_default_id_{uuid.uuid4().hex[:8]}"
    client = _seed_collection(qdrant_connect_settings, collection)
    try:
        adapter = QdrantAdapter()
        adapter.connect(**qdrant_connect_settings)

        chunks = {c.id: c for c in adapter.iter_chunks(collection)}
        assert set(chunks) == {"1", "2"}  # native point ids, stringified
        assert chunks["1"].text == "hello"
        assert chunks["1"].metadata == {"text": "hello", "k": "v"}  # payload copied whole, text included
    finally:
        client.delete_collection(collection)


def test_id_field_overrides_native_id(qdrant_connect_settings: dict[str, Any]) -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    collection = f"qa_id_field_{uuid.uuid4().hex[:8]}"
    client = QdrantClient(host=qdrant_connect_settings["host"], port=qdrant_connect_settings["port"])
    client.create_collection(collection, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    client.upsert(
        collection,
        points=[PointStruct(id=99, vector=[1.0, 0.0], payload={"text": "hi", "external_id": "real-chunk-1"})],
    )
    try:
        adapter = QdrantAdapter()
        adapter.connect(**qdrant_connect_settings, id_field="external_id")

        chunks = list(adapter.iter_chunks(collection))
        assert chunks[0].id == "real-chunk-1"  # not "99"
    finally:
        client.delete_collection(collection)


def test_custom_text_field(qdrant_connect_settings: dict[str, Any]) -> None:
    collection = f"qa_text_field_{uuid.uuid4().hex[:8]}"
    client = _seed_collection(qdrant_connect_settings, collection, text_field="body")
    try:
        adapter = QdrantAdapter()
        adapter.connect(**qdrant_connect_settings, text_field="body")

        chunks = {c.id: c for c in adapter.iter_chunks(collection)}
        assert chunks["1"].text == "hello"
    finally:
        client.delete_collection(collection)


def test_with_embeddings_false_omits_embeddings(qdrant_connect_settings: dict[str, Any]) -> None:
    collection = f"qa_no_emb_{uuid.uuid4().hex[:8]}"
    client = _seed_collection(qdrant_connect_settings, collection)
    try:
        adapter = QdrantAdapter()
        adapter.connect(**qdrant_connect_settings)

        chunks = list(adapter.iter_chunks(collection, with_embeddings=False))
        assert all(c.embedding is None for c in chunks)
    finally:
        client.delete_collection(collection)


def test_iter_chunks_pages_across_multiple_batches(qdrant_connect_settings: dict[str, Any]) -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    collection = f"qa_paging_{uuid.uuid4().hex[:8]}"
    client = QdrantClient(host=qdrant_connect_settings["host"], port=qdrant_connect_settings["port"])
    client.create_collection(collection, vectors_config=VectorParams(size=1, distance=Distance.COSINE))
    client.upsert(
        collection,
        points=[PointStruct(id=i, vector=[float(i)], payload={"text": f"t{i}"}) for i in range(5)],
    )
    try:
        adapter = QdrantAdapter()
        adapter.connect(**qdrant_connect_settings)

        chunks = list(adapter.iter_chunks(collection, batch_size=2))
        assert sorted(c.id for c in chunks) == ["0", "1", "2", "3", "4"]
    finally:
        client.delete_collection(collection)
