from kbguard.adapters.chroma import ChromaAdapter
from kbguard.registry import load_adapter

# Unlike test_registry.py (which exercises registry.py's own lookup logic
# against a fake, mocked entry point), these tests use the *real* installed
# package metadata. They'd fail if pyproject.toml's
# [project.entry-points."kbguard.adapters"] table ever drifted from the
# actual class path — e.g. a typo, or an adapter getting renamed without
# updating its registration. One test per built-in adapter, added as each
# one is built.


def test_chroma_adapter_is_registered() -> None:
    assert load_adapter("chroma") is ChromaAdapter
