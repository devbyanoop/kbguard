from collections.abc import Iterator
from typing import Any

from qdrant_client import QdrantClient

from kbguard.config import resolve_env
from kbguard.models import Chunk


class QdrantAdapter:
    name = "qdrant"
    iteration_mode = "full"

    def __init__(self) -> None:
        self._client: QdrantClient | None = None
        self._text_field = "text"
        self._id_field: str | None = None

    def connect(self, **settings: Any) -> None:
        url = settings.get("url")
        host = settings.get("host", "localhost")
        port = settings.get("port", 6333)
        api_key_env = settings.get("api_key_env")
        api_key = resolve_env(api_key_env) if api_key_env else settings.get("api_key")
        # Qdrant has no distinct "text" field — chunk text lives inside the
        # payload, under whatever key the client used. store.text_field in
        # kbguard.yaml controls this; cli.py merges it into **settings.
        self._text_field = settings.get("text_field", "text")
        # Qdrant point ids must be an unsigned int or a UUID (confirmed by
        # hand), so an arbitrary string id a client had before migrating
        # into Qdrant often ends up preserved inside the payload instead.
        # id_field names that payload key; left unset (the default), the
        # native point id is used — the right default for an arbitrary
        # existing collection kbguard knows nothing about.
        self._id_field = settings.get("id_field")

        if url is not None:
            self._client = QdrantClient(url=url, api_key=api_key)
        else:
            self._client = QdrantClient(host=host, port=port, api_key=api_key)

    def _require_client(self) -> QdrantClient:
        if self._client is None:
            raise RuntimeError("QdrantAdapter.connect() must be called before use")
        return self._client

    def collections(self) -> list[str]:
        return [c.name for c in self._require_client().get_collections().collections]

    def count(self, collection: str) -> int:
        return self._require_client().count(collection).count

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        client = self._require_client()
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=with_embeddings,
            )
            if not points:
                return
            for point in points:
                yield self._to_chunk(point.id, point.payload, point.vector if with_embeddings else None)
            if next_offset is None:
                return
            offset = next_offset

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if filters is not None:
            # Same reasoning as pgvector: silently ignoring filters would
            # return unfiltered results to a caller that explicitly asked
            # for filtered ones. No caller passes filters yet.
            raise NotImplementedError("QdrantAdapter.search() doesn't support filters yet")

        client = self._require_client()
        # .search() doesn't exist on this client version (1.19) — confirmed
        # by hand, not assumed from an older remembered API. query_points()
        # is current. Score ordering is already best-first (Qdrant's own
        # guarantee), satisfying the Protocol's ordering requirement with no
        # re-sorting here.
        result = client.query_points(
            collection, query=query_vector, limit=k, with_payload=True, with_vectors=True
        )

        results: list[tuple[Chunk, float]] = []
        for point in result.points:
            chunk = self._to_chunk(point.id, point.payload, point.vector)
            results.append((chunk, float(point.score)))
        return results

    def _to_chunk(self, point_id: Any, payload: dict[str, Any] | None, vector: Any) -> Chunk:
        payload = payload or {}
        if self._id_field is not None and self._id_field in payload:
            chunk_id = str(payload[self._id_field])
        else:
            chunk_id = str(point_id)
        text = payload.get(self._text_field, "")
        # Named/multi-vector points return a dict here, not a list — not
        # handled yet (no current caller has a multi-vector collection to
        # test against); silently treated as "no embedding" rather than
        # raising, which is an accepted gap, not a verified-safe case.
        embedding = list(vector) if isinstance(vector, list) else None
        return Chunk(id=chunk_id, text=str(text), embedding=embedding, metadata=dict(payload))
