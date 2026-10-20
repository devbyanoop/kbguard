# Configuration

kbguard reads a single `kbguard.yaml`, validated into a typed `KBGuardConfig` object by `config.py` (pydantic). Unknown fields are rejected with a clear error — a typo like `cosin:` instead of `cosine:` fails loudly at load time rather than silently doing nothing.

## Minimal config

Everything below `store` is optional and defaults sensibly — this is a complete, valid `kbguard.yaml` today:

```yaml
store:
  adapter: chroma
  collection: policies
```

`judge`, `evals`, and `target` are only needed once you use features that depend on them — `checks.contradictions` and the answer-quality metrics (`judge`), `kbguard eval`/`golden generate`/`calibrate` (`evals`), and answer-quality metrics specifically (`target`). All three are fully implemented; `checks.contradictions` defaults to disabled specifically so a judge is never forced on you by default.

## Full example

```yaml
store:
  adapter: qdrant
  settings: {url: http://localhost:6333, api_key_env: QDRANT_API_KEY}
  collection: policies
  text_field: text           # for stores keeping text in metadata

metadata_map:
  source: doc_id
  version: meta.version
  updated_at: meta.last_modified

embeddings:
  reuse_stored: true
  provider: sentence-transformers   # or litellm
  model: sentence-transformers/all-MiniLM-L6-v2

checks:
  duplicates: {cosine: 0.97, minhash_jaccard: 0.3}
  stale_versions: {enabled: true}
  chunking_damage: {min_tokens: 40, max_tokens: 800, required_metadata: [source]}
  contradictions: {enabled: true, types: [number, date, money, percent, duration]}

health:
  duplicates: 0.15
  stale_versions: 0.30
  chunking_damage: 0.20
  contradictions: 0.35

judge:
  model: ollama/llama3
  calibration_set: evals/calibration.jsonl
  min_agreement: 0.8

evals:
  golden: evals/golden.jsonl
  k: [1, 3, 5]
  metrics: [ragas.faithfulness, ragas.answer_relevancy]

target:
  type: python
  callable: my_app.rag:answer

fail_on:
  health_drop: 3
```

!!! note "Every section on this page is real"
    `checks.*`, `health:`, `judge:`, `evals:`, `target:`, and `fail_on:` are all read by real, tested code today — `kbguard scan` runs every enabled check and writes a report, `kbguard eval` runs retrieval and (if configured) answer-quality metrics, `kbguard diff` applies `fail_on` rules for CI gating. `judge:` is needed only if `checks.contradictions.enabled` is `true` (it defaults to `false` for exactly this reason) or if `evals.metrics` names any answer-quality metric. See [Roadmap & status](../project/roadmap.md) for exactly what each piece is tested against.

## Reference

### `store` (required)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `adapter` | string | — | Required. The registered adapter name (e.g. `chroma`, `qdrant`). |
| `settings` | mapping | `{}` | Adapter-specific — connection URL, credentials, etc. Not validated here; each adapter validates its own settings. |
| `collection` | string | — | Required. |
| `text_field` | string \| null | `null` | For stores that keep chunk text inside metadata rather than a dedicated field. |

### `metadata_map`

A mapping from kbguard's standard `Chunk` fields (`source`, `version`, `updated_at`, ...) to your store's actual field names, supporting dotted paths into nested metadata (e.g. `meta.last_modified`). Defaults to `{}` (no mapping — standard fields stay `null`).

### `embeddings`

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `reuse_stored` | bool | `true` | Use the vector already stored in your vector DB when present; only falls back to recomputing for chunks that lack one. |
| `provider` | `"sentence-transformers"` \| `"litellm"` | `sentence-transformers` | Explicit, not guessed from `model`'s name — see below. |
| `model` | string | `sentence-transformers/all-MiniLM-L6-v2` | Interpreted according to `provider`. |

`provider` is deliberately explicit rather than inferred from `model` (e.g. by checking for a `"sentence-transformers/"` prefix) — plenty of valid local HuggingFace models (`BAAI/bge-small-en-v1.5`, `intfloat/e5-small-v2`, ...) don't carry that prefix, and guessing wrong here has a real cost: `litellm` routes to a hosted API, so misrouting a model that was meant to stay local means document text leaves your machine. `sentence-transformers` is the default specifically because it runs fully locally — matching this project's "runs entirely in your environment" principle by default, not just as an option.

### `checks`

Each of `duplicates`, `stale_versions`, `chunking_damage` has `enabled: bool = true`; `contradictions` has `enabled: bool = false` (see [Contradictions](checks/contradictions.md) for why it's the one exception) — plus a `severity` override and check-specific tuning fields (shown in the full example above) on all four. Defaults mostly follow the original architecture spec, with one correction made after measuring against real data: `duplicates.minhash_jaccard` is `0.3`, not the spec's original `0.9` — see [Duplicates](checks/duplicates.md) for why. `chunking_damage.required_metadata` defaults to `[]` (flags nothing) until you list the fields you actually require; see [Chunking damage](checks/chunking-damage.md) for why its example-corpus config overrides `min_tokens` to `10`.

### `health` (optional)

| Field | Type | Default |
| --- | --- | --- |
| `duplicates` | float | `0.15` |
| `stale_versions` | float | `0.30` |
| `chunking_damage` | float | `0.20` |
| `contradictions` | float | `0.35` |

Weights for the [health score](../guide/health-score.md) formula. Don't need to sum to 1 — `compute_health` clamps the result to `[0, 100]` regardless.

### `judge` (optional)

| Field | Type | Default |
| --- | --- | --- |
| `model` | string | — (required if `judge` is given at all) |
| `calibration_set` | path \| null | `null` |
| `min_agreement` | float | `0.8` |

### `evals` (optional)

| Field | Type | Default |
| --- | --- | --- |
| `golden` | path | — (required if `evals` is given at all) |
| `k` | list of int | `[1, 3, 5]` |
| `metrics` | list of string | `[]` |

### `target` (optional)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `type` | `"python"` \| `"http"` | — | Required. |
| `callable` | string \| null | `null` | Required when `type: python` (validated — omitting it is a config error, not a runtime surprise). |
| `url` | string \| null | `null` | Required when `type: http`. |
| `method` | string | `POST` | |
| `answer_path` | string | `$.answer` | |
| `contexts_path` | string | `$.contexts` | |
| `timeout` | float | `30.0` | HTTP only — a plain Python callable has no cross-platform-safe timeout without extra threading complexity, a deliberate v0.1 limit. |

### `fail_on` (optional)

| Field | Type | Default |
| --- | --- | --- |
| `health_drop` | int \| null | `null` |
| `new_findings` | `{severity, max}` \| null | `null` |
| `metric_drop` | mapping of metric → float | `{}` |

## Secrets

Secrets are never written into `kbguard.yaml` directly. A field like `api_key_env` holds the **name** of an environment variable, not the value:

```yaml
store:
  settings: {api_key_env: QDRANT_API_KEY}
```

The actual value is read from the environment only at the point a connection is actually attempted — not while the config file is being loaded and validated. This means a command that doesn't need that credential (e.g. `kbguard report` on an existing snapshot) never fails over a secret it was never going to use.
