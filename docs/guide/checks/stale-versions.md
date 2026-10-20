# Stale versions check

Implemented and verified against the real example corpus — the planted old/new policy pair is found, with severity correctly escalated by a real self-retrieval probe against the live store.

## How it works

1. **Group into document families**: by `title` when present (the reliable signal), falling back to a normalized `source`/filename stem (strips one trailing version-ish marker — `_v2`, `-final`, `2025` — so `"refund-policy-2024"` and `"refund-policy-2025"` group together). This is a heuristic, not a parser, and is expected to occasionally misfire on unusual naming — exactly what `kbguard.ignore.yaml` suppressions (planned) exist to handle.
2. **Order within a family**: by `updated_at` when present (the reliable signal); falls back to comparing `version` as a plain string when it isn't (best-effort — `"v10"` sorting before `"v9"` lexically isn't handled). A member with **neither** signal is excluded from ordering entirely — kbguard doesn't guess which is older without evidence.
3. **Flag every member except the newest** as potentially stale.
4. **Self-retrieval probe**: for each stale member, query the *live* store (not the snapshot) with that chunk's own embedding — the best available stand-in for "a real query whose topic matches this content" — and check whether both the stale and current versions come back in the top 5 results. If they do, severity escalates to `error` regardless of configured base severity, since that means a real user query could plausibly retrieve the outdated version. Without a live adapter connection, the check still reports stale members, just without this escalation.

## Example finding

Run against `examples/policy_corpus/` (`return-window-v1`, "Returns within 14 days", superseded by `return-window-v2`, "Returns within 30 days" — same `title`, different `version`/`updated_at`):

```
error  ['return-window-v1', 'return-window-v2']  Chunk 'return-window-v1' appears superseded by 'return-window-v2' but is still in the collection
```

Escalated to `error` because a search using `return-window-v1`'s own embedding genuinely surfaces `return-window-v2` in its top 5 nearest neighbors on the live corpus — confirmed directly, not assumed.

## Configuration

```yaml
checks:
  stale_versions:
    enabled: true
    severity: warn
```

No tuning fields beyond `enabled`/`severity` yet — the self-retrieval probe's `k` (currently 5) isn't configurable; nothing has asked for it to be.
