import importlib.util
import math
from pathlib import Path
from types import ModuleType

import pytest

_SEED_PATH = Path(__file__).parent.parent / "examples" / "policy_corpus" / "seed.py"


def _load_seed_module() -> ModuleType:
    # examples/ isn't part of the installed kbguard package, so a normal
    # import can't find it — loaded by file path instead, which works
    # regardless of sys.path/cwd/how pytest was invoked (see
    # tests/test_registry.py and contract_tests/test_adapter_contract.py
    # for two cases this session where a path/package-relative import
    # broke under one invocation style but not another).
    spec = importlib.util.spec_from_file_location("policy_corpus_seed", _SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed_module = _load_seed_module()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_corpus_has_seventeen_chunks() -> None:
    assert len(seed_module.CHUNKS) == 17
    assert len({c["id"] for c in seed_module.CHUNKS}) == 17  # ids unique


def test_only_intended_pairs_exceed_duplicate_threshold() -> None:
    chunks = seed_module.CHUNKS
    exceeding = set()
    for i, a in enumerate(chunks):
        for b in chunks[i + 1 :]:
            if _cosine(a["embedding"], b["embedding"]) >= 0.97:
                exceeding.add(frozenset({a["id"], b["id"]}))

    assert exceeding == {
        frozenset({"refund-exact-1", "refund-exact-2"}),
        frozenset({"shipping-near-1", "shipping-near-2"}),
    }


def test_stale_version_pair_is_related_but_not_duplicate_level() -> None:
    by_id = {c["id"]: c for c in seed_module.CHUNKS}
    similarity = _cosine(by_id["return-window-v1"]["embedding"], by_id["return-window-v2"]["embedding"])

    assert 0.3 < similarity < 0.97  # related enough for a self-retrieval probe, not a duplicate


def test_stale_version_pair_shares_doc_family_metadata() -> None:
    by_id = {c["id"]: c for c in seed_module.CHUNKS}
    v1, v2 = by_id["return-window-v1"], by_id["return-window-v2"]

    assert v1["metadata"]["doc_id"] == v2["metadata"]["doc_id"]
    assert v1["metadata"]["title"] == v2["metadata"]["title"]
    assert v1["metadata"]["version"] != v2["metadata"]["version"]


def test_no_source_chunk_has_no_doc_id() -> None:
    by_id = {c["id"]: c for c in seed_module.CHUNKS}

    assert "doc_id" not in by_id["no-source-chunk"]["metadata"]


def test_seed_populates_a_real_chroma_collection(tmp_path: Path) -> None:
    seed_module.seed(path=tmp_path / "chroma_data")

    import chromadb

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma_data"))
    collection = client.get_collection("demo", embedding_function=None)

    assert collection.count() == 17


def test_seed_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "chroma_data"
    seed_module.seed(path=path)
    seed_module.seed(path=path)  # must not error or duplicate

    import chromadb

    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_collection("demo", embedding_function=None)

    assert collection.count() == 17


@pytest.mark.parametrize("chunk_id", [c["id"] for c in seed_module.CHUNKS])
def test_every_chunk_embedding_matches_declared_dimension(chunk_id: str) -> None:
    by_id = {c["id"]: c for c in seed_module.CHUNKS}

    assert len(by_id[chunk_id]["embedding"]) == 14
