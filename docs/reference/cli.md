# CLI reference

## Commands

| Command | Does | Status |
| --- | --- | --- |
| `kbguard scan` | Pulls a collection through its adapter, runs every enabled check, writes a snapshot + `results.json` + `report.html` | Done |
| `kbguard report` | Re-renders `results.json`/`report.html` from an existing snapshot's already-computed findings — no re-scan, no re-run of any check | Done |
| `kbguard golden generate` / `golden freeze` | Generates and freezes a golden Q&A set for retrieval/answer evals | Planned — Week 3 |
| `kbguard eval` | Runs retrieval + answer metrics; gated by the judge calibration cache | Planned — Week 3 |
| `kbguard calibrate` | Scores the judge against human labels, writes the calibration cache | Planned — Week 3 |
| `kbguard diff` | Compares two snapshots, non-zero exit on regression | Planned — Week 3 |

See [Roadmap & status](../project/roadmap.md) for current build state.

## `kbguard scan`

```bash
kbguard scan --collection <name> [--config kbguard.yaml]
```

Connects to the configured adapter, pulls every chunk, writes a new snapshot at `.kbguard/snapshots/<timestamp>_<collection>/`, then runs every check whose `checks.<name>.enabled` is `true` against that snapshot, computes the health score, and writes `results.json` + `report.html` into the same snapshot directory. A real run against the bundled example corpus:

```text
Wrote snapshot '2026-10-20T06-47-31_demo': 17 chunks -> .kbguard\snapshots\2026-10-20T06-47-31_demo (report.html, results.json)
```

Checks run in a fixed order (`duplicates`, `stale_versions`, `chunking_damage`, `contradictions`) — the only four wired into this command today. A third-party check registered via the same `kbguard.checks` entry-point group still works when invoked directly through `registry.load_check`, it just isn't automatically included in `scan`'s pipeline yet (a real, documented v0.1 scope limit).

## `kbguard report`

```bash
kbguard report <snapshot-id> [--config kbguard.yaml]
```

Regenerates `results.json`/`report.html` from a snapshot's **already-computed** findings — it never connects to the adapter and never constructs a judge, confirmed by a test that fails if either is touched. The `--config` flag is read only for `health:` weights, so you can re-render the same snapshot's report under different weight assumptions without re-scanning or re-paying for any judge call.

## Output files, per snapshot

Every snapshot directory (`.kbguard/snapshots/<id>/`) ends up with:

| File | Written by | Contents |
| --- | --- | --- |
| `chunks.parquet`, `vectors.npy`, `index.sqlite` | `scan` | The raw scanned data — see `ingest/snapshot.py` |
| `manifest.json` | `scan` | Snapshot id, collection, adapter, chunk/finding counts, `iteration_mode` (`"full"` or `"sampled"`) |
| `findings.jsonl` | `scan` (checks), readable by `report` | Every finding every enabled check produced |
| `judge_cache.sqlite` | `scan`, if `judge:` is configured | Judge responses cached by request hash — see [Judge & calibration](../guide/evals/judge-and-calibration.md) |
| `results.json` | `scan` and `report` | `ScanResults`: snapshot metadata + health score + findings (+ eval results from Week 3) |
| `report.html` | `scan` and `report` | The human-readable report — health score, findings grouped by check and severity |
