# Retrieval metrics

!!! warning "Planned — Week 3"
    Not implemented yet.

## Planned metrics

hit@k, recall@k, precision@k, MRR, nDCG@k — computed using the same adapter `search()` call and the same embedding model used during the scan, against the [golden set](golden-sets.md).

## Cause tagging

Every failing retrieval result is tagged with why it failed, so you're not left guessing whether it's a content problem or a retrieval problem:

- **`content`** — the expected chunk is missing entirely, or was flagged by a [knowledge-base check](../checks/overview.md) (e.g. it's stale or damaged).
- **`retrieval`** — the expected chunk exists and is healthy, but wasn't returned in the top-k.

This is the concrete link between the checks (Week 2) and the evals (Week 3) that makes kbguard's "trace every failure to a cause" promise real rather than just a design goal.

This page will include real numbers from the seeded example corpus once `evals/retrieval.py` is built and tested.
