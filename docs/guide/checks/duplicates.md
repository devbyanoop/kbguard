# Duplicates check

Implemented and verified against the real example corpus — both the exact-duplicate pair and the reworded near-duplicate pair are found, and nothing else is.

## How it works

1. **Exact:** hash of normalized text (lowercase, whitespace collapsed). Chunks sharing a hash form one cluster.
2. **Near:** an ANN index (`faiss`, `IndexFlatIP` on L2-normalized vectors — exact cosine similarity, not an approximation at this scale) finds cosine-similarity candidates among chunks *not* already exact-matched; `datasketch` MinHash then estimates lexical (word-set) overlap. **A pair is flagged only when both thresholds are met.**
3. **Clustering:** near-duplicate pairs are merged transitively (union-find) — if A↔B and B↔C both pass but A↔C doesn't directly, all three still land in one finding, not two overlapping ones.
4. **Severity:** `warn` by default, escalated to `error` when a cluster spans two or more distinct `source` values — regardless of a configured override, since cross-source duplication (copy-pasted content) is specifically called out as more significant than duplication within one document.

## Why both signals are required

Cosine similarity alone would flag two chunks that are merely *about* the same topic — similar embedding, different wording — as duplicates. MinHash alone has the opposite problem, measured directly against this project's own example corpus: the **stale-version pair** (`return-window-v1`/`v2`, differing by a single word — "14 days" vs. "30 days") scores **0.852** word-Jaccard, high enough to look like a near-duplicate on lexical grounds alone. It's cosine similarity (0.707, well below the 0.97 threshold) that correctly excludes it — confirming the two-signal design is load-bearing, not redundant caution. Both of these false-positive directions are covered by dedicated tests.

## The MinHash threshold default was wrong in the original spec, and is now fixed

The architecture spec's original default was `minhash_jaccard: 0.9`. Before trusting it, it was checked against the example corpus's actual reworded near-duplicate pair (`shipping-near-1`/`shipping-near-2` — "typically takes 3 to 5 business days" vs. "usually takes three to five business days"):

| Shingling scheme | Near-dup pair | Unrelated text |
| --- | --- | --- |
| Word 3-grams | **0.0** | 0.0 |
| Word unigrams (used) | **0.469** | ≤ 0.18 |
| Character 4-grams | 0.461 | ≤ 0.023 |

Word trigrams — a natural first choice for "word shingles" — scored **zero** for a genuine paraphrase: a handful of synonym substitutions ("typically"→"usually", "3 to 5"→"three to five") invalidates nearly every trigram. At the spec's original `0.9` threshold, this check would have essentially never fired for real paraphrased duplicates, since a Jaccard that high only occurs for text that's already near word-for-word identical. The default is now **`0.3`** — comfortably below the measured near-duplicate value (room for more heavily-paraphrased duplicates to still pass) and well clear of the unrelated-text ceiling.

## Configuration

```yaml
checks:
  duplicates:
    enabled: true
    cosine: 0.97
    minhash_jaccard: 0.3
    severity: warn
```

## Example finding

Run against `examples/policy_corpus/`:

```
error  exact  [refund-exact-1, refund-exact-2]  2 chunks are exact duplicates across sources: customer-faq, refund-policy
error  near   [shipping-near-1, shipping-near-2]  2 chunks are near duplicates across sources: shipping-faq, shipping-policy
```
