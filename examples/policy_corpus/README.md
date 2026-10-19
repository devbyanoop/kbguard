# Example policy corpus

A small, synthetic company-policy knowledge base (16 chunks) with deliberately planted problems, used:

- today, to have something real for `kbguard scan` to point at (Week 1);
- from Week 2 onward, as the fixture every knowledge-base check is tested against — "every seeded problem in this corpus is found" is that week's actual done-when criterion.

## Setup

```bash
python examples/policy_corpus/seed.py
kbguard scan --collection demo --config examples/policy_corpus/kbguard.yaml
```

`seed.py` is idempotent — running it again when the collection already has all 16 chunks is a no-op.

## What's planted, and which check (Week 2+) should catch it

| Chunk id(s) | Problem | Check |
| --- | --- | --- |
| `refund-exact-1`, `refund-exact-2` | Identical text, different sources (copy-pasted policy) | `duplicates` (exact) |
| `shipping-near-1`, `shipping-near-2` | Reworded near-duplicate, different sources | `duplicates` (near, cosine ≥ 0.97) |
| `return-window-v1`, `return-window-v2` | Same doc family, different version/date, older still present | `stale_versions` |
| `return-window-v1`, `return-window-v2` | Also disagree on the refund window (14 vs. 30 days) | `contradictions` |
| `warranty-a`, `warranty-b` | Two unrelated docs disagreeing (1-year vs. 2-year), not a version pair | `contradictions` |
| `pricing-table-cut` | Markdown table cut mid-row | `chunking_damage` (split table) |
| `orphan-heading-1` | Chunk is only a heading | `chunking_damage` (orphan heading) |
| `tiny-chunk-1` | Far below the default `min_tokens` | `chunking_damage` (size) |
| `broken-sentence-1` | Starts mid-sentence, no overlap | `chunking_damage` (broken sentence) |
| `no-source-chunk` | No `doc_id` at all → `source` stays unmapped | `chunking_damage` (missing metadata) |
| `privacy-1`, `contact-1`, `account-1` | None — clean, for contrast | (none should fire) |

## On the embeddings

These are **hand-crafted vectors, not output from a real embedding model.** That's deliberate: the corpus needs to work against the *actual default* duplicate threshold (`cosine: 0.97`) to be a real test of the detection logic — not a scenario tuned around whatever a real model happened to produce. Every pairwise cosine similarity was computed and checked by hand before being committed (see the comment block at the top of `seed.py`): only the two intended pairs clear 0.97; the stale-version pair (0.707) and the contradiction pair (0.640) are deliberately well below it, so they're not also mistaken for near-duplicates; everything else is near-orthogonal.
