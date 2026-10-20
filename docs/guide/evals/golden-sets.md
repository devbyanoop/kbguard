# Golden sets

`evals/golden.py` (`generate`/`freeze`) is built and tested — the CLI commands (`kbguard golden generate`/`golden freeze`) land once `cli.py`'s eval-related wiring happens together (see [Roadmap & status](../../project/roadmap.md)).

## Workflow

```bash
kbguard golden generate --n 100 --out evals/golden.csv
# a human edits / approves rows in the CSV
kbguard golden freeze evals/golden.csv   # -> evals/golden.jsonl with stable ids
```

```python
from kbguard.evals.golden import generate, freeze

df = generate(snapshot_reader, n=100, judge=judge_client)
df.to_csv("evals/golden.csv", index=False)
# ... human reviews/approves rows in evals/golden.csv ...
freeze(Path("evals/golden.csv"), Path("evals/golden.jsonl"))
```

`generate` samples up to `n` chunks (deterministically — the same seed every call, so re-running against an unchanged snapshot samples the same chunks) and asks the judge to write one specific, answerable question per chunk — the first place the judge is used for *generation*, not yes/no classification like [Contradictions](../checks/contradictions.md). `approved` is always `false` in the output — `generate` never auto-approves anything, including during kbguard's own testing. The human review step is a deliberate v0.1 requirement, not an optional nicety.

Each review row: `question`, `expected_chunk_ids`, `reference_answer` (optional), `approved`. Only rows marked approved make it into the frozen `golden.jsonl`, each with an added stable `id` (`sha256(question)[:16]` — the same question text always gets the same id, so re-freezing the same CSV, or re-approving an identical question later, never shuffles ids).

## A real bug this caught before it shipped

The CSV is explicitly meant for a human to edit by hand. A reviewer leaving even one row's `approved` cell blank while working through the rest — completely normal — makes `pandas` infer that whole column as a mixed type (real booleans alongside `NaN` for the blank cell), and a naive `df[df["approved"]]` then raises `ValueError: Cannot mask with non-boolean array containing NA/NaN values`, confirmed by hand, not assumed. `freeze` parses each cell explicitly instead (`NaN`/blank → not approved; `"true"` case-insensitively, including real `True` values → approved), so a half-reviewed CSV never crashes it.

## Verified against the real example corpus

`generate(reader, n=5, judge=...)` against the 17-chunk example corpus produces 5 review rows; simulating a human approving 2 of them (leaving the other 3 blank, not explicitly `false`) and freezing produces exactly 2 `golden.jsonl` records — see `tests/test_evals_golden.py::test_against_real_example_corpus`.
