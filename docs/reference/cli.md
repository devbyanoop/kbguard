# CLI reference

!!! warning "Planned — commands land across Weeks 1-3"
    `kbguard` has no commands implemented yet. This page will be filled in, command by command, the same day each one is built and verified — never written ahead of the real implementation, so every example here is guaranteed runnable.

## Planned commands

| Command | Does | Status |
| --- | --- | --- |
| `kbguard scan` | Pulls a collection through its adapter, runs KB checks, writes a snapshot + findings | Planned — Week 1/2 |
| `kbguard golden generate` / `golden freeze` | Generates and freezes a golden Q&A set for retrieval/answer evals | Planned — Week 3 |
| `kbguard eval` | Runs retrieval + answer metrics; gated by the judge calibration cache | Planned — Week 3 |
| `kbguard calibrate` | Scores the judge against human labels, writes the calibration cache | Planned — Week 3 |
| `kbguard diff` | Compares two snapshots, non-zero exit on regression | Planned — Week 3 |
| `kbguard report` | Re-renders the HTML/JSON report from an existing snapshot, no re-scan | Planned — Week 2 |

See [Roadmap & status](../project/roadmap.md) for current build state.
