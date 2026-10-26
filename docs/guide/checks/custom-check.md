# Writing a custom check

Both pieces below are real and tested: implementing the `Check` Protocol, and registering it as a plugin. The worked example was run for real against the bundled example corpus before being written here.

## 1. Implement the Protocol

A check needs `name`, `default_severity`, and a `run(snapshot, ctx) -> Iterator[Finding]` method (see [Overview](overview.md)):

```python
# kbguard_banned_phrases/check.py
from collections.abc import Iterator
from dataclasses import dataclass, field

from kbguard.checks.base import CheckContext
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Finding, compute_fingerprint


@dataclass
class BannedPhrasesConfig:
    enabled: bool = False
    phrases: list[str] = field(default_factory=list)


class BannedPhrasesCheck:
    name = "banned_phrases"
    default_severity = "warn"

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]:
        config: BannedPhrasesConfig = ctx.config  # your check's own resolved config
        for chunk in snapshot.chunks():
            for phrase in config.phrases:
                if phrase.lower() in chunk.text.lower():
                    yield Finding(
                        check=self.name,
                        severity=self.default_severity,
                        chunk_ids=[chunk.id],
                        message=f"Chunk contains banned phrase {phrase!r}",
                        evidence={"phrase": phrase},
                        fingerprint=compute_fingerprint(self.name, [chunk.id], identity_keys=[phrase]),
                    )
```

A few things every check must get right, not just this example:

- **Read from the snapshot, never from a live store connection.** `snapshot.chunks()` yields every `Chunk` already written by `kbguard scan` — a check runs against a point-in-time snapshot, not a live query (`stale_versions`' self-retrieval probe is the one documented exception, via `ctx.adapter`/`ctx.collection` — see [Stale versions](stale-versions.md)).
- **Compute a stable `fingerprint` via `compute_fingerprint(check_name, chunk_ids, identity_keys=[...])`.** This is what `diff` and `kbguard.ignore.yaml` suppressions key off of — get it wrong (e.g. omit an `identity_keys` entry that actually varies between findings) and two genuinely different findings collapse into one fingerprint, or a stable finding looks "new" on every rescan.
- **`ctx.config` is typed `Any` on purpose** — `CheckContext` is shared infrastructure that doesn't know which check it's for. Your check casts it to its own config type (`BannedPhrasesConfig` above), the same way `DuplicatesCheck`/`StaleVersionsCheck`/etc. each cast to their own.

Run it directly against a real snapshot to confirm it works before registering it as a plugin:

```python
from pathlib import Path
from kbguard.checks.base import CheckContext
from kbguard.ingest.snapshot import SnapshotReader

reader = SnapshotReader(Path(".kbguard/snapshots/<your-snapshot-id>"))
config = BannedPhrasesConfig(enabled=True, phrases=["lorem ipsum"])
findings = list(BannedPhrasesCheck().run(reader, CheckContext(config=config)))
```

## 2. Register it

In *your own* package's `pyproject.toml` — no changes to kbguard's own source:

```toml
[project.entry-points."kbguard.checks"]
banned_phrases = "kbguard_banned_phrases.check:BannedPhrasesCheck"
```

`kbguard.registry.load_check("banned_phrases")` discovers it at runtime via `importlib.metadata` entry points — the exact same mechanism [custom adapters](../adapters/custom-adapter.md) use, and the one kbguard's own four built-in checks (`duplicates`, `stale_versions`, `chunking_damage`, `contradictions`) are registered through too; nothing about being "built-in" gets special treatment.

## Needing the judge or a live adapter

Two optional `CheckContext` fields exist for checks that need more than the snapshot alone:

- `ctx.judge` (typed as the structural `JudgeLike` Protocol, not the concrete `JudgeClient`) — set only when a judge is configured. `contradictions.py` is the one built-in check that uses this, to confirm a candidate fact conflict rather than report every syntactic mismatch as a finding.
- `ctx.adapter` / `ctx.collection` — set when a check needs to query the *live* store directly, not just read the snapshot. `stale_versions.py` uses this for its self-retrieval escalation probe (query the live store with a stale chunk's own embedding; if the current version also comes back in the top-k results, escalate the finding's severity).

Both are `None` unless your check actually needs them — check for `None` explicitly rather than assuming they're set, the same way `stale_versions.py` and `contradictions.py` themselves do.
