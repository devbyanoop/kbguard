# Writing a custom check

!!! warning "Planned — depends on checks/base.py (Week 2)"
    Not buildable yet. This page describes the planned mechanism.

## Planned mechanism

A new check needs one file implementing the `Check` Protocol (see [Overview](overview.md)) and one entry point in your own package's `pyproject.toml` — same discovery mechanism as adapters, no changes to kbguard's own source required.

Inside `run()`, a check reads from the `SnapshotReader` it's given — never from a live vector store connection — and yields `Finding`s, computing each one's `fingerprint` via `compute_fingerprint(check_name, chunk_ids, identity_keys=[...])` so `diff` and suppressions work correctly against it.

This page will include a full worked example once the mechanism is real and tested.
