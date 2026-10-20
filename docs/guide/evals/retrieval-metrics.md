# Retrieval metrics

`evals/retrieval.py`'s `evaluate_retrieval()` is built and tested — hit@k, recall@k, precision@k, MRR@k, nDCG@k, computed using the *live* adapter's `search()` with the same embedding model the snapshot was built with, against the [golden set](golden-sets.md).

## Formulas, verified by hand before trusting the code

Spec's own advice ("derive each formula by hand on a toy example before coding it") was followed literally: two hand-worked toy examples (one relevant doc at rank 2; two relevant docs at ranks 1 and 3) were computed on paper first, then asserted against the function's actual output to full floating-point precision — not "roughly reasonable." For a single relevant doc found at rank 2 out of 3:

| Metric | Formula | Value |
| --- | --- | --- |
| hit@2 | 1 if any expected id in top 2, else 0 | 1.0 |
| recall@2 | \|found ∩ expected\| / \|expected\| | 1.0 |
| precision@2 | \|found ∩ expected\| / k | 0.5 |
| mrr@3 | 1 / rank of first relevant hit | 0.5 |
| ndcg@3 | DCG@3 / IDCG@3 (binary relevance, log₂ discount) | 0.6309297535714574 |

One `EvalResult` per `(question, metric, k)` — aggregating e.g. every `recall@5` result into one mean is left to whatever consumes this list (a report/summary step), not this function's job.

## Cause tagging

Every result's `cause` answers *why* it failed, reading Week 2's own check findings directly — the concrete link that makes "trace every failure to a cause" real, not aspirational:

- **`content`** — an expected chunk is either missing from the snapshot entirely, or already flagged by a [knowledge-base check](../checks/overview.md) (stale, damaged, duplicate). Fixing retrieval wouldn't have helped.
- **`retrieval`** — the expected chunk exists and is unflagged, but simply wasn't surfaced in the top-k.
- **`none`** — the question passed (an expected chunk was found).

`passed` and `cause` are shared across all five metrics at a given `(question, k)` — they all answer the same underlying question (was an expected chunk surfaced?) as different numbers, so there's one verdict per question/k, not five independent ones.

## Verified against the real example corpus

A golden question whose answer is verifiably in `privacy-1`, queried with that chunk's own real embedding vector (the nearest neighbor to your own vector is yourself) — `hit@1 = 1.0`, `cause = "none"`. See `tests/test_evals_retrieval.py::test_against_real_example_corpus`.
