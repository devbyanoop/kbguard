# CLI reference

## Commands

| Command | Does | Status |
| --- | --- | --- |
| `kbguard scan` | Pulls a collection through its adapter, runs every enabled check, writes a snapshot + `results.json` + `report.html` | Done |
| `kbguard report` | Re-renders `results.json`/`report.html` from an existing snapshot's already-computed findings — no re-scan, no re-run of any check | Done |
| `kbguard golden generate` / `golden freeze` | Generates and freezes a golden Q&A set for retrieval/answer evals | Done |
| `kbguard eval` | Runs retrieval + answer metrics; gated by the judge calibration cache | Done |
| `kbguard calibrate` | Scores the judge against human labels, writes the calibration cache | Done |
| `kbguard diff` | Compares two snapshots, non-zero exit on regression | Done |

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

## `kbguard golden generate` / `golden freeze`

```bash
kbguard golden generate --collection <name> --n 100 --out evals/golden.csv [--snapshot <id>] [--config kbguard.yaml]
# review the CSV by hand, mark some rows approved
kbguard golden freeze evals/golden.csv --out evals/golden.jsonl
```

`generate` samples chunks from a snapshot (most recent, unless `--snapshot` is given) and asks the judge to write one candidate question per chunk — needs `judge:` configured. Nothing is approved automatically; `approved` is always `false` in the output CSV. `freeze` filters a reviewed CSV down to the rows you actually approved and assigns each a stable id.

## `kbguard calibrate`

```bash
kbguard calibrate [--labels evals/calibration.jsonl] [--config kbguard.yaml]
```

Scores a human-labeled calibration set with the judge, reports agreement and Cohen's kappa, and writes `.kbguard/calibration.json` — the file `kbguard eval` reads to decide whether to trust the judge for answer-quality metrics. See [Judge & calibration](../guide/evals/judge-and-calibration.md).

## `kbguard eval`

```bash
kbguard eval --collection <name> [--snapshot <id>] [--config kbguard.yaml]
```

Runs retrieval metrics (hit@k/recall@k/precision@k/MRR@k/nDCG@k) against `evals.golden` — always, no judge needed. If `evals.metrics` names any answer-quality metrics, also calls your `target:` for each golden question and scores the answer, gated by a passing calibration (see [Judge & calibration](../guide/evals/judge-and-calibration.md)). One broken question's target call is reported as a failed result, not a crash of the whole run. Merges everything into the snapshot's existing `results.json`/`report.html` — health and findings from the original `scan` are preserved untouched, since `eval` never re-runs any check.

## `kbguard diff`

```bash
kbguard diff --collection <name> --against <baseline-snapshot-id> [--snapshot <id>] [--ignore-file kbguard.ignore.yaml] [--config kbguard.yaml]
```

Compares two snapshots and exits non-zero when any `fail_on` rule triggers. See [Diff & CI](../guide/diff-and-ci.md) for the full picture, including suppressions.

## Output files, per snapshot

Every snapshot directory (`.kbguard/snapshots/<id>/`) ends up with:

| File | Written by | Contents |
| --- | --- | --- |
| `chunks.parquet`, `vectors.npy`, `index.sqlite` | `scan` | The raw scanned data — see `ingest/snapshot.py` |
| `manifest.json` | `scan` | Snapshot id, collection, adapter, chunk/finding counts, `iteration_mode` (`"full"` or `"sampled"`) |
| `findings.jsonl` | `scan` (checks), readable by `report` | Every finding every enabled check produced |
| `judge_cache.sqlite` | `scan`, if `judge:` is configured | Judge responses cached by request hash — see [Judge & calibration](../guide/evals/judge-and-calibration.md) |
| `results.json` | `scan`, `report`, and `eval` | `ScanResults`: snapshot metadata + health score + findings + eval results |
| `report.html` | `scan`, `report`, and `eval` | The human-readable report — three tabs: Summary (plain-language verdict + top issues), Engineering (findings grouped by check/severity, each enriched with source/snippet/suggested action), Trend (health over every past scan of this collection) |

One file lives *outside* any specific snapshot: `.kbguard/calibration.json`, written only by `calibrate` and read only by `eval` — not per-snapshot, since recalibrating is a deliberate, infrequent human action that should apply regardless of which snapshot you're evaluating next.
