# Quickstart

!!! warning "Planned — Week 1"
    `kbguard scan` doesn't exist yet. This page is a placeholder for the real quickstart, which will walk through: pointing kbguard at a live collection via `kbguard.yaml`, running `kbguard scan --collection <name>`, and opening the resulting HTML report.

    It will be written and verified against a real scan the same day `cli.py`'s `scan` command lands — not before, so every command shown here is guaranteed to actually work as written.

## What this page will cover

1. A minimal `kbguard.yaml` for a single store (starting with Chroma, since it needs no server).
2. Running `kbguard scan --collection <name>`.
3. Where the output lands (`.kbguard/snapshots/<id>/`) and what's in it.
4. Opening `report.html` and reading a first health score.
5. A short note on what happens next (checks in Week 2, evals in Week 3).

Track progress on [Roadmap & status](../project/roadmap.md).
