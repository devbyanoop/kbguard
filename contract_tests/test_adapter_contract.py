"""The shared suite every VectorStoreAdapter must pass — built-in or
third-party. Each test runs once per backend in conftest.py's BACKENDS list
(currently just "chroma"); the pytest output names which backend failed,
since the test function itself never hardcodes a backend name.

Passing this suite is what lets kbguard's design rule "everything downstream
works on Chunk records, never on a store-specific client" actually be
trusted — not just assumed from looking at the code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    # Only for type hints below — never executed at runtime (annotations are
    # lazy via `from __future__ import annotations`), specifically because a
    # real top-level `from contract_tests.conftest import ContractCase` here
    # fails under the plain `pytest` command: contract_tests/ has no
    # __init__.py, so pytest's import machinery doesn't treat it as a real
    # package from that invocation (same root cause as the fix in
    # tests/test_registry.py). conftest.py itself is always auto-discovered
    # by pytest regardless, which is why the `adapter` fixture still works.
    from contract_tests.conftest import ContractCase


def test_count_matches_iteration(adapter: ContractCase) -> None:
    reported_count = adapter.adapter.count(adapter.collection)
    iterated_count = sum(1 for _ in adapter.adapter.iter_chunks(adapter.collection))

    assert reported_count == iterated_count == len(adapter.chunks)


def test_ids_stable_across_two_scans(adapter: ContractCase) -> None:
    first_scan = {c.id for c in adapter.adapter.iter_chunks(adapter.collection)}
    second_scan = {c.id for c in adapter.adapter.iter_chunks(adapter.collection)}

    expected_ids = {c.id for c in adapter.chunks}
    assert first_scan == second_scan == expected_ids


def test_search_finds_planted_nearest_neighbor(adapter: ContractCase) -> None:
    results = adapter.adapter.search(adapter.collection, adapter.query_vector, k=1)

    assert len(results) == 1
    nearest_chunk, _score = results[0]
    assert nearest_chunk.id == adapter.expected_nearest_id


def test_search_respects_k(adapter: ContractCase) -> None:
    results = adapter.adapter.search(adapter.collection, adapter.query_vector, k=2)

    assert len(results) == 2


def test_metadata_roundtrips(adapter: ContractCase) -> None:
    # A superset check, not exact equality: backends whose payload is one
    # flat namespace holding text, id, AND metadata together (Qdrant,
    # confirmed by hand — its "_kbguard_test_id"/"text" housekeeping keys
    # land in the same payload the seeded metadata does) can't return
    # "pure" metadata with nothing else mixed in, unlike Chroma/pgvector,
    # which store text and metadata genuinely separately. The contract only
    # promises every originally-seeded key/value is present, not that
    # nothing else is.
    expected_by_id = {c.id: c.metadata for c in adapter.chunks}

    for chunk in adapter.adapter.iter_chunks(adapter.collection):
        expected = expected_by_id[chunk.id]
        assert expected.items() <= chunk.metadata.items()


def test_text_roundtrips(adapter: ContractCase) -> None:
    expected_by_id = {c.id: c.text for c in adapter.chunks}

    for chunk in adapter.adapter.iter_chunks(adapter.collection):
        assert chunk.text == expected_by_id[chunk.id]


def test_embeddings_roundtrip_approximately(adapter: ContractCase) -> None:
    expected_by_id = {c.id: c.embedding for c in adapter.chunks}

    for chunk in adapter.adapter.iter_chunks(adapter.collection):
        assert chunk.embedding is not None
        # Approximate, not exact: some backends store embeddings as float32
        # internally, which loses precision relative to the float64 values
        # we seeded with (confirmed on Chroma — 0.3 round-trips as
        # 0.30000001...). That precision loss is an accepted, expected
        # backend characteristic, not a bug the contract should flag.
        assert chunk.embedding == pytest.approx(expected_by_id[chunk.id], abs=1e-5)


def test_with_embeddings_false_omits_embeddings(adapter: ContractCase) -> None:
    chunks = list(adapter.adapter.iter_chunks(adapter.collection, with_embeddings=False))

    assert len(chunks) == len(adapter.chunks)
    assert all(c.embedding is None for c in chunks)
