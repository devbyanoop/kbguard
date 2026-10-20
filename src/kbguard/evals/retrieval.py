import math
from collections.abc import Callable
from typing import Literal

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.evals.golden import GoldenRow
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import EvalResult

_METRIC_NAMES = ["hit", "recall", "precision", "mrr", "ndcg"]


def evaluate_retrieval(
    golden: list[GoldenRow],
    adapter: VectorStoreAdapter,
    collection: str,
    snapshot: SnapshotReader,
    k_values: list[int],
    embedder: Callable[[str], list[float]],
) -> list[EvalResult]:
    """hit@k/recall@k/precision@k/MRR@k/nDCG@k against a golden set, using
    the *live* adapter's search (not the snapshot) with the same embedding
    model the snapshot itself was built with — a golden question's
    embedding has to live in the same vector space as the chunks it's
    being compared against.

    One EvalResult per (question, metric, k) — aggregating e.g. every
    "recall@5" result into a single mean recall@5 is left to whatever
    consumes this list (a report/summary step), not this function's job.

    `cause` and `passed` are shared across all 5 metrics at a given
    (question, k): they all answer the same underlying question — was an
    expected chunk actually surfaced in the top k? — just as different
    numbers. `cause` reads Week 2's own check findings (spec's `content`
    vs `retrieval` distinction only means anything with that link): a
    miss where an expected chunk is missing from the snapshot or already
    flagged by a check is `content`'s fault, not the search/embedding
    pipeline's.
    """
    known_chunk_ids = {c.id for c in snapshot.chunks()}
    flagged_chunk_ids = {cid for finding in snapshot.findings() for cid in finding.chunk_ids}

    results: list[EvalResult] = []
    for row in golden:
        expected = set(row.expected_chunk_ids)
        query_vector = embedder(row.question)
        search_results = adapter.search(collection, query_vector, k=max(k_values) if k_values else 0)
        retrieved = [chunk.id for chunk, _score in search_results]

        for k in k_values:
            top_k = retrieved[:k]
            hit = 1.0 if expected & set(top_k) else 0.0
            passed = hit == 1.0
            cause = _cause(expected, known_chunk_ids, flagged_chunk_ids, passed)

            values: dict[str, float] = {
                "hit": hit,
                "recall": _recall_at_k(top_k, expected),
                "precision": _precision_at_k(top_k, expected, k),
                "mrr": _mrr_at_k(top_k, expected),
                "ndcg": _ndcg_at_k(top_k, expected, k),
            }
            for metric_name in _METRIC_NAMES:
                results.append(
                    EvalResult(
                        question_id=row.id,
                        metric=f"{metric_name}@{k}",
                        value=values[metric_name],
                        passed=passed,
                        cause=cause,
                        details={"expected_chunk_ids": sorted(expected), "retrieved": top_k},
                    )
                )

    return results


def _cause(
    expected: set[str], known_chunk_ids: set[str], flagged_chunk_ids: set[str], passed: bool
) -> Literal["content", "retrieval", "generation", "none"]:
    if passed:
        return "none"
    # A miss is "content"'s fault if *any* expected chunk is simply gone
    # from the collection, or already flagged by a Week 2 check — in
    # either case, fixing retrieval wouldn't have helped; the content
    # itself needs fixing first.
    if any(cid not in known_chunk_ids or cid in flagged_chunk_ids for cid in expected):
        return "content"
    return "retrieval"


def _recall_at_k(top_k: list[str], expected: set[str]) -> float:
    if not expected:
        return 0.0
    return len(expected & set(top_k)) / len(expected)


def _precision_at_k(top_k: list[str], expected: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    return len(expected & set(top_k)) / k


def _mrr_at_k(top_k: list[str], expected: set[str]) -> float:
    for rank, chunk_id in enumerate(top_k, start=1):
        if chunk_id in expected:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(top_k: list[str], expected: set[str], k: int) -> float:
    dcg = sum((1.0 if chunk_id in expected else 0.0) / math.log2(rank + 1) for rank, chunk_id in enumerate(top_k, start=1))
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0
