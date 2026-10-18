# Health score

!!! warning "Planned — Week 2 (scoring/health.py)"
    Not implemented yet.

## Planned formula

A single 0–100 score per collection, intended for a non-technical stakeholder who just needs one number:

```text
health = 100
       - w_dup   * duplicate_chunk_ratio      * 100
       - w_stale * stale_chunk_ratio          * 100
       - w_chunk * damaged_chunk_ratio        * 100
       - w_conf  * min(1, conflicts / 20)     * 100
```

Default weights: duplicates `0.15`, stale `0.30`, chunking `0.20`, conflicts `0.35` (sum to `1.0`, so a maximally unhealthy collection scores `0`). **The score is clamped to `[0, 100]`** regardless of configured weights, so a custom weight set that doesn't sum to 1 can't push it out of range.

## Why eval metrics aren't mixed into this number

Retrieval/answer-quality metrics (recall@5, faithfulness, etc.) are reported as a **separate scorecard**, not folded into the health score. Content quality and system quality are different things that can move independently — a perfectly clean knowledge base can still sit behind broken retrieval, and mixing the two into one number would hide that distinction from exactly the person the number is meant to help.

This page will include a real worked example once `scoring/health.py` is built and tested.
