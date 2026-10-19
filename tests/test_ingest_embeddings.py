import sys
import types

import pytest

from kbguard.config import EmbeddingsConfig
from kbguard.ingest.embeddings import EmbeddingError, embed_chunk, get_embedder
from kbguard.models import Chunk


def test_embed_chunk_reuses_stored_embedding_without_calling_embedder():
    chunk = Chunk(id="a", text="hello", embedding=[0.1, 0.2])
    calls: list[str] = []

    def embedder(text: str) -> list[float]:
        calls.append(text)
        return [9.9]

    result = embed_chunk(chunk, embedder, reuse_stored=True)

    assert result is chunk
    assert calls == []


def test_embed_chunk_recomputes_when_no_stored_embedding():
    chunk = Chunk(id="a", text="hello", embedding=None)

    def embedder(text: str) -> list[float]:
        return [1.0, 2.0]

    result = embed_chunk(chunk, embedder, reuse_stored=True)

    assert result is not chunk
    assert result.embedding == [1.0, 2.0]
    assert result.text == "hello"  # everything else preserved


def test_embed_chunk_recomputes_even_with_stored_embedding_when_reuse_stored_false():
    chunk = Chunk(id="a", text="hello", embedding=[0.1, 0.2])
    calls: list[str] = []

    def embedder(text: str) -> list[float]:
        calls.append(text)
        return [9.9]

    result = embed_chunk(chunk, embedder, reuse_stored=False)

    assert calls == ["hello"]
    assert result.embedding == [9.9]


def test_sentence_transformers_embedder_loads_model_lazily_and_once(monkeypatch: pytest.MonkeyPatch) -> None:
    init_calls: list[str] = []
    encode_calls: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            init_calls.append(model_name)

        def encode(self, text: str) -> list[float]:
            encode_calls.append(text)
            return [1.0, 2.0, 3.0]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    embedder = get_embedder(EmbeddingsConfig(provider="sentence-transformers", model="fake-model"))

    assert init_calls == []  # get_embedder itself must not load the model

    vector1 = embedder("first")
    vector2 = embedder("second")

    assert init_calls == ["fake-model"]  # loaded exactly once, not per call
    assert encode_calls == ["first", "second"]
    assert vector1 == [1.0, 2.0, 3.0]
    assert vector2 == [1.0, 2.0, 3.0]


def test_sentence_transformers_embedder_missing_library_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules forces `import sentence_transformers` to raise
    # ImportError, regardless of whether it's actually installed in this
    # venv — the test must not depend on that ambient state.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    embedder = get_embedder(EmbeddingsConfig(provider="sentence-transformers", model="fake-model"))

    with pytest.raises(EmbeddingError, match="sentence-transformers"):
        embedder("hello")


def test_litellm_embedder_calls_litellm_and_extracts_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_embedding(*, model: str, input: list[str]) -> dict:
        calls.append((model, input))
        return {"data": [{"embedding": [4.0, 5.0]}]}

    fake_module = types.ModuleType("litellm")
    fake_module.embedding = fake_embedding
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    embedder = get_embedder(EmbeddingsConfig(provider="litellm", model="ollama/nomic-embed-text"))
    vector = embedder("hello")

    assert vector == [4.0, 5.0]
    assert calls == [("ollama/nomic-embed-text", ["hello"])]


def test_litellm_embedder_missing_library_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "litellm", None)

    embedder = get_embedder(EmbeddingsConfig(provider="litellm", model="ollama/nomic-embed-text"))

    with pytest.raises(EmbeddingError, match="litellm"):
        embedder("hello")
