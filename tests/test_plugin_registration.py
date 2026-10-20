from kbguard.adapters.chroma import ChromaAdapter
from kbguard.adapters.pgvector import PgVectorAdapter
from kbguard.adapters.qdrant import QdrantAdapter
from kbguard.checks.duplicates import DuplicatesCheck
from kbguard.checks.stale_versions import StaleVersionsCheck
from kbguard.registry import load_adapter, load_check

# Unlike test_registry.py (which exercises registry.py's own lookup logic
# against a fake, mocked entry point), these tests use the *real* installed
# package metadata. They'd fail if pyproject.toml's entry-points tables
# ever drifted from the actual class path — e.g. a typo, or a class
# getting renamed without updating its registration. One test per built-in
# adapter/check, added as each one is built.


def test_chroma_adapter_is_registered() -> None:
    assert load_adapter("chroma") is ChromaAdapter


def test_pgvector_adapter_is_registered() -> None:
    assert load_adapter("pgvector") is PgVectorAdapter


def test_qdrant_adapter_is_registered() -> None:
    assert load_adapter("qdrant") is QdrantAdapter


def test_duplicates_check_is_registered() -> None:
    assert load_check("duplicates") is DuplicatesCheck


def test_stale_versions_check_is_registered() -> None:
    assert load_check("stale_versions") is StaleVersionsCheck
