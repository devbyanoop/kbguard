# Contradictions check

`ContradictionsCheck` (`contradictions` plugin name) finds two chunks that state conflicting numbers, dates, money amounts, percentages, or durations about the same thing — e.g. "warranty is 1 year" in one document and "warranty is 2 years" in another. It's the one check that uses an LLM, and the only one disabled by default, since it genuinely can't do anything without a configured judge.

## Pipeline

```text
All chunks → cluster by embedding similarity → extract facts + subject phrase
→ candidate pairs (same subject, different value, different source) → judge confirms → Finding
```

Each step narrows the field *before* any LLM call, so judge cost scales with the number of actual candidate conflicts, not with corpus size. Against the real example corpus (17 chunks), exactly **one** pair ever reaches the judge.

### 1. Cluster by embedding similarity

Chunks are grouped by cosine similarity ≥ 0.6 (union-find, same technique as [Duplicates](duplicates.md), much looser threshold — this is "roughly the same topic," not "near-duplicate"). Only clusters of 2+ chunks are examined further; a chunk with no topically-similar neighbor can't be compared to anything.

!!! note "0.6 isn't independently measured — it clears a real, measured gap"
    No broad corpus of real contradicting-fact pairs was available to calibrate this threshold the way `duplicates.minhash_jaccard` was measured. It's picked to clear a real gap in the one corpus available: the two genuine same-topic pairs sit at cosine 0.7071 and 0.6402; the highest *unrelated* pair sits at 0.5432 (verified by hand — see `examples/policy_corpus/seed.py`'s pairwise comment). 0.6 clears both with real margin. This is also a real v0.1 scaling limit, done with plain numpy, not an ANN index: brute-force O(n²) cosine, fine for a demo corpus, not for a huge one — revisit with faiss if that ever matters in practice.

### 2. Extract facts and a subject phrase

Five regex patterns run in a fixed priority order — money, percent, duration, date, then a catch-all bare number — each claiming its matched span so a more specific type's digits (e.g. the `14` inside `14 days`) never also become a separate `number` fact. This priority-consumption happens for *every* pattern regardless of which fact types are enabled in config, specifically so that disabling `duration` doesn't let its bare digit leak through and get reported as a `number` fact instead — a real bug caught by a test that assumed disabling a type meant "nothing extracted," which was wrong until this was fixed.

For each match, `spaCy`'s small English model (`en_core_web_sm`) finds the nearest meaningful noun phrase and uses its lemmatized head noun as the subject:

- If a noun chunk *contains* the match (e.g. "a 2-year **warranty**" contains "2-year") and its head noun sits outside the match itself, that's the subject — "warranty".
- Otherwise, the nearest noun chunk that doesn't overlap the match at all.
- The lemma, not the raw word, is used — "warranty" from "1 user" and "5 users" both resolve to "user", not "user" vs "users" failing to match.

Verified against this project's two real planted pairs before trusting the design: both members of each pair resolve to the *same* subject ("warranty" for the warranty pair, "delivery" for the return-window pair) — what matters is consistency across a pair, not that the chosen word is the most natural human label.

### 3. Candidate pairs

Within a cluster, facts are grouped by `(fact_type, subject)`. A pair is a candidate only if:

- the values genuinely differ, **and**
- both chunks have a known, *different* source.

Two chunks from the same source (e.g. two versions of one document) are excluded — that's [Stale versions](stale-versions.md)'s job, not this check's. This is exactly why the real example corpus's `return-window-v1`/`return-window-v2` pair (same `doc_id`, different `version`) never reaches the judge, even though it's same-subject and different-value — only `warranty-a`/`warranty-b` (genuinely different documents) does.

### 4. Judge confirmation

Each candidate goes to `JudgeClient.ask_json()` with both chunks' full text and the two conflicting values, asking `{"conflict": bool, "explanation": str}`. Only `conflict: true` produces a `Finding`, at the configured severity (`error` by default).

## Configuration

```yaml
judge:
  model: ollama/llama3   # required -- see below

checks:
  contradictions:
    enabled: true          # default: false
    types: [number, date, money, percent, duration]   # default: all five
    severity: error        # default
```

!!! warning "Disabled by default — and for a real reason, not an oversight"
    Every other check works standalone; this one can't, since every candidate must be judge-confirmed before being reported — reporting unconfirmed candidates would be far too noisy to be useful. So `enabled` defaults to `false`, matching this project's "judge-dependent features stay off until `judge:` is configured" principle. Setting `enabled: true` without a `judge:` section raises `ContradictionsCheckError` at scan time — a clear error, not a silent no-op and not a crash deep inside a check.

## Known limitations

- **Duration values aren't unit-converted.** `(1, "year")` and `(365, "day")` are never recognized as equal — a deliberate v0.1 simplification (leap years, "month" having no fixed day count add real complexity this corpus-driven build never needed to solve).
- **Date coverage is narrow**: ISO (`2026-06-01`) and `Month D, YYYY` only — no slash formats, no relative dates.
- **Clustering is brute-force**, not ANN-indexed — a real v0.1 scaling limit on a very large corpus, documented rather than hidden.

## Verified against the real example corpus

17 chunks, 1 candidate pair reaches the judge (`warranty-a`/`warranty-b`), confirmed by `tests/test_checks_contradictions.py::test_against_real_example_corpus`.
