from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from kbguard.adapters.base import AdapterConnectionError
from kbguard.adapters.pinecone import PineconeAdapter


class _Obj:
    """Minimal stand-in for pinecone's msgspec response objects -- supports
    attribute access only, same shape real callers rely on (point.id,
    page.vectors, response.matches, ...)."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _FakeIndex:
    def __init__(self, name: str, pages: list[list[str]], vectors: dict[str, _Obj]) -> None:
        self.name = name
        self._pages = pages
        self._vectors = vectors
        self.fetch_calls: list[tuple[tuple[str, ...], str]] = []
        self.query_calls: list[dict[str, Any]] = []

    def describe_index_stats(self, *, timeout: float | None = None) -> _Obj:
        return _Obj(total_vector_count=len(self._vectors), namespaces={})

    def list(self, *, limit: int, namespace: str, timeout: float | None = None) -> list[_Obj]:
        return [_Obj(vectors=[_Obj(id=vid) for vid in page]) for page in self._pages if page]

    def fetch(self, *, ids: list[str], namespace: str, timeout: float | None = None) -> _Obj:
        self.fetch_calls.append((tuple(ids), namespace))
        return _Obj(vectors={vid: self._vectors[vid] for vid in ids})

    def query(self, **kwargs: Any) -> _Obj:
        self.query_calls.append(kwargs)
        top_k = kwargs["top_k"]
        matches = [
            _Obj(id=vid, score=1.0 - i * 0.1, values=v.values, metadata=v.metadata)
            for i, (vid, v) in enumerate(list(self._vectors.items())[:top_k])
        ]
        return _Obj(matches=matches)


class _FakePineconeException(Exception):
    """Stands in for the real `pinecone.PineconeException` -- adapters/
    pinecone.py imports the real one by name (`from pinecone import
    Pinecone, PineconeException`), so a fake pinecone module needs this
    attribute too, or that import itself fails with a plain
    ImportError/AttributeError, not the exception path being tested."""


class _FakePinecone:
    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.indexes: dict[str, _FakeIndex] = {}
        self.list_indexes_error: Exception | None = None

    def Index(self, name: str) -> _FakeIndex:  # matches real pinecone.Pinecone.Index's casing
        return self.indexes[name]

    def list_indexes(self) -> _Obj:
        if self.list_indexes_error is not None:
            raise self.list_indexes_error
        # names() is a *method* on the real IndexList, not a plain
        # attribute — confirmed only after a live test against a real
        # Pinecone index caught adapters/pinecone.py calling it as one.
        # This fake originally had the same wrong shape and would never
        # have caught that bug either; fixed to match the real callable.
        index_names = list(self.indexes.keys())
        return _Obj(names=lambda: index_names)


def _install_fake_pinecone(monkeypatch: pytest.MonkeyPatch, fake_client: _FakePinecone) -> None:
    fake_module = types.ModuleType("pinecone")
    fake_module.Pinecone = lambda **kwargs: fake_client  # type: ignore[attr-defined]
    fake_module.PineconeException = _FakePineconeException  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", fake_module)


def test_collections_lists_index_names(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakePinecone()
    client.indexes["policies"] = _FakeIndex("policies", [], {})
    client.indexes["faqs"] = _FakeIndex("faqs", [], {})
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    assert sorted(adapter.collections()) == ["faqs", "policies"]


def test_count_without_namespace_uses_total_vector_count(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {"a": _Obj(values=[1.0], metadata={}), "b": _Obj(values=[2.0], metadata={})}
    client = _FakePinecone()
    client.indexes["policies"] = _FakeIndex("policies", [], vectors)
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    assert adapter.count("policies") == 2


def test_iter_chunks_lists_then_fetches_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {
        "a": _Obj(values=[1.0, 0.0], metadata={"text": "chunk a", "source": "doc1"}),
        "b": _Obj(values=[0.0, 1.0], metadata={"text": "chunk b", "source": "doc1"}),
        "c": _Obj(values=[0.5, 0.5], metadata={"text": "chunk c", "source": "doc2"}),
    }
    index = _FakeIndex("policies", pages=[["a", "b"], ["c"]], vectors=vectors)
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    chunks = list(adapter.iter_chunks("policies", batch_size=2))

    assert {c.id for c in chunks} == {"a", "b", "c"}
    assert {c.text for c in chunks} == {"chunk a", "chunk b", "chunk c"}
    by_id = {c.id: c for c in chunks}
    assert by_id["a"].embedding == [1.0, 0.0]
    assert by_id["a"].metadata == {"text": "chunk a", "source": "doc1"}
    # Two list pages -> two separate fetch() calls, each scoped to its page's ids.
    assert len(index.fetch_calls) == 2
    assert index.fetch_calls[0][0] == ("a", "b")
    assert index.fetch_calls[1][0] == ("c",)


def test_iter_chunks_without_embeddings_still_fetches_but_drops_values(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {"a": _Obj(values=[1.0], metadata={"text": "chunk a"})}
    index = _FakeIndex("policies", pages=[["a"]], vectors=vectors)
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    chunks = list(adapter.iter_chunks("policies", with_embeddings=False))

    assert chunks[0].embedding is None


def test_empty_index_yields_no_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _FakeIndex("policies", pages=[], vectors={})
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    assert list(adapter.iter_chunks("policies")) == []
    assert index.fetch_calls == []  # never called with an empty id list


def test_search_returns_best_match_first_with_metadata_and_values(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {
        "a": _Obj(values=[1.0, 0.0], metadata={"text": "chunk a"}),
        "b": _Obj(values=[0.0, 1.0], metadata={"text": "chunk b"}),
    }
    index = _FakeIndex("policies", pages=[], vectors=vectors)
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    results = adapter.search("policies", [1.0, 0.0], k=2)

    assert [chunk.id for chunk, _score in results] == ["a", "b"]  # order preserved, best-match-first
    assert results[0][1] > results[1][1]  # descending score
    assert results[0][0].text == "chunk a"
    assert results[0][0].embedding == [1.0, 0.0]


def test_search_passes_filters_through_to_query(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _FakeIndex("policies", pages=[], vectors={})
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    adapter.search("policies", [1.0], k=5, filters={"doc_type": "policy"})

    assert index.query_calls[0]["filter"] == {"doc_type": "policy"}


def test_text_field_setting_controls_where_chunk_text_is_read_from(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {"a": _Obj(values=[1.0], metadata={"body": "the real text", "text": "wrong field"})}
    index = _FakeIndex("policies", pages=[["a"]], vectors=vectors)
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key", text_field="body")

    chunks = list(adapter.iter_chunks("policies"))

    assert chunks[0].text == "the real text"


def test_namespace_setting_scopes_count_and_fetch_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _FakeIndex("policies", pages=[], vectors={})
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key", namespace="articles-en")

    adapter.search("policies", [1.0], k=1)

    assert index.query_calls[0]["namespace"] == "articles-en"


def test_connect_wraps_a_bad_key_into_a_clean_adapter_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinecone(api_key=...) never raises for a bad key by itself -- the
    real failure only surfaces on the first real call, confirmed by hand
    against the real API (a real 401 UnauthorizedError). connect() proves
    this eagerly via list_indexes() specifically so a bad/invalid key
    fails clearly right here instead of as a raw library traceback the
    first time any other method is used."""
    client = _FakePinecone()
    client.list_indexes_error = _FakePineconeException("[401 UNAUTHENTICATED] Invalid API key")
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()

    with pytest.raises(AdapterConnectionError, match="could not connect to Pinecone.*Invalid API key"):
        adapter.connect(api_key="fake-key")


