import hashlib

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from kbguard.adapters.bridge_langchain import LangChainBridgeAdapter, _stable_id


class _DeterministicEmbeddings(Embeddings):
    """Small, dependency-free, fully deterministic Embeddings -- real
    langchain_core Documents and search behavior, without needing a real
    embedding model or network access."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[:4]]


def _seeded_vectorstore() -> InMemoryVectorStore:
    vs = InMemoryVectorStore(_DeterministicEmbeddings())
    vs.add_texts(
        ["refund policy allows 30 days", "shipping takes 3 to 5 days", "warranty lasts one year"],
        metadatas=[{"source": "refunds"}, {"source": "shipping"}, {"source": "warranty"}],
        ids=["id-refund", "id-shipping", "id-warranty"],
    )
    return vs


def _connect(**extra_settings: object) -> LangChainBridgeAdapter:
    adapter = LangChainBridgeAdapter()
    settings: dict[str, object] = {"vectorstore": _seeded_vectorstore(), "embedding_dim": 4}
    settings.update(extra_settings)
    adapter.connect(**settings)
    return adapter


def test_iteration_mode_is_sampled_not_full() -> None:
    assert LangChainBridgeAdapter.iteration_mode == "sampled"


def test_count_refuses_to_guess() -> None:
    adapter = _connect()

    with pytest.raises(NotImplementedError, match="count"):
        adapter.count("default")


def test_missing_vectorstore_setting_raises() -> None:
    adapter = LangChainBridgeAdapter()

    with pytest.raises(ValueError, match="vectorstore"):
        adapter.connect(embedding_dim=4)


def test_missing_embedding_dim_setting_raises() -> None:
    adapter = LangChainBridgeAdapter()

    with pytest.raises(ValueError, match="embedding_dim"):
        adapter.connect(vectorstore=_seeded_vectorstore())


def test_iter_chunks_via_sample_queries_finds_real_seeded_content() -> None:
    adapter = _connect(sample_queries=["refund policy"], probe_count=0)

    chunks = list(adapter.iter_chunks("default", batch_size=3))

    assert any(c.id == "id-refund" for c in chunks)
    assert any("refund" in c.text for c in chunks)


def test_iter_chunks_every_yielded_chunk_has_no_embedding() -> None:
    # The one real, named limitation: VectorStore's search methods never
    # return a hit's own embedding, regardless of with_embeddings.
    adapter = _connect(sample_queries=["refund policy", "shipping"], probe_count=2)

    chunks = list(adapter.iter_chunks("default", batch_size=3, with_embeddings=True))

    assert chunks  # sanity: the probes actually found something
    assert all(c.embedding is None for c in chunks)


def test_iter_chunks_deduplicates_across_queries_and_probes() -> None:
    # Three real seeded chunks, two overlapping sample queries plus random
    # probes that will very likely also surface them -- every id must
    # still appear in the result exactly once.
    adapter = _connect(sample_queries=["refund policy", "refund"], probe_count=5)

    chunks = list(adapter.iter_chunks("default", batch_size=3))

    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))  # no duplicates despite overlapping probes


def test_iter_chunks_with_zero_probes_and_no_queries_yields_nothing() -> None:
    adapter = _connect(sample_queries=[], probe_count=0)

    assert list(adapter.iter_chunks("default")) == []


def test_search_returns_best_match_first_with_real_scores_from_the_store() -> None:
    adapter = _connect()
    query_vector = _DeterministicEmbeddings().embed_query("refund policy allows 30 days")

    results = adapter.search("default", query_vector, k=3)

    assert len(results) == 3
    assert results[0][0].id == "id-refund"  # the exact chunk the query vector came from, ranked first
    scores = [score for _chunk, score in results]
    assert scores == sorted(scores, reverse=True)  # descending placeholder scores, not a real similarity


def test_search_with_filters_raises_not_implemented() -> None:
    adapter = _connect()

    with pytest.raises(NotImplementedError, match="filters"):
        adapter.search("default", [0.0, 0.0, 0.0, 0.0], k=1, filters={"source": "refunds"})


def test_stable_id_is_deterministic_for_identical_content_and_metadata() -> None:
    first = _stable_id("some text", {"source": "doc1"})
    second = _stable_id("some text", {"source": "doc1"})

    assert first == second


def test_stable_id_differs_for_different_content() -> None:
    a = _stable_id("some text", {"source": "doc1"})
    b = _stable_id("different text", {"source": "doc1"})

    assert a != b


def test_to_chunk_falls_back_to_stable_id_when_document_id_is_none() -> None:
    class _FakeDocWithNoId:
        def __init__(self) -> None:
            self.id = None
            self.page_content = "fallback text"
            self.metadata = {"source": "doc1"}

    adapter = _connect()
    chunk = adapter._to_chunk(_FakeDocWithNoId())

    assert chunk.id == _stable_id("fallback text", {"source": "doc1"})
    assert chunk.text == "fallback text"
