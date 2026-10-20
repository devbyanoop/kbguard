from collections.abc import Iterator
from typing import Any

from kbguard.config import resolve_env
from kbguard.models import Chunk

# Pinecone's own list() page size cap (confirmed against the installed
# client's real signature/docstring, not assumed) — a caller-requested
# batch_size larger than this is silently clamped, not an error.
_MAX_LIST_PAGE_SIZE = 100


class PineconeAdapter:
    name = "pinecone"
    iteration_mode = "full"

    def __init__(self) -> None:
        self._client: Any = None
        self._namespace = ""
        self._text_field = "text"
        self._indexes: dict[str, Any] = {}  # index name -> opened Index object, cached

    def connect(self, **settings: Any) -> None:
        try:
            from pinecone import Pinecone
        except ImportError as exc:
            raise ImportError(
                'the pinecone adapter needs the \'pinecone\' extra: pip install "kbguard[pinecone]" '
                "-- note this installs the `pinecone` package, not the deprecated `pinecone-client` "
                "(the old package now raises ImportError on its own, telling you to switch)"
            ) from exc

        api_key_env = settings.get("api_key_env")
        api_key = resolve_env(api_key_env) if api_key_env else settings.get("api_key")
        # A Pinecone *index* is this adapter's "collection" (the thing
        # collections()/count()/iter_chunks()/search() take by name) --
        # same role as a Chroma collection, a pgvector table, a Qdrant
        # collection. A *namespace* is a further subdivision within one
        # index, with no equivalent in the other three stores, so it's an
        # adapter-specific setting rather than a Protocol parameter.
        self._namespace = settings.get("namespace", "")
        # Pinecone has no separate "text" storage, same situation as
        # Qdrant -- chunk text lives inside the flat metadata dict under
        # whatever key the client used.
        self._text_field = settings.get("text_field", "text")
        self._client = Pinecone(api_key=api_key)

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("PineconeAdapter.connect() must be called before use")
        return self._client

    def _index_for(self, collection: str) -> Any:
        if collection not in self._indexes:
            self._indexes[collection] = self._require_client().Index(collection)
        return self._indexes[collection]

    def collections(self) -> list[str]:
        # .names() is a *method* on the real installed client (confirmed
        # by hand after a live test caught this: dir() lists "names" the
        # same way whether it's a plain attribute or a callable, which is
        # exactly how this got written wrong the first time, against a
        # fake client that never would have caught it either).
        return self._require_client().list_indexes().names()  # type: ignore[no-any-return]

    def count(self, collection: str) -> int:
        stats = self._index_for(collection).describe_index_stats()
        if self._namespace:
            summary = stats.namespaces.get(self._namespace)
            return summary.vector_count if summary is not None else 0
        return stats.total_vector_count  # type: ignore[no-any-return]

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        index = self._index_for(collection)
        page_size = min(batch_size, _MAX_LIST_PAGE_SIZE)
        # index.list() yields one page of bare ids at a time (no values, no
        # metadata -- confirmed from the installed client's own docstring);
        # fetch() is the separate call that returns the actual vectors,
        # exactly the "list ids, then fetch in batches" shape the
        # architecture spec calls for.
        for page in index.list(limit=page_size, namespace=self._namespace):
            ids = [item.id for item in page.vectors]
            if not ids:
                continue
            fetched = index.fetch(ids=ids, namespace=self._namespace)
            for vector_id, vector in fetched.vectors.items():
                yield self._to_chunk(vector_id, vector.values, vector.metadata, with_embeddings)

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        index = self._index_for(collection)
        response = index.query(
            vector=query_vector,
            top_k=k,
            namespace=self._namespace,
            filter=filters,
            include_values=True,
            include_metadata=True,
        )
        # Best-match-first is Pinecone's own guarantee for query(), same as
        # Qdrant's query_points() -- no re-sorting needed here either.
        return [
            (self._to_chunk(match.id, match.values, match.metadata, True), float(match.score))
            for match in response.matches
        ]

    def _to_chunk(
        self, vector_id: str, values: list[float] | None, metadata: dict[str, Any] | None, with_embeddings: bool
    ) -> Chunk:
        metadata = dict(metadata or {})
        text = metadata.get(self._text_field, "")
        embedding = list(values) if with_embeddings and values is not None else None
        return Chunk(id=str(vector_id), text=str(text), embedding=embedding, metadata=metadata)
