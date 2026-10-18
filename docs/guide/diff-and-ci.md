# Diff & CI

!!! warning "Planned — Week 3 (scoring/diff.py)"
    Not implemented yet.

## Planned command

```bash
kbguard diff --against <baseline_snapshot> [--snapshot <new_snapshot>]
```

Omitting `--snapshot` compares against the most recent snapshot for the collection. The diff compares: the health score delta, each check's finding counts, findings by `fingerprint` (new / resolved / unchanged), and eval metric deltas per question.

## Failing the build

```yaml
fail_on:
  health_drop: 3
  new_findings: {severity: error, max: 0}
  metric_drop: {recall@5: 0.02, faithfulness: 0.03}
```

Exit code is non-zero when any rule triggers — this is what lets a GitHub Action block a PR or a scheduled job that introduces a measurable regression.

## Suppressions

A `kbguard.ignore.yaml` file, keyed by `fingerprint`, lets a team accept a known finding without it counting toward `fail_on.new_findings` — but a suppressed finding still shows up in the diff output labeled as suppressed, rather than silently disappearing. You should always be able to see what's been accepted, not just what's currently failing.

## CI example (planned)

```yaml
# .github/workflows/kbguard.yml
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
      - run: kbguard eval
      - run: kbguard diff --against baseline
      - uses: actions/upload-artifact@v4
        if: always()
        with: {name: kbguard-report, path: .kbguard/reports/}
```

This page will include a real worked example — an intentionally damaged chunk showing up as a failing diff — once `scoring/diff.py` is built and tested.
