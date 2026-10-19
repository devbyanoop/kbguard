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
