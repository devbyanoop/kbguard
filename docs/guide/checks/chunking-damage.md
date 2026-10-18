# Chunking damage check

!!! warning "Planned — Week 2"
    Not implemented yet.

## Planned rules

All six rules are deterministic — no embeddings, no LLM calls, runs in milliseconds per chunk:

| Rule | Detects |
| --- | --- |
| Size | Chunks below min or above max tokens |
| Split table | Markdown/pipe-table rows or header row cut at a chunk boundary |
| Orphan heading | Chunk is only a heading, or ends with one |
| Broken sentence | Chunk starts mid-sentence, with no overlap from the previous chunk |
| Missing metadata | Required fields (from config) absent |
| Encoding noise | High ratio of control characters, repeated headers/footers |

## Configuration (planned)

```yaml
checks:
  chunking_damage: {min_tokens: 40, max_tokens: 800, required_metadata: [source]}
```

This page will include real examples of each rule firing, once the check is built and tested against a seeded corpus with one planted example per rule.
