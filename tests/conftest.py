import os
import socket
from typing import Any

import pytest

# Same env var names as contract_tests/conftest.py, same localhost default
# (matches docker-compose.yml's port mapping) — duplicated rather than
# imported from there. A cross-conftest import across tests/ and
# contract_tests/ (neither a real package, no __init__.py) hits the same
# invocation-mode fragility already found twice this session (see
# tests/test_registry.py, contract_tests/test_adapter_contract.py); pytest
# fixtures, by contrast, share reliably across conftest.py files with no
# import at all, which is what these are for.
_PG_HOST = os.environ.get("KBGUARD_TEST_PG_HOST", "localhost")
_PG_PORT = int(os.environ.get("KBGUARD_TEST_PG_PORT", "5434"))
_QDRANT_HOST = os.environ.get("KBGUARD_TEST_QDRANT_HOST", "localhost")
_QDRANT_PORT = int(os.environ.get("KBGUARD_TEST_QDRANT_PORT", "6333"))
# No host/port to pre-check reachability against — Pinecone is an HTTPS
# API, not a raw socket. Loaded via the repo-root conftest.py's
# load_dotenv() if present in .env; never hardcoded, never logged.
_PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
_PINECONE_TEST_INDEX = os.environ.get("PINECONE_TEST_INDEX")


def _is_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def pgvector_connect_settings() -> dict[str, Any]:
    if not _is_reachable(_PG_HOST, _PG_PORT):
        pytest.skip(f"pgvector not reachable at {_PG_HOST}:{_PG_PORT} — run docker compose up -d")
    return {"host": _PG_HOST, "port": _PG_PORT, "user": "kbguard", "password": "kbguard", "dbname": "kbguard_test"}


@pytest.fixture
def qdrant_connect_settings() -> dict[str, Any]:
    if not _is_reachable(_QDRANT_HOST, _QDRANT_PORT):
        pytest.skip(f"Qdrant not reachable at {_QDRANT_HOST}:{_QDRANT_PORT} — run docker compose up -d")
    return {"host": _QDRANT_HOST, "port": _QDRANT_PORT}


@pytest.fixture
def pinecone_index() -> Any:
    """A real, connected Pinecone Index object for the configured test
    index — not a settings dict like the other two fixtures, since a live
    test here also needs to upsert/delete its own seed data directly, not
    just call PineconeAdapter.connect(). Skips (not errors) if the env
    vars aren't set, or if the real connection attempt fails for any
    reason (wrong key, index doesn't exist, no network) — same "skip
    gracefully on any failure, not just an upfront check" lesson pgvector/
    Qdrant's fixtures already learned this session.
    """
    if not _PINECONE_API_KEY or not _PINECONE_TEST_INDEX:
        pytest.skip("PINECONE_API_KEY / PINECONE_TEST_INDEX not set — see .env.example")

    try:
        from pinecone import Pinecone

        client = Pinecone(api_key=_PINECONE_API_KEY)
        index = client.Index(_PINECONE_TEST_INDEX)
        index.describe_index_stats()  # cheapest real call that proves auth + index name both work
    except Exception as exc:  # noqa: BLE001 -- any real-world failure here means "skip", not "error"
        pytest.skip(f"Pinecone not usable with the configured credentials: {exc}")

    return index
