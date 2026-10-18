# FAQ

This page grows as real questions come in. It starts with a few that are already answerable from design decisions made so far.

## Will kbguard ever write to my vector store?

No. Read-only is a hard design constraint, not a default that could change later — there's no code path, in any adapter, that performs a write. If you ever see a feature request that would require a write, it belongs in a separate tool, not kbguard.

## Does my document text ever leave my environment?

By default, no. kbguard runs entirely inside your own infrastructure. The one place that calls an external service is the judge LLM (used for contradiction confirmation and some answer metrics) — and that's pinned to a specific model in your config, with local models via Ollama explicitly supported for teams that can't send document text to a third-party API at all.

## Why "Protocol" instead of a base class for adapters and checks?

A `Protocol` (structural typing) means a third-party adapter or check never needs to import anything from kbguard's own code to satisfy the contract — it just needs to have the right methods. That keeps the coupling one-directional: kbguard depends on the shape of a plugin, a plugin never depends on kbguard's internals.

## Why does the contradictions check only look at numbers and dates in v0.1?

To keep the false-positive rate manageable while the design is still new. Open-ended claim contradiction (two sentences disagreeing in a way that isn't a clean numeric/date mismatch) is a much harder, fuzzier problem — it's deliberately deferred rather than shipped half-working.

## Something's missing from this FAQ

Open an issue, or see [Contributing](contributing.md).
