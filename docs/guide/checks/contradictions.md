# Contradictions check

!!! warning "Planned — Week 2"
    Not implemented yet.

## Planned behavior

1. Cluster chunks by embedding similarity.
2. Extract facts — numbers, money, percentages, durations, dates — along with a nearby subject phrase (e.g. "refund window" next to "30 days").
3. Build candidate pairs: same subject, different value, different source.
4. Only those candidate pairs — never the full corpus — go to an LLM judge, which confirms whether it's a real conflict and explains why.

This "cheap first, LLM last" narrowing is what keeps LLM cost bounded even on a large corpus — the number of judge calls scales with the number of actual candidate conflicts, not with corpus size.

## Fact types covered in v0.1

Numbers, money, percentages, durations, and dates — not yet open-ended claims or qualitative statements.

## Configuration (planned)

```yaml
checks:
  contradictions: {types: [number, date, money, percent, duration]}
```

## On false positives

v0.1 deliberately limits scope to numeric/date-shaped facts specifically to keep the false-positive rate manageable. Every flagged pair shows both chunks side by side so a human can judge quickly; labels from that review feed [judge calibration](../evals/judge-and-calibration.md).

This page will include real examples once the check is built and tested against a seeded contradicting pair.
