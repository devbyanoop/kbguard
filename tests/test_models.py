from datetime import datetime

from kbguard.models import Chunk, EvalResult, Finding, Snapshot, compute_fingerprint


def test_chunk_defaults_dont_share_metadata_dict():
    a = Chunk(id="a", text="hello", embedding=None)
    b = Chunk(id="b", text="world", embedding=None)

    a.metadata["x"] = 1

    assert b.metadata == {}


def test_chunk_standard_fields_default_to_none():
    c = Chunk(id="a", text="hello", embedding=[0.1, 0.2])

    assert c.source is None
    assert c.position is None
    assert c.version is None
    assert c.updated_at is None
    assert c.title is None


def test_finding_default_fingerprint_is_empty():
    f = Finding(check="duplicates", severity="warn", chunk_ids=["a", "b"], message="dup")

    assert f.fingerprint == ""


def test_compute_fingerprint_is_order_independent():
    fp1 = compute_fingerprint("duplicates", ["a", "b"])
    fp2 = compute_fingerprint("duplicates", ["b", "a"])

    assert fp1 == fp2
    assert len(fp1) == 16


def test_compute_fingerprint_distinguishes_identity_keys():
    too_short = compute_fingerprint("chunking_damage", ["a"], identity_keys=["size"])
    orphan_heading = compute_fingerprint("chunking_damage", ["a"], identity_keys=["orphan_heading"])

    assert too_short != orphan_heading


def test_compute_fingerprint_distinguishes_checks():
    fp1 = compute_fingerprint("duplicates", ["a", "b"])
    fp2 = compute_fingerprint("contradictions", ["a", "b"])

    assert fp1 != fp2


def test_eval_result_defaults_to_no_cause():
    r = EvalResult(question_id="q1", metric="recall@5", value=1.0, passed=True)

    assert r.cause == "none"
    assert r.details == {}


def test_snapshot_round_trips_fields():
    now = datetime(2026, 10, 18, 9, 0, 0)
    s = Snapshot(
        id="2026-10-18T09-00_policies",
        collection="policies",
        adapter="chroma",
        created_at=now,
        chunk_count=42,
        path=".kbguard/snapshots/2026-10-18T09-00_policies/",
    )

    assert s.chunk_count == 42
    assert s.created_at == now
