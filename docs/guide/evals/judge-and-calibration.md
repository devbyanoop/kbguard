# Judge & calibration

!!! warning "Planned — Week 2 (judge/client.py) and Week 3 (judge/calibrate.py)"
    Not implemented yet.

## Why calibration exists

kbguard uses an LLM as a judge in a few places (confirming contradictions, scoring some answer metrics). Trusting a judge's yes/no call without checking its actual accuracy would be exactly the kind of unverified-automation mistake kbguard exists to catch in *your* system — so the judge doesn't get a pass either.

## Planned behavior

- **One `JudgeClient`**, model pinned in `kbguard.yaml` — local models (via Ollama) are explicitly supported for teams that can't send document text to a third-party API.
- **JSON-only outputs**, with exactly one retry on a malformed response — not a silent fallback to `None`, which would hide a persistently broken judge.
- **Every call is cached** by a hash of the request inside the snapshot, so re-scanning unchanged data costs zero new LLM calls.
- **Calibration:** `kbguard calibrate` scores `evals/calibration.jsonl` (20–50 human-labeled examples) and reports agreement and **Cohen's kappa** (agreement corrected for chance — plain percent-agreement overstates reliability when one answer is common). The result is cached to `.kbguard/calibration.json` with the judge model id and a timestamp.
- **The gate:** `kbguard eval` reads that cache and refuses to proceed (non-zero exit, clear error message) if agreement is below `min_agreement`, or if the cache is missing or was written against a different judge model than the one currently pinned.

This page will include real calibration numbers from a worked example once `judge/client.py` and `judge/calibrate.py` are built and tested.
