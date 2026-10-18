from collections.abc import Iterator
from typing import Any, Protocol

from kbguard.models import Chunk


class VectorStoreAdapter(Protocol):
    """The only contract kbguard knows about a vector store. Everything
    downstream (ingest, checks, evals) works on the `Chunk` records this
    produces — never on a store-specific client — which is what makes any
    vector store pluggable.
    """

    name: str

    def connect(self, **settings: Any) -> None: ...

    def collections(self) -> list[str]: ...

    def count(self, collection: str) -> int: ...

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        """Must page through the *entire* collection without ever holding it
        all in memory at once — implementations page internally (keyset or
        cursor-based, store-dependent) and yield one Chunk at a time.
        """
        ...

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Results are returned **best-match-first**; callers rely on this
        ordering, not on the numeric score. Scores only need to be
        comparable *within a single call* — never across two different
        adapters, two different collections, or against some assumed
        absolute scale (a Chroma distance and a Qdrant similarity are not
        the same kind of number, and callers must not assume either
        direction — lower-is-better or higher-is-better — holds generically).
        """
        ...
