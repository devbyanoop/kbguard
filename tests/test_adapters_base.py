from collections.abc import Iterator
from typing import Any

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.models import Chunk


class _FakeAdapter:
    """Minimal adapter used only to prove the Protocol is satisfiable and
    usable — a real adapter (Chroma, next file) covers actual store behavior."""

    name = "fake"

    def connect(self, **settings: Any) -> None:
        pass

    def collections(self) -> list[str]:
        return ["demo"]

    def count(self, collection: str) -> int:
        return 1

    def iter_chunks(
        self, collection: str, batch_size: int = 500, with_embeddings: bool = True
    ) -> Iterator[Chunk]:
        yield Chunk(id="1", text="hello", embedding=[0.1, 0.2])

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        chunk = Chunk(id="1", text="hello", embedding=[0.1, 0.2])
        return [(chunk, 0.99)]


def test_fake_adapter_satisfies_protocol_structurally() -> None:
    # The type annotation here is the real check: mypy verifies _FakeAdapter
    # structurally matches VectorStoreAdapter. This line is also what the
    # broken-adapter sanity check (not committed) confirmed fails loudly
    # when a method is missing.
    adapter: VectorStoreAdapter = _FakeAdapter()

    assert adapter.name == "fake"
    assert adapter.collections() == ["demo"]
    assert adapter.count("demo") == 1

    chunks = list(adapter.iter_chunks("demo"))
    assert len(chunks) == 1
    assert chunks[0].id == "1"

    results = adapter.search("demo", [0.1, 0.2], k=1)
    assert results[0][1] == 0.99
