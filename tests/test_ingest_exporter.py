from collections.abc import Iterator
from typing import Any

import pytest

from kbguard.ingest.exporter import export_chunks
from kbguard.ingest.metadata import MetadataMappingError
from kbguard.models import Chunk


class _FakeAdapter:
    name = "fake"

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self.with_embeddings_requested: bool | None = None
        self.batch_size_requested: int | None = None

    def connect(self, **settings: Any) -> None:
        pass

    def collections(self) -> list[str]:
        return []

    def count(self, collection: str) -> int:
        return len(self._chunks)

    def iter_chunks(
        self, collection: str, batch_size: int = 500, with_embeddings: bool = True
    ) -> Iterator[Chunk]:
        self.with_embeddings_requested = with_embeddings
        self.batch_size_requested = batch_size
        yield from self._chunks

    def search(
        self, collection: str, query_vector: list[float], k: int, filters: dict[str, Any] | None = None
    ) -> list[tuple[Chunk, float]]:
        return []


def _raw_chunk(chunk_id: str, doc_id: str, embedding: list[float] | None = None) -> Chunk:
    return Chunk(id=chunk_id, text=f"text for {chunk_id}", embedding=embedding, metadata={"doc_id": doc_id})


def test_export_chunks_applies_metadata_map_and_embeds() -> None:
    raw_chunks = [_raw_chunk("1", "doc-a"), _raw_chunk("2", "doc-b"), _raw_chunk("3", "doc-c")]
    adapter = _FakeAdapter(raw_chunks)

    def embedder(text: str) -> list[float]:
        return [1.0, 2.0]

    results = list(export_chunks(adapter, "demo", {"source": "doc_id"}, embedder))

    assert [c.id for c in results] == ["1", "2", "3"]  # order preserved
    assert [c.source for c in results] == ["doc-a", "doc-b", "doc-c"]
    assert all(c.embedding == [1.0, 2.0] for c in results)


def test_export_chunks_validates_metadata_map_eagerly() -> None:
    adapter = _FakeAdapter([_raw_chunk("1", "doc-a")])

    def embedder(text: str) -> list[float]:
        return [1.0]

    # The error must come from calling export_chunks() itself, before any
    # iteration — proving validation isn't deferred to first next().
    with pytest.raises(MetadataMappingError, match="unknown_field"):
        export_chunks(adapter, "demo", {"unknown_field": "doc_id"}, embedder)


def test_export_chunks_requests_with_embeddings_matching_reuse_stored() -> None:
    adapter_reuse = _FakeAdapter([_raw_chunk("1", "doc-a")])
    list(export_chunks(adapter_reuse, "demo", {}, lambda t: [0.0], reuse_stored=True))
    assert adapter_reuse.with_embeddings_requested is True

    adapter_no_reuse = _FakeAdapter([_raw_chunk("1", "doc-a")])
    list(export_chunks(adapter_no_reuse, "demo", {}, lambda t: [0.0], reuse_stored=False))
    assert adapter_no_reuse.with_embeddings_requested is False


def test_export_chunks_passes_through_batch_size() -> None:
    adapter = _FakeAdapter([_raw_chunk("1", "doc-a")])

    list(export_chunks(adapter, "demo", {}, lambda t: [0.0], batch_size=42))

    assert adapter.batch_size_requested == 42


def test_export_chunks_reuses_stored_embedding_without_calling_embedder() -> None:
    raw_chunks = [
        _raw_chunk("1", "doc-a", embedding=[9.0, 9.0]),  # already has one
        _raw_chunk("2", "doc-b", embedding=None),  # needs computing
    ]
    adapter = _FakeAdapter(raw_chunks)
    calls: list[str] = []

    def embedder(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 1.0]

    results = list(export_chunks(adapter, "demo", {}, embedder, reuse_stored=True))

    assert results[0].embedding == [9.0, 9.0]  # untouched
    assert results[1].embedding == [1.0, 1.0]  # computed
    assert calls == ["text for 2"]  # embedder called once, only for chunk 2
