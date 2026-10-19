import dataclasses
from collections.abc import Callable
from typing import Any

from kbguard.config import EmbeddingsConfig
from kbguard.models import Chunk


class EmbeddingError(Exception):
    """Raised when the configured embedding provider's library isn't
    installed — names the exact extra to install, same pattern as
    ConfigError/RegistryError/MetadataMappingError elsewhere in the
    codebase."""


def get_embedder(config: EmbeddingsConfig) -> Callable[[str], list[float]]:
    """Returns a text -> vector function for the configured provider/model.

    Deliberately returns a *function*, not a loaded model: the actual model
    (for sentence-transformers) is loaded lazily, on first real use inside
    that returned function — not here. If every chunk in a scan already has
    a stored embedding (embed_chunk below never calls this function at
    all), the model is never loaded, and a library that isn't installed is
    never even imported. "Don't pay for what you don't use" applies to
    model-loading time (can be seconds) as much as to the import itself.
    """
    if config.provider == "sentence-transformers":
        return _sentence_transformers_embedder(config.model)
    return _litellm_embedder(config.model)


def _sentence_transformers_embedder(model_name: str) -> Callable[[str], list[float]]:
    model: Any = None

    def embed(text: str) -> list[float]:
        nonlocal model
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "embeddings.provider=sentence-transformers needs the 'sentence-transformers' "
                    'extra: pip install "kbguard[sentence-transformers]"'
                ) from exc
            model = SentenceTransformer(model_name)

        vector = model.encode(text)
        return [float(x) for x in vector]

    return embed


def _litellm_embedder(model_name: str) -> Callable[[str], list[float]]:
    def embed(text: str) -> list[float]:
        try:
            import litellm
        except ImportError as exc:
            raise EmbeddingError(
                'embeddings.provider=litellm needs the \'litellm\' extra: pip install "kbguard[litellm]"'
            ) from exc

        response = litellm.embedding(model=model_name, input=[text])
        return [float(x) for x in response["data"][0]["embedding"]]

    return embed


def embed_chunk(chunk: Chunk, embedder: Callable[[str], list[float]], reuse_stored: bool) -> Chunk:
    """Applies the reuse-or-recompute *policy* — separate from get_embedder,
    which only knows how to compute a vector for text, not when to bother.
    Returns the same Chunk instance (not a copy) when reusing, same
    immutable-pipeline convention as ingest/metadata.py.
    """
    if reuse_stored and chunk.embedding is not None:
        return chunk
    return dataclasses.replace(chunk, embedding=embedder(chunk.text))
