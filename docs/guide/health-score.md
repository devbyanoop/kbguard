# Health score

`scoring/health.py` computes a single 0–100 score per collection — one number a non-technical stakeholder can read at a glance.

## Formula

```text
health = 100
       - w_dup   * duplicate_chunk_ratio      * 100
       - w_stale * stale_chunk_ratio          * 100
       - w_chunk * damaged_chunk_ratio        * 100
       - w_conf  * min(1, conflicts / 20)     * 100
```

Default weights (configurable via `health:` in `kbguard.yaml`): duplicates `0.15`, stale `0.30`, chunking `0.20`, contradictions `0.35` (sum to `1.0`, so a maximally unhealthy collection scores `0`). **The score is clamped to `[0, 100]`** regardless of configured weights — custom weights that don't sum to 1 can't push it out of range, the fix the original architecture review called out explicitly.

The three per-chunk ratios (`duplicate_chunk_ratio`, `stale_chunk_ratio`, `damaged_chunk_ratio`) are each the *distinct* chunk ids that check flagged, divided by total chunk count — a chunk flagged by two separate findings from the same check still only counts once. Contradictions use a plain finding count instead of a ratio, since one contradiction finding already involves two chunks, and a corpus-size-relative ratio would mean wildly different things on a 50-chunk vs. a 50,000-chunk collection.

## Two functions, split on purpose

```python
def summarize_findings(snapshot: SnapshotReader) -> FindingsSummary: ...
def compute_health(findings_summary: FindingsSummary, weights: HealthWeights) -> int: ...
```

`summarize_findings` reads a snapshot's findings and reduces them to the four numbers the formula needs. `compute_health` is a pure function over that summary plus a weights object — no snapshot, no I/O — deliberately "obviously correct" code (a handful of ratios and a weighted sum) with a thorough test matrix instead of anything clever, since this is the one number a client will actually look at.

## Configuration

```yaml
health:
  duplicates: 0.15        # default
  stale_versions: 0.30    # default
  chunking_damage: 0.20   # default
  contradictions: 0.35    # default
```

## Worked example (real, from the example corpus)

Running `kbguard scan` against `examples/policy_corpus/` (17 chunks) with default weights produces **health = 86**, computed as:

| Dimension | Flagged chunks | Ratio | Weight | Contribution |
| --- | --- | --- | --- | --- |
| Duplicates | 4 of 17 | 0.2353 | 0.15 | −3.53 |
| Stale versions | 2 of 17 | 0.1176 | 0.30 | −3.53 |
| Chunking damage | 6 of 17 | 0.3529 | 0.20 | −7.06 |
| Contradictions | 0 findings | 0.0 | 0.35 | 0 |

`100 − 3.53 − 3.53 − 7.06 − 0 = 85.88`, rounded to **86** — verified by actually running `kbguard scan` against the real corpus and reading `results.json`, not hand-waved.

## Why eval metrics aren't mixed into this number

Retrieval/answer-quality metrics (recall@5, faithfulness, etc.) are reported as a **separate scorecard**, not folded into the health score. Content quality and system quality are different things that can move independently — a perfectly clean knowledge base can still sit behind broken retrieval, and mixing the two into one number would hide that distinction from exactly the person the number is meant to help.
