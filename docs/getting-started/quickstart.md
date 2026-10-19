# Quickstart

This walks through a real `kbguard scan`, using the bundled example corpus (`examples/policy_corpus/`) so you don't need a vector database of your own yet. Every command below was run for real against this repo before being written here.

!!! note "No report yet"
    `kbguard scan` writes a snapshot — the raw scanned data — but nothing reads it back into an HTML report yet. Checks, the health score, and `kbguard report` are Week 2. This page will grow to include opening a report once that exists; for now, the quickstart ends at inspecting the snapshot directly.

## 1. Install

Follow [Installation](installation.md) first (`pip install -e ".[dev,chroma]"` from a cloned checkout — kbguard isn't on PyPI yet).

## 2. Seed the example corpus

```bash
python examples/policy_corpus/seed.py
```

This writes a small, local Chroma collection (`examples/policy_corpus/chroma_data/`, gitignored) with 16 chunks — a synthetic company-policy knowledge base with deliberately planted problems (duplicates, a stale policy version, a cut table, a contradicting number, ...). See `examples/policy_corpus/README.md` for exactly what's in it. Re-running `seed.py` is safe — it's a no-op once the collection is already populated.

## 3. Point kbguard at it

A `kbguard.yaml` is already provided at `examples/policy_corpus/kbguard.yaml`:

```yaml
store:
  adapter: chroma
  collection: demo
  settings:
    path: examples/policy_corpus/chroma_data

metadata_map:
  source: doc_id
  title: title
  version: version
  updated_at: updated_at
```

## 4. Scan

```bash
kbguard scan --collection demo --config examples/policy_corpus/kbguard.yaml
```

```text
Wrote snapshot '2026-10-19T04-18-42_demo': 16 chunks -> .kbguard\snapshots\2026-10-19T04-18-42_demo
```

(Your snapshot id will have today's actual timestamp.) The output lands under `.kbguard/snapshots/<id>/` relative to wherever you ran the command — gitignored, since it contains your actual document text (see [Configuration](../guide/configuration.md)).

## 5. Inspect the snapshot

There's no `kbguard report` yet (Week 2), but you can read a snapshot directly with `SnapshotReader`:

```python
from pathlib import Path
from kbguard.ingest.snapshot import SnapshotReader

reader = SnapshotReader(Path(".kbguard/snapshots/<your-snapshot-id>"))

for chunk in reader.chunks():
    print(chunk.id, chunk.source, repr(chunk.text[:60]))

print(reader.manifest())
```

You should see all 16 chunks, with `source` filled in from each chunk's `doc_id` via `metadata_map` — except `no-source-chunk`, where `source` is `None`, since that chunk has no `doc_id` at all (deliberately — see the corpus README).

## What's next

- **Week 2** adds the knowledge-base checks (`duplicates`, `stale_versions`, `chunking_damage`, `contradictions`), a health score, and `kbguard report` — at which point this corpus's planted problems should all show up as findings.
- Track real progress on [Roadmap & status](../project/roadmap.md).