def test_missing_pinecone_library_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pinecone", None)

    adapter = PineconeAdapter()

    with pytest.raises(ImportError, match="pinecone"):
        adapter.connect(api_key="fake-key")


def test_connect_resolves_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PINECONE_KEY", "secret-value")
    captured: dict[str, Any] = {}

    def fake_pinecone_ctor(**kwargs: Any) -> _FakePinecone:
        captured.update(kwargs)
        return _FakePinecone(**kwargs)

    fake_module = types.ModuleType("pinecone")
    fake_module.Pinecone = fake_pinecone_ctor  # type: ignore[attr-defined]
    fake_module.PineconeException = _FakePineconeException  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", fake_module)

    adapter = PineconeAdapter()
    adapter.connect(api_key_env="PINECONE_KEY")

    assert captured["api_key"] == "secret-value"


def test_query_is_called_with_a_timeout_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real test run hung indefinitely against a throttled live index
    # specifically because no timeout was ever passed through -- this
    # locks in that every real call now carries one.
    index = _FakeIndex("policies", pages=[], vectors={})
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key")

    adapter.search("policies", [1.0], k=1)

    assert index.query_calls[0]["timeout"] == 30.0


def test_timeout_setting_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _FakeIndex("policies", pages=[], vectors={})
    client = _FakePinecone()
    client.indexes["policies"] = index
    _install_fake_pinecone(monkeypatch, client)

    adapter = PineconeAdapter()
    adapter.connect(api_key="fake-key", timeout=5.0)

    adapter.search("policies", [1.0], k=1)

    assert index.query_calls[0]["timeout"] == 5.0
