# Quickstart

This walks through a real `kbguard scan`, using the bundled example corpus (`examples/policy_corpus/`) so you don't need a vector database of your own yet. Every command below was run for real against this repo before being written here.

## 1. Install

Follow [Installation](installation.md) first (`pip install -e ".[dev,chroma]"` from a cloned checkout — kbguard isn't on PyPI yet).

## 2. Seed the example corpus

```bash
python examples/policy_corpus/seed.py
```

This writes a small, local Chroma collection (`examples/policy_corpus/chroma_data/`, gitignored) with 17 chunks — a synthetic company-policy knowledge base with deliberately planted problems (duplicates, a stale policy version, a cut table, a contradicting number, ...). See `examples/policy_corpus/README.md` for exactly what's in it. Re-running `seed.py` is safe — it's a no-op once the collection is already populated.

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
Wrote snapshot '2026-10-20T06-47-31_demo': 17 chunks -> .kbguard\snapshots\2026-10-20T06-47-31_demo (report.html, results.json)
```

(Your snapshot id will have today's actual timestamp.) This now also runs every enabled check (`duplicates`, `stale_versions`, `chunking_damage` — `contradictions` stays off by default since it needs a configured judge, see [Contradictions](../guide/checks/contradictions.md)), computes a health score, and writes `results.json` + `report.html` into the same snapshot directory under `.kbguard/snapshots/<id>/` — gitignored, since it contains your actual document text (see [Configuration](../guide/configuration.md)).

## 5. Open the report

```bash
# Windows
start .kbguard\snapshots\<your-snapshot-id>\report.html
# macOS
open .kbguard/snapshots/<your-snapshot-id>/report.html
```

You should see a health score of **86** and 10 findings grouped by check: 2 duplicate pairs, 1 stale-version pair, and 7 chunking-damage findings across the corpus's 6 planted rule violations. Re-render the same report without re-scanning at any point:

```bash
kbguard report <your-snapshot-id> --config examples/policy_corpus/kbguard.yaml
```

You can also read the snapshot directly:

```python
from pathlib import Path
from kbguard.ingest.snapshot import SnapshotReader

reader = SnapshotReader(Path(".kbguard/snapshots/<your-snapshot-id>"))

for chunk in reader.chunks():
    print(chunk.id, chunk.source, repr(chunk.text[:60]))

print(reader.manifest())
```

You should see all 17 chunks, with `source` filled in from each chunk's `doc_id` via `metadata_map` — except `no-source-chunk`, where `source` is `None`, since that chunk has no `doc_id` at all (deliberately — see the corpus README).

## What's next

- Enable `contradictions` (set `judge.model` and `checks.contradictions.enabled: true`) to see the corpus's one genuine cross-document contradiction (`warranty-a` vs. `warranty-b`) show up too.
- Try evals, retrieval metrics, judge calibration, and `kbguard diff` for CI gating — see [Golden sets](../guide/evals/golden-sets.md) and [Diff & CI](../guide/diff-and-ci.md).
- Track real progress on [Roadmap & status](../project/roadmap.md).
