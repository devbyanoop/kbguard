# Duplicates check

!!! warning "Planned — Week 2"
    Not implemented yet.

## Planned behavior

1. **Exact duplicates:** hash of normalized text (lowercase, whitespace collapsed).
2. **Near duplicates:** a pair is flagged only when **both** signals agree:
   - cosine similarity ≥ threshold (default `0.97`), found cheaply via an ANN index (`faiss`/`hnswlib`) rather than comparing every pair directly;
   - MinHash Jaccard similarity ≥ threshold (default `0.9`), confirming real lexical (word-level) overlap.

   Requiring both is deliberate: cosine similarity alone would flag two chunks that are merely about the same topic — similar embedding, very different wording — as duplicates, which they aren't.
3. **Clustering & severity:** duplicate chunks are grouped into clusters; severity increases when duplicates come from **different sources** (the copy-pasted-policy-text case, more likely to indicate a real content problem than two chunks of the same document overlapping slightly).

## Configuration (planned)

```yaml
checks:
  duplicates: {cosine: 0.97, minhash_jaccard: 0.9}
```

This page will include real examples (what a flagged pair's report entry looks like, how clustering groups show up) once the check is built and tested against the seeded example corpus.
