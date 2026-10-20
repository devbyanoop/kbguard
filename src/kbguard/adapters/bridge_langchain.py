import hashlib
import random
from collections.abc import Iterator
from typing import Any

from kbguard.models import Chunk

# Deterministic seed: sampling coverage should be reproducible between two
# scans of an unchanged collection (so a `diff` isn't just sampling noise),
# not a source of real randomness — this is sampling, not security.
_RANDOM_SEED = 0


def _require_setting(settings: dict[str, Any], key: str) -> Any:
    if key not in settings:
        raise ValueError(f"store.settings.{key} is required for the bridge_langchain adapter")
    return settings[key]


def _stable_id(page_content: str, metadata: dict[str, Any]) -> str:
    # Used only when the wrapped store's own Document.id is None (common —
    # many LangChain VectorStore implementations never set it). Content-
    # based, not random, so the same chunk gets the same id across two
    # separate scans; two genuinely distinct chunks that happen to share
    # identical text and metadata would collide, which is an accepted,
    # documented gap, not a silently-assumed-safe one.
    payload = page_content + repr(sorted(metadata.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class LangChainBridgeAdapter:
    """Wraps a LangChain VectorStore instance the client already has,
    instead of connecting to a store natively. langchain_core.vectorstores
    .VectorStore (checked against the installed library, not assumed)
    exposes no "iterate everything" or "count" method at all — only
    similarity search — so this adapter is deliberately less complete than
    the native ones: iter_chunks() approximates coverage via search-based
    sampling, reported honestly as iteration_mode = "sampled" (see
    adapters/base.py), and count() refuses to report a number it has no
    way to verify, rather than guessing.

    A further real gap, worth naming explicitly: none of VectorStore's
    search methods return a hit's own embedding vector, so every Chunk
    this adapter produces has embedding=None regardless of the
    with_embeddings argument — unlike every native adapter, which returns
    real stored vectors. A caller relying on `embeddings.reuse_stored`
    will recompute every chunk's embedding through the configured model
    instead, which is a real cost difference worth knowing about, not a
    bug in how `with_embeddings` is honored here.
    """

    name = "bridge_langchain"
    iteration_mode = "sampled"

    def __init__(self) -> None:
        self._vectorstore: Any = None
        self._collection_name = "default"
        self._embedding_dim: int | None = None
        self._sample_queries: list[str] = []
        self._probe_count = 20

    def connect(self, **settings: Any) -> None:
        self._vectorstore = _require_setting(settings, "vectorstore")
        # Needed to generate the random probe vectors iter_chunks() uses to
        # sample beyond whatever sample_queries covers — there's no API on
        # a generic VectorStore to ask its own embedding dimension.
        self._embedding_dim = _require_setting(settings, "embedding_dim")
        # Real queries a human knows are representative of this
        # collection's content sample far better than random vectors do —
        # optional, but strongly recommended; see docs/guide/adapters/
        # bridge-langchain.md.
        self._sample_queries = settings.get("sample_queries", [])
        self._probe_count = settings.get("probe_count", 20)
        self._collection_name = settings.get("collection", "default")

    def _require_vectorstore(self) -> Any:
        if self._vectorstore is None:
            raise RuntimeError("LangChainBridgeAdapter.connect() must be called before use")
        return self._vectorstore

    def collections(self) -> list[str]:
        # One already-constructed VectorStore instance is already scoped
        # to whatever single collection/index it was built against — there
        # is no "list every collection this client has" operation to call.
        return [self._collection_name]

    def count(self, collection: str) -> int:
        raise NotImplementedError(
            "LangChainBridgeAdapter can't report an exact count -- the wrapped VectorStore has no "
            "universal count/enumerate method. iter_chunks() reports iteration_mode='sampled' instead "
            "of a count it has no way to verify; see docs/guide/adapters/bridge-langchain.md"
        )

    def iter_chunks(
        self,
        collection: str,
        batch_size: int = 500,
        with_embeddings: bool = True,
    ) -> Iterator[Chunk]:
        vectorstore = self._require_vectorstore()
        seen_ids: set[str] = set()

        for query in self._sample_queries:
            for doc, _score in vectorstore.similarity_search_with_score(query, k=batch_size):
                chunk = self._to_chunk(doc)
                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)
                yield chunk

        # Beyond the (optional) human-provided sample_queries, probe with
        # random unit-ish vectors in the embedding space to pick up content
        # those specific queries wouldn't surface — still not a guarantee
        # of full coverage, just a broader, documented sample.
        assert self._embedding_dim is not None  # guaranteed by connect()
        rng = random.Random(_RANDOM_SEED)
        for _ in range(self._probe_count):
            probe_vector = [rng.uniform(-1.0, 1.0) for _ in range(self._embedding_dim)]
            for doc in vectorstore.similarity_search_by_vector(probe_vector, k=batch_size):
                chunk = self._to_chunk(doc)
                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)
                yield chunk

    def search(
        self,
        collection: str,
        query_vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if filters is not None:
            raise NotImplementedError("LangChainBridgeAdapter.search() doesn't support filters yet")

        vectorstore = self._require_vectorstore()
        # similarity_search_by_vector (checked against the installed
        # library) returns plain Documents, best-match-first, but no
        # scores at all -- unlike every native adapter's search(). A
        # descending rank-based placeholder satisfies the Protocol's
        # best-match-first ordering guarantee; it is not a real similarity
        # value and must never be compared against another adapter's
        # score, which adapters/base.py's own docstring already rules out
        # generically.
        docs = vectorstore.similarity_search_by_vector(query_vector, k=k)
        return [(self._to_chunk(doc), 1.0 - i * 0.001) for i, doc in enumerate(docs)]

    def _to_chunk(self, doc: Any) -> Chunk:
        metadata = dict(doc.metadata or {})
        chunk_id = doc.id if getattr(doc, "id", None) is not None else _stable_id(doc.page_content, metadata)
        return Chunk(id=chunk_id, text=doc.page_content, embedding=None, metadata=metadata)
