from collections.abc import Callable, Iterator

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.ingest.embeddings import embed_chunk
from kbguard.ingest.metadata import apply_metadata_map, validate_metadata_map
from kbguard.models import Chunk


def export_chunks(
    adapter: VectorStoreAdapter,
    collection: str,
    metadata_map: dict[str, str],
    embedder: Callable[[str], list[float]],
    reuse_stored: bool = True,
    batch_size: int = 500,
) -> Iterator[Chunk]:
    """Drives one full export: adapter.iter_chunks() -> metadata mapping ->
    embedding fill-in, yielding fully-populated Chunks for the snapshot
    writer. Nothing here calls an LLM or does anything expensive beyond the
    embedding step itself — pure iteration and lookups ("cheap first").

    `metadata_map` is validated here (once), *not* inside the generator
    below: this function is intentionally not itself a generator (no
    `yield` in its own body), specifically so validate_metadata_map() runs
    the moment export_chunks() is called, not deferred until whoever gets
    the returned iterator starts actually consuming it. A generator
    function's body doesn't execute at all until first iterated — if
    export_chunks were a generator directly, a bad metadata_map would raise
    nothing until some arbitrary later point, possibly never, if the
    caller never actually loops over the result.
    """
    validate_metadata_map(metadata_map)
    # Asking the adapter for embeddings it'll immediately be discarded
    # would be wasted I/O — with_embeddings tracks reuse_stored exactly.
    chunks = adapter.iter_chunks(collection, batch_size=batch_size, with_embeddings=reuse_stored)
    return _export_chunks(chunks, metadata_map, embedder, reuse_stored)


def _export_chunks(
    chunks: Iterator[Chunk],
    metadata_map: dict[str, str],
    embedder: Callable[[str], list[float]],
    reuse_stored: bool,
) -> Iterator[Chunk]:
    for chunk in chunks:
        chunk = apply_metadata_map(chunk, metadata_map)
        chunk = embed_chunk(chunk, embedder, reuse_stored)
        yield chunk
