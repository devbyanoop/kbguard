from pathlib import Path
from typing import Any

from kbguard.checks.base import CheckContext
from kbguard.checks.contradictions import ContradictionsCheck, ContradictionsCheckError
from kbguard.config import ContradictionsCheckConfig
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk


class _FakeJudge:
    """Always answers the same way, and records every call — enough to
    assert both "a finding was produced" and "the judge was (or wasn't)
    called", which is the whole point of the cheap-first design."""

    def __init__(self, conflict: bool = True) -> None:
        self._conflict = conflict
        self.calls: list[tuple[str, str]] = []

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        self.calls.append((prompt, schema_hint))
        return {"conflict": self._conflict, "explanation": "fake judge response"}


def _chunk(chunk_id: str, text: str, embedding: list[float], source: str | None = None) -> Chunk:
    return Chunk(id=chunk_id, text=text, embedding=embedding, metadata={}, source=source)


def _snapshot(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


_CONFIG = ContradictionsCheckConfig(enabled=True)

# Same-topic pair (cosine well above the 0.6 clustering threshold), same
# subject ("warranty"), genuinely different sources and values.
_WARRANTY_A = _chunk(
    "warranty-a",
    "All electronics purchased through our store come with a 1-year manufacturer warranty.",
    [1.0, 0.0],
    source="warranty-policy",
)
_WARRANTY_B = _chunk(
    "warranty-b",
    "All electronics are covered by a 2-year warranty from the date of purchase.",
    [0.95, 0.312],  # cosine ~0.95 with warranty-a -- comfortably above 0.6
    source="product-faq",
)


def _run(reader: SnapshotReader, judge: Any, config: ContradictionsCheckConfig = _CONFIG) -> list:
    ctx = CheckContext(config=config, judge=judge)
    return list(ContradictionsCheck().run(reader, ctx))


def test_confirmed_candidate_produces_a_finding(tmp_path: Path) -> None:
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, _WARRANTY_B])

    findings = _run(reader, judge)

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert sorted(findings[0].chunk_ids) == ["warranty-a", "warranty-b"]
    assert findings[0].evidence["fact_type"] == "duration"
    assert findings[0].evidence["subject"] == "warranty"
    assert len(judge.calls) == 1  # exactly one candidate, so exactly one judge call


def test_judge_saying_not_a_conflict_produces_no_finding(tmp_path: Path) -> None:
    judge = _FakeJudge(conflict=False)
    reader = _snapshot(tmp_path, [_WARRANTY_A, _WARRANTY_B])

    findings = _run(reader, judge)

    assert findings == []
    assert len(judge.calls) == 1  # still called -- the judge is the one deciding "not a conflict"


def test_same_value_is_not_a_candidate_judge_never_called(tmp_path: Path) -> None:
    same_value_b = _chunk(
        "warranty-b2",
        "All electronics are covered by a 1-year warranty from the date of purchase.",
        [0.95, 0.312],
        source="product-faq",
    )
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, same_value_b])

    findings = _run(reader, judge)

    assert findings == []
    assert judge.calls == []


def test_same_source_is_not_a_candidate_judge_never_called(tmp_path: Path) -> None:
    same_source_b = _chunk(
        "warranty-b3",
        "All electronics are covered by a 2-year warranty from the date of purchase.",
        [0.95, 0.312],
        source="warranty-policy",  # same source as warranty-a
    )
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, same_source_b])

    findings = _run(reader, judge)

    assert findings == []
    assert judge.calls == []


def test_unclustered_chunks_never_get_their_facts_compared(tmp_path: Path) -> None:
    # Same subject/type/different-value/different-source on paper, but the
    # two chunks are topically unrelated (orthogonal embeddings) -- cosine
    # similarity is ~0, well below the clustering threshold, so they're
    # never even compared.
    unrelated_b = _chunk(
        "unrelated-warranty",
        "All electronics are covered by a 2-year warranty from the date of purchase.",
        [0.0, 1.0],  # orthogonal to warranty-a's [1.0, 0.0]
        source="product-faq",
    )
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, unrelated_b])

    findings = _run(reader, judge)

    assert findings == []
    assert judge.calls == []


def test_disabled_check_yields_nothing_judge_never_called(tmp_path: Path) -> None:
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, _WARRANTY_B])
    config = ContradictionsCheckConfig(enabled=False)

    findings = _run(reader, judge, config)

    assert findings == []
    assert judge.calls == []


def test_missing_judge_raises(tmp_path: Path) -> None:
    reader = _snapshot(tmp_path, [_WARRANTY_A, _WARRANTY_B])
    ctx = CheckContext(config=_CONFIG, judge=None)

    try:
        list(ContradictionsCheck().run(reader, ctx))
        raised = False
    except ContradictionsCheckError:
        raised = True
    assert raised


def test_fewer_than_two_chunks_yields_nothing(tmp_path: Path) -> None:
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A])

    findings = _run(reader, judge)

    assert findings == []
    assert judge.calls == []


def test_disabled_fact_type_excludes_it(tmp_path: Path) -> None:
    # "duration" excluded from config.types -> the warranty pair's only
    # fact type is never extracted, so there's nothing to pair at all.
    config = ContradictionsCheckConfig(types=["money", "percent", "date", "number"])
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [_WARRANTY_A, _WARRANTY_B])

    findings = _run(reader, judge, config)

    assert findings == []
    assert judge.calls == []


def test_money_percent_and_duration_facts_all_extracted_without_cross_contamination(tmp_path: Path) -> None:
    # One sentence pair carrying three different fact types at once (money,
    # percent, duration) -- a regression guard for the overlap-exclusion
    # logic in _extract_facts: a bare "number" fact must never also be
    # produced for e.g. the "15" inside "$15" or the "30" inside "30 days".
    # Verified against real spaCy output before writing this test (not
    # assumed): all three fact types resolve to the same subject on both
    # sides ("month", "discount", "renew"), and no stray "number" facts
    # appear at all.
    chunk_x = _chunk(
        "pricing-x",
        "The subscription costs $15 per month, includes a 20% discount for annual plans, "
        "and renews after 30 days.",
        [1.0, 0.0],
        source="pricing-page",
    )
    chunk_y = _chunk(
        "pricing-y",
        "The subscription costs $25 per month, includes a 10% discount for annual plans, "
        "and renews after 60 days.",
        [0.95, 0.312],
        source="pricing-faq",
    )
    judge = _FakeJudge(conflict=True)
    reader = _snapshot(tmp_path, [chunk_x, chunk_y])

    findings = _run(reader, judge)

    fact_types = {f.evidence["fact_type"] for f in findings}
    assert fact_types == {"money", "percent", "duration"}  # exactly these three, no stray "number"
    assert len(findings) == 3
    assert len(judge.calls) == 3


def test_against_real_example_corpus(tmp_path: Path) -> None:
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

    judge = _FakeJudge(conflict=True)
    findings = _run(reader, judge)

    # Only the warranty-a/warranty-b pair is a genuine candidate: it's the
    # only same-subject/different-value pair whose two chunks come from
    # different sources. return-window-v1/v2 is also same-subject/
    # different-value, but shares one source (same doc_id, different
    # version) -- that's stale_versions' finding to make, not this check's;
    # requiring *confirmed* different sources correctly excludes it here.
    assert len(findings) == 1
    assert sorted(findings[0].chunk_ids) == ["warranty-a", "warranty-b"]
    # 17 chunks in the corpus, but only 1 candidate pair ever reaches the
    # judge -- the whole point of clustering + subject/value/source
    # narrowing before any LLM call.
    assert len(judge.calls) == 1
