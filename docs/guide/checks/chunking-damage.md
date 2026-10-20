# Chunking damage check

`ChunkingDamageCheck` (`chunking_damage` plugin name) looks for chunks that were cut in a way that hurts retrieval or generation quality — a table sliced mid-row, a heading left alone with no body, a sentence starting mid-thought, a chunk far too small or too large, required metadata missing, or signs of bad text extraction. All six rules are deterministic — no embeddings, no LLM calls, no optional dependencies, runs in milliseconds per chunk.

## Rules

| Rule | Detects | Evidence fields |
| --- | --- | --- |
| `size` | Chunk's approximate word count is below `min_tokens` or above `max_tokens` | `approx_word_count`, `min_tokens` or `max_tokens` |
| `split_table` | Chunk ends with a pipe-table row cut off mid-row, or starts with the tail of one | `edge` (`"start"` or `"end"`) |
| `orphan_heading` | Chunk is only a heading, or ends with one and nothing follows | — |
| `broken_sentence` | Chunk starts mid-sentence (lowercase first letter, or starts with `...`) with no word overlap from the chunk immediately before it in the same source | — |
| `missing_metadata` | A field listed in `required_metadata` is `null` on this chunk | `missing_fields` |
| `encoding_noise` | High ratio of control characters, or a non-trivial line repeated within the same chunk | `control_char_count` or `line` |

"Tokens" means whitespace-split words, not a model-accurate tokenizer (tiktoken) — a deliberate choice to keep this check cheap and dependency-free, stated explicitly in each finding's evidence rather than silently implying a model-accurate count.

### `size`

Flags chunks below `min_tokens` or above `max_tokens`. The global default is `min_tokens: 40, max_tokens: 800`, following the architecture spec's assumption of realistic production chunk sizes.

!!! note "The example corpus overrides min_tokens"
    `examples/policy_corpus/kbguard.yaml` sets `min_tokens: 10` for its `chunking_damage` config. That corpus's chunks are deliberately tiny (3–25 words) single-sentence snippets, built for easy hand-verification — not representative of real production chunk sizes. At the global default of 40, nearly every chunk in that corpus would be flagged as undersized, burying the one chunk actually meant to demonstrate the rule (`tiny-chunk-1`, 3 words). This is a corpus-design mismatch, not a bug in the 40-word default, so the override lives in the example's own config, not in `config.py`.

### `split_table`

Looks only at the chunk's first and last non-blank line. A last line that starts with `|` but doesn't end with `|` is a row cut off at the end (`edge: "end"`); a first line that ends with `|` but doesn't start with `|` is the tail of a row cut off at the start (`edge: "start"`). A complete row (starts and ends with `|`) is left alone, as is a chunk with no pipe characters at all.

### `orphan_heading`

A chunk is flagged if it consists of only a heading line, or ends with one. A line counts as heading-like if it starts with `#`, or if it's short (≤8 words, ≤60 characters), has no terminal punctuation, and every alphabetic word in it is capitalized.

!!! warning "Regression: table rows misclassified as headings"
    Found by hand against the real example corpus: `pricing-table-cut`'s cut-off last row (`"| Pro | $25/mo"`) is short, ends with no terminal punctuation, and its one real word (`Pro`) is capitalized — so it passed every heading heuristic and was wrongly flagged as `orphan_heading` in addition to the correct `split_table` finding. Fixed by explicitly excluding any line containing `|` from `_looks_like_heading` before checking the other criteria — a pipe is a strong table-row signal, never a heading signal. Covered by a dedicated regression test (`test_table_row_not_misclassified_as_heading`).

### `broken_sentence`

A chunk "starts mid-sentence" if its first character (after stripping leading whitespace) is lowercase, or it starts with `...`. That alone isn't enough to flag it: sliding-window chunking deliberately repeats the tail of one chunk at the head of the next, and that's not damage. So this rule also builds a predecessor index — for chunks that have both `source` and `position` set, the chunk at `position - 1` in the same source — and checks for any shared word (case-insensitive, trailing punctuation stripped) in the last 5 words of the predecessor and the first 5 words of this chunk. Overlap found → treated as intentional, not flagged. A chunk with no identifiable predecessor (missing `source`/`position`, or no sibling at `position - 1`) isn't given the benefit of the doubt — it's flagged, since there's no way to confirm deliberate overlap either way.

### `missing_metadata`

Flags a chunk if any field named in `required_metadata` (default `[]`, so this rule flags nothing until configured) is `null` on that chunk. Reports all missing fields in one finding, not one finding per field.

### `encoding_noise`

Two independent signals, checked in order, at most one finding per chunk:

1. **Control characters.** If more than 1% of the chunk's characters are control characters (ordinal < 32, excluding `\n`/`\t`/`\r`), flagged — a common artifact of bad PDF text extraction.
2. **Repeated line.** Failing that, if any line of 3+ characters appears more than once within the same chunk, flagged — a crude proxy for a running header/footer leaking into chunk content. This only catches repetition *within* one chunk; the same header repeated once each across many different chunks needs cross-chunk analysis this rule doesn't do.

!!! note "The 1% control-character threshold isn't empirically calibrated"
    Unlike `duplicates.py`'s `minhash_jaccard` threshold (measured against real near-duplicate pairs — see [Duplicates](duplicates.md)), no real corpus of corrupted documents was available to tune this one against. Revisit if real-world false positives or negatives turn up.

## Configuration

```yaml
checks:
  chunking_damage:
    enabled: true
    severity: warn          # default
    min_tokens: 40
    max_tokens: 800
    required_metadata: []   # e.g. [source]
```

## Example corpus

Running against `examples/policy_corpus/` (with that corpus's own `min_tokens: 10` override) produces exactly:

| Rule | Chunk(s) flagged |
| --- | --- |
| `size` | `tiny-chunk-1`, `orphan-heading-1` |
| `split_table` | `pricing-table-cut` |
| `orphan_heading` | `orphan-heading-1` |
| `broken_sentence` | `broken-sentence-1` |
| `missing_metadata` | `no-source-chunk` |
| `encoding_noise` | `encoding-noise-1` |

Verified by `tests/test_checks_chunking_damage.py::test_against_real_example_corpus`, which asserts this exact mapping.
