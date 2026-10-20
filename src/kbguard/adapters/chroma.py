from collections.abc import Iterator, Sequence
from typing import Any

import chromadb
from chromadb.api import ClientAPI

from kbguard.models import Chunk

# kbguard always supplies its own embeddings (ingest/embeddings.py — reuse
# stored or recompute with the configured model) and never asks Chroma to
# embed text itself. Passing embedding_function=None everywhere stops Chroma
# from silently downloading its default embedding model on first use, which
# would otherwise be a surprise network call this project's "runs entirely
# in your environment" principle explicitly rules out.
_NO_EMBEDDING_FUNCTION = None


class ChromaAdapter:
    name = "chroma"
    iteration_mode = "full"

    def __init__(self) -> None:
        self._client: ClientAPI | None = None

    def connect(self, **settings: Any) -> None:
        path = settings.get("path")
        # No `path` -> in-process, in-memory client: this is what makes
        # Chroma the fastest adapter to develop and test against (no server,
        # no Docker). Given a `path`, data persists to that local directory
        # between runs instead.
        if path is not None:
            self._client = chromadb.PersistentClient(path=str(path))
        else:
            self._client = chromadb.EphemeralClient()

    def _require_client(self) -> ClientAPI:
        if self._client is None:
            raise RuntimeError("ChromaAdapter.connect() must be called before use")
        return self._client

    def collections(self) -> list[str]:
        return [c.name for c in self._require_client().list_collections()]

    def count(self, collection: str) -> int:
        col = self._require_client().get_collection(collection, embedding_function=_NO_EMBEDDING_FUNCTION)
        return col.count()

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        col = self._require_client().get_collection(collection, embedding_function=_NO_EMBEDDING_FUNCTION)
        include = ["documents", "metadatas", *(["embeddings"] if with_embeddings else [])]

        offset = 0
        while True:
            batch = col.get(limit=batch_size, offset=offset, include=include)  # type: ignore[arg-type]
            ids = batch["ids"]
            if not ids:
                return

            documents = batch["documents"]
            metadatas = batch["metadatas"]
            embeddings = batch["embeddings"]

            for i, chunk_id in enumerate(ids):
                text = documents[i] if documents is not None else None
                metadata = metadatas[i] if metadatas is not None else None
                embedding = [float(x) for x in embeddings[i]] if embeddings is not None else None
                yield Chunk(
                    id=chunk_id,
                    text=text or "",
                    embedding=embedding,
                    metadata=dict(metadata or {}),
                )

            offset += len(ids)

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        col = self._require_client().get_collection(collection, embedding_function=_NO_EMBEDDING_FUNCTION)
        query_embeddings: list[Sequence[float] | Sequence[int]] = [query_vector]
        result = col.query(
            query_embeddings=query_embeddings,
            n_results=k,
            where=filters,
            include=["documents", "metadatas", "embeddings", "distances"],
        )

        # query() nests one list per query vector; we only ever send one.
        ids = result["ids"][0]
        documents = result["documents"][0] if result["documents"] is not None else None
        metadatas = result["metadatas"][0] if result["metadatas"] is not None else None
        embeddings = result["embeddings"][0] if result["embeddings"] is not None else None
        distances = result["distances"][0] if result["distances"] is not None else None

        pairs: list[tuple[Chunk, float]] = []
        for i, chunk_id in enumerate(ids):
            text = documents[i] if documents is not None else None
            metadata = metadatas[i] if metadatas is not None else None
            embedding = [float(x) for x in embeddings[i]] if embeddings is not None else None
            chunk = Chunk(id=chunk_id, text=text or "", embedding=embedding, metadata=dict(metadata or {}))
            # Chroma's query() already returns nearest-first, satisfying the
            # Protocol's best-match-first guarantee (adapters/base.py)
            # without any re-sorting needed here.
            score = float(distances[i]) if distances is not None else 0.0
            pairs.append((chunk, score))
        return pairs
