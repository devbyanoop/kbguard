# Configuration

!!! warning "Planned — Week 1 (config.py)"
    This page will become the full `kbguard.yaml` reference once `config.py` is built and its validation behavior is verified by tests. What follows is the **planned** shape from the architecture spec — real, but not yet implemented or runtime-checked. Treat field names as likely-but-not-final until this warning is removed.

## Planned shape

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
  model: sentence-transformers/all-MiniLM-L6-v2

checks:
  duplicates: {cosine: 0.97, minhash_jaccard: 0.9}
  stale_versions: {enabled: true}
  chunking_damage: {min_tokens: 40, max_tokens: 800, required_metadata: [source]}
  contradictions: {types: [number, date, money, percent, duration]}

judge:
  model: <pinned model id>
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

## Secrets

Planned behavior: secrets (API keys, DB credentials) are always referenced by **environment variable name** in the YAML (e.g. `api_key_env: QDRANT_API_KEY`), never written into the file itself, and never stored in a snapshot. kbguard reads the named environment variable only at the moment it's needed — not at config-load time — so a missing secret doesn't block commands that don't need it.

## What will be documented here once verified

- Every top-level section, field by field, with type, default, and whether it's required.
- Exact validation error messages for common mistakes (wrong type, missing required field, unknown adapter name).
- How `metadata_map`'s dotted-path syntax works against nested metadata.
