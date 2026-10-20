# Diff & CI

`scoring/diff.py` (`diff_snapshots`) and `kbguard diff` are built and tested.

## Command

```bash
kbguard diff --collection <name> --against <baseline_snapshot> [--snapshot <new_snapshot>] [--ignore-file kbguard.ignore.yaml]
```

Omitting `--snapshot` compares against the most recent snapshot for the collection (lexical sort on snapshot ids, which are ISO-timestamp-prefixed — no timestamp parsing needed). The diff compares:

- **Health score delta** — recomputed independently for both snapshots via `summarize_findings`/`compute_health` (the same pure functions [health scoring](health-score.md) uses), not read from a stored value.
- **Findings by `fingerprint`** — new (in current, not baseline), resolved (in baseline, not current), unchanged (in both — excluded from both lists). Nothing fuzzier than a set difference, which is exactly what `Finding.fingerprint`'s stability across re-scans of unchanged content is for.
- **Eval metric deltas** — mean value per metric name, current minus baseline, read from each snapshot's `results.json` if present (empty if either snapshot has no eval results yet).

## Failing the build

```yaml
fail_on:
  health_drop: 3
  new_findings: {severity: error, max: 0}
  metric_drop: {recall@5: 0.02, faithfulness: 0.03}
```

Exit code is non-zero when any rule triggers — this is what lets a GitHub Action block a PR or a scheduled job that introduces a measurable regression. `new_findings.severity` is a *minimum* threshold (`error` is the most severe of the three levels today, but the comparison is ordering-based, not an exact match, so it stays correct if a severity is ever added between `warn` and `error`).

## Suppressions

```yaml
# kbguard.ignore.yaml
<fingerprint>:
  reason: "known, accepted — legacy doc duplicated intentionally"
```

A flat mapping keyed by fingerprint (`load_suppressions()` only reads the keys — the value is free-form, for your own team's record-keeping). A suppressed fingerprint is excluded from the `new_findings` **count** that decides pass/fail, but it still appears in the diff's `new_findings` list, explicitly marked in `suppressed_fingerprints` — you should always be able to see what's been accepted, never have it silently vanish.

## Verified

Two hand-constructed snapshots with a known new `error` finding: `fail_on.new_findings.max: 0` returns exit code 1; suppressing that exact fingerprint in a fixture `kbguard.ignore.yaml` flips it back to 0 while the finding still shows up in the diff output, confirmed via a real CLI invocation (`tests/test_cli_evals.py::test_diff_fails_on_a_new_error_finding_and_suppression_file_clears_it`), not just a unit test of `diff_snapshots` in isolation.

## CI

kbguard's own CI (`.github/workflows/kbguard.yml`) is a different workflow from the one a client runs — it tests kbguard's own source against real pgvector/Qdrant/Chroma service containers. The thing you'd actually copy is the client template:

```yaml
# examples/ci/kbguard-client-template.yml — copy to .github/workflows/ IN YOUR OWN REPO
name: kb-quality
on:
  workflow_dispatch:
  schedule: [{cron: "0 2 * * 1"}]
jobs:
  kbguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install "kbguard[qdrant,ragas]"
      - run: kbguard scan --collection policies
      - run: kbguard eval --collection policies
      - run: kbguard diff --collection policies --against <baseline-snapshot-id>
      - uses: actions/upload-artifact@v4
        if: always()
        with: {name: kbguard-report, path: .kbguard/snapshots/*/report.html}
```

The template is deliberately marked with `TODO`s for the one thing it can't know for you: which extras your store/judge/metrics need, and how you want to carry a baseline snapshot id between runs (an artifact or cache, since GitHub Actions runners don't persist `.kbguard/` between jobs on their own).
