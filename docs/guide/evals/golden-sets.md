# Golden sets

!!! warning "Planned — Week 3"
    Not implemented yet.

## Planned workflow

```bash
kbguard golden generate --n 100 --out evals/golden.csv
# a human edits / approves rows in the CSV
kbguard golden freeze evals/golden.csv   # -> evals/golden.jsonl with stable ids
```

Questions are generated from sampled chunks by the judge LLM. Only rows marked `approved` in the CSV make it into the frozen `golden.jsonl` — `generate` never auto-approves anything, including during kbguard's own testing. The human review step is a deliberate v0.1 requirement, not an optional nicety.

Each row: `question`, `expected_chunk_ids`, optional `reference_answer`, `approved`.

This page will include a real worked example once `evals/golden.py` is built and tested.
