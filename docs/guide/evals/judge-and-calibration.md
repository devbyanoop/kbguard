# Judge & calibration

!!! warning "judge/client.py is done; judge/calibrate.py is Planned — Week 3"
    `JudgeClient`/`JudgeCache` below are implemented and tested. Calibration (`kbguard calibrate`, `kbguard eval`'s `min_agreement` gate) is not built yet.

## Why calibration exists

kbguard uses an LLM as a judge in a few places (confirming contradictions, scoring some answer metrics). Trusting a judge's yes/no call without checking its actual accuracy would be exactly the kind of unverified-automation mistake kbguard exists to catch in *your* system — so the judge doesn't get a pass either.

## `JudgeClient` (built)

One `JudgeClient` (`judge/client.py`), used by contradiction confirmation and (Week 3) answer metrics that accept a custom LLM:

```python
class JudgeClient:
    def __init__(self, model: str, cache: JudgeCache) -> None: ...
    def ask_json(self, prompt: str, schema_hint: str) -> dict: ...
```

- **Provider-neutral** via `litellm`'s model-string routing — `gpt-4o-mini`, `anthropic/claude-3-5-sonnet-...`, or a local `ollama/llama3` all use the same call shape. `litellm` is only imported on an actual call (not at import time), so constructing a `JudgeClient` — or hitting its cache on a repeat request — never requires the `litellm` extra to be installed.
- **JSON-only outputs**, requested via `response_format={"type": "json_object"}` (confirmed to be a parameter litellm maps for Ollama models too, not just hosted APIs — so this works the same way locally). litellm doesn't itself enforce valid JSON when a provider ignores the hint, so `ask_json` still parses and validates the response itself regardless.
- **Exactly one retry** on a malformed response (2 attempts total) — not a silent fallback to `None`. A judge that's still returning non-JSON after the retry raises `JudgeError`, so a persistently broken judge surfaces as a clear error rather than a `None` propagating confusingly downstream.
- **Cached by request hash** (`sha256` of model + prompt + schema hint) in a `JudgeCache`, a small sqlite file living inside one snapshot's own directory.

!!! note "The cache is scoped to one snapshot, not across separate scans"
    Each `kbguard scan` run writes a new, differently-named snapshot directory (see `cli.py`) — so a second scan always starts with a cold judge cache; it does **not** make re-scanning unchanged data free of new LLM calls. What it does buy: running checks, `report`, or `diff` more than once against the *same* already-written snapshot never re-pays for a judge call it already made — e.g. iterating on a report template, or re-running `contradictions` after tuning an unrelated threshold, costs zero additional judge calls. This is narrower than the architecture spec's section 10 wording ("cached ... in the snapshot") might suggest at a glance, and is called out explicitly here rather than left implied.

## Calibration (planned — Week 3)

- `kbguard calibrate` scores `evals/calibration.jsonl` (20–50 human-labeled examples) and reports agreement and **Cohen's kappa** (agreement corrected for chance — plain percent-agreement overstates reliability when one answer is common). The result is cached to `.kbguard/calibration.json` with the judge model id and a timestamp.
- **The gate:** `kbguard eval` reads that cache and refuses to proceed (non-zero exit, clear error message) if agreement is below `min_agreement`, or if the cache is missing or was written against a different judge model than the one currently pinned.

This page will include real calibration numbers from a worked example once `judge/calibrate.py` is built and tested.
