"""Real integration test for checks/contradictions.py against a live LLM
— the live-judge counterpart to test_checks_contradictions.py's fake-judge
unit tests, same relationship test_adapters_pinecone_live.py has to
test_adapters_pinecone.py.

Needs a real judge configured (see tests/conftest.py's `real_judge`
fixture — Groq by default, GROQ_API_KEY from .env). Skips cleanly, not an
error, when no provider's key is usable.
"""

from pathlib import Path
from typing import Any

from kbguard.checks.base import CheckContext
from kbguard.checks.contradictions import ContradictionsCheck
from kbguard.config import ContradictionsCheckConfig
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter


def _snapshot(tmp_path: Path, chunks: list[Any]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="demo", adapter_name="chroma", embedding_model="hand-crafted")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


def test_real_judge_confirms_the_real_planted_contradiction(tmp_path: Path, real_judge: Any) -> None:
    import importlib.util

    from kbguard.adapters.chroma import ChromaAdapter
    from kbguard.ingest.exporter import export_chunks

    repo_root = Path(__file__).parent.parent
    seed_path = repo_root / "examples" / "policy_corpus" / "seed.py"
    spec = importlib.util.spec_from_file_location("policy_corpus_seed", seed_path)
    assert spec is not None and spec.loader is not None
    seed_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_module)
    seed_module.seed()

    adapter = ChromaAdapter()
    adapter.connect(path=str(repo_root / "examples" / "policy_corpus" / "chroma_data"))

    def _unused_embedder(text: str) -> list[float]:
        raise AssertionError("embedder should not be called")

    chunks = list(export_chunks(adapter, "demo", metadata_map={"source": "doc_id"}, embedder=_unused_embedder))
    reader = _snapshot(tmp_path, chunks)

    config = ContradictionsCheckConfig(enabled=True)
    ctx = CheckContext(config=config, judge=real_judge)

    findings = list(ContradictionsCheck().run(reader, ctx))

    # Exactly the one genuine candidate the real pipeline narrows down to
    # (verified earlier, against a fake judge, in
    # test_checks_contradictions.py::test_against_real_example_corpus) --
    # here a REAL LLM independently reasons about it and confirms it's a
    # genuine conflict, not a canned fake response.
    assert len(findings) == 1
    finding = findings[0]
    assert sorted(finding.chunk_ids) == ["warranty-a", "warranty-b"]
    assert finding.severity == "error"
    assert finding.evidence["fact_type"] == "duration"
    assert finding.evidence["subject"] == "warranty"
    # The real judge's own explanation -- not asserting exact wording
    # (that's genuinely non-deterministic LLM output), just that it
    # actually provided one.
    assert len(finding.evidence.get("explanation") or "") > 20
