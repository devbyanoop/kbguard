# Judge & calibration

!!! note "Judge, calibration, and the eval gate are all built"
    `JudgeClient`/`JudgeCache`, `judge/calibrate.py`, `kbguard calibrate`, and `kbguard eval`'s `min_agreement` gate are all implemented and tested.

## Why calibration exists

kbguard uses an LLM as a judge in a few places (confirming contradictions, scoring some answer metrics). Trusting a judge's yes/no call without checking its actual accuracy would be exactly the kind of unverified-automation mistake kbguard exists to catch in *your* system — so the judge doesn't get a pass either.

## `JudgeClient` (built)

One `JudgeClient` (`judge/client.py`), used by contradiction confirmation and answer metrics that accept a custom LLM:

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

## Calibration

```bash
kbguard calibrate --labels evals/calibration.jsonl
```

Each labeled row is deliberately generic — not tied to the contradictions check's own `{"conflict": bool, ...}` schema, since the judge contract is shared by contradiction confirmation and answer metrics alike:

```json
{"prompt": "...", "schema_hint": "...", "key": "conflict", "human_label": true}
```

`calibrate(labels_path, judge, out_path)` replays `judge.ask_json(prompt, schema_hint)` for every row, reads the decision out of whichever JSON key `"key"` names, and compares it against `human_label`. It reports:

- **Agreement** — the plain fraction where judge and human agree.
- **Cohen's kappa** — agreement corrected for chance, via `sklearn.metrics.cohen_kappa_score` (a library implementation, not hand-rolled — exactly the kind of statistic worth trusting to a library). Verified by hand: identical label lists score 1.0; a judge that disagrees with every human label scores 0.0.

Both are written to `.kbguard/calibration.json` with the judge's model id and a timestamp — `calibrate` is the only thing that writes this file; `eval` only ever reads it.

!!! note "Undefined kappa never becomes NaN"
    When every label (human and judge) happens to be identical, Cohen's kappa is mathematically undefined (the chance-agreement term hits 1.0, giving a 0/0). Confirmed by hand against `sklearn` directly: its default behavior returns `NaN`. `calibrate` passes `replace_undefined_by=0.0` explicitly, so a degenerate all-one-label calibration set reports 0.0 ("no measurable agreement beyond chance"), never a `NaN` silently flowing into `calibration.json`.

**The gate:** `kbguard eval` refuses to run any answer-quality metric (non-zero exit, clear error message) if `.kbguard/calibration.json` is missing, was written for a different judge model than the one currently pinned, or reports agreement below `judge.min_agreement`. Retrieval metrics never need this gate — only the answer-quality metrics that actually call the judge do.
