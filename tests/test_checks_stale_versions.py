from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kbguard.checks.base import CheckContext
from kbguard.checks.stale_versions import StaleVersionsCheck
from kbguard.config import StaleVersionsCheckConfig
from kbguard.ingest.snapshot import SnapshotReader, SnapshotWriter
from kbguard.models import Chunk


def _chunk(chunk_id: str, **overrides: Any) -> Chunk:
    defaults: dict[str, Any] = {
        "id": chunk_id,
        "text": f"text for {chunk_id}",
        "embedding": [1.0, 0.0],
        "metadata": {},
    }
    defaults.update(overrides)
    return Chunk(**defaults)


def _snapshot(tmp_path: Path, chunks: list[Chunk]) -> SnapshotReader:
    writer = SnapshotWriter(tmp_path / "snap", collection="c", adapter_name="chroma", embedding_model="fake")
    for chunk in chunks:
        writer.write_chunk(chunk)
    writer.close()
    return SnapshotReader(tmp_path / "snap")


class _FakeSearchAdapter:
    """Returns the same canned result list regardless of query -- enough
    for tests that only ever make one self-retrieval probe call."""

    name = "fake"

    def __init__(self, results: list[Chunk]) -> None:
        self._results = [(chunk, 1.0) for chunk in results]

    def connect(self, **settings: Any) -> None:
        pass

    def collections(self) -> list[str]:
        return []

    def count(self, collection: str) -> int:
        return 0

    def iter_chunks(self, collection: str, batch_size: int = 500, with_embeddings: bool = True):
        return iter(())

    def search(self, collection: str, query_vector: list[float], k: int, filters: dict[str, Any] | None = None):
        return self._results


_CONFIG = StaleVersionsCheckConfig()


def test_same_title_different_version_escalates_when_both_retrievable(tmp_path: Path) -> None:
    old = _chunk("v1", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    new = _chunk("v2", title="Return Policy", version="v2", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [old, new])

    fake_adapter = _FakeSearchAdapter(results=[old, new])  # probe finds both
    ctx = CheckContext(config=_CONFIG, adapter=fake_adapter, collection="demo")

    findings = list(StaleVersionsCheck().run(reader, ctx))

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert sorted(findings[0].chunk_ids) == ["v1", "v2"]


def test_no_escalation_without_a_live_adapter(tmp_path: Path) -> None:
    old = _chunk("v1", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    new = _chunk("v2", title="Return Policy", version="v2", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [old, new])

    ctx = CheckContext(config=_CONFIG)  # no adapter/collection

    findings = list(StaleVersionsCheck().run(reader, ctx))

    assert len(findings) == 1
    assert findings[0].severity == "warn"


def test_no_escalation_when_probe_does_not_surface_newest(tmp_path: Path) -> None:
    old = _chunk("v1", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    new = _chunk("v2", title="Return Policy", version="v2", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [old, new])

    # Probe only surfaces the old chunk itself, not the current version --
    # stays at the base severity, not escalated.
    fake_adapter = _FakeSearchAdapter(results=[old])
    ctx = CheckContext(config=_CONFIG, adapter=fake_adapter, collection="demo")

    findings = list(StaleVersionsCheck().run(reader, ctx))

    assert findings[0].severity == "warn"


def test_groups_by_normalized_source_when_no_title(tmp_path: Path) -> None:
    old = _chunk(
        "a", source="refund-policy-2024", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc)
    )
    new = _chunk(
        "b", source="refund-policy-2025", version="v2", updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
    )
    reader = _snapshot(tmp_path, [old, new])

    ctx = CheckContext(config=_CONFIG)
    findings = list(StaleVersionsCheck().run(reader, ctx))

    assert len(findings) == 1
    assert sorted(findings[0].chunk_ids) == ["a", "b"]


def test_single_member_family_yields_nothing(tmp_path: Path) -> None:
    chunk = _chunk("a", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [chunk])

    findings = list(StaleVersionsCheck().run(reader, CheckContext(config=_CONFIG)))

    assert findings == []


def test_members_with_no_ordering_signal_yield_nothing(tmp_path: Path) -> None:
    # Same title (same family) but neither has updated_at nor version --
    # no reliable signal for which is older, so nothing is flagged.
    a = _chunk("a", title="Return Policy")
    b = _chunk("b", title="Return Policy")
    reader = _snapshot(tmp_path, [a, b])

    findings = list(StaleVersionsCheck().run(reader, CheckContext(config=_CONFIG)))

    assert findings == []


def test_updated_at_takes_priority_over_version_string(tmp_path: Path) -> None:
    # "a" has only a version string ("v9"); "b" has an actual timestamp.
    # The tiered sort key means anything with updated_at is treated as
    # more reliable and sorts after anything without, regardless of what
    # the version string says.
    a = _chunk("a", title="Return Policy", version="v9")
    b = _chunk("b", title="Return Policy", updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [a, b])

    findings = list(StaleVersionsCheck().run(reader, CheckContext(config=_CONFIG)))

    assert len(findings) == 1
    assert findings[0].evidence["older_id"] == "a"
    assert findings[0].evidence["newest_id"] == "b"


def test_family_with_three_members_flags_every_older_one_against_the_newest(tmp_path: Path) -> None:
    a = _chunk("a", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    b = _chunk("b", title="Return Policy", version="v2", updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    c = _chunk("c", title="Return Policy", version="v3", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [a, b, c])

    findings = list(StaleVersionsCheck().run(reader, CheckContext(config=_CONFIG)))

    pairs = {(f.evidence["older_id"], f.evidence["newest_id"]) for f in findings}
    assert pairs == {("a", "c"), ("b", "c")}  # both older members paired against "c", not just a~b~c chain


def test_disabled_check_yields_nothing(tmp_path: Path) -> None:
    old = _chunk("v1", title="Return Policy", version="v1", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    new = _chunk("v2", title="Return Policy", version="v2", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reader = _snapshot(tmp_path, [old, new])

    config = StaleVersionsCheckConfig(enabled=False)
    findings = list(StaleVersionsCheck().run(reader, CheckContext(config=config)))

    assert findings == []


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

    metadata_map = {"source": "doc_id", "title": "title", "version": "version", "updated_at": "updated_at"}
    chunks = list(export_chunks(adapter, "demo", metadata_map=metadata_map, embedder=_unused_embedder))
    reader = _snapshot(tmp_path, chunks)

    ctx = CheckContext(config=_CONFIG, adapter=adapter, collection="demo")
    findings = list(StaleVersionsCheck().run(reader, ctx))

    assert len(findings) == 1
    assert sorted(findings[0].chunk_ids) == ["return-window-v1", "return-window-v2"]
    assert findings[0].severity == "error"  # v2 genuinely shows up in v1's own top-k neighbors
