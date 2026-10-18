# Contributing

kbguard is in early, active development — see [Roadmap & status](roadmap.md) before picking up anything, since large parts of the design described elsewhere in this guide aren't implemented yet.

## Development setup

```bash
git clone https://github.com/devbyanoop/kbguard.git
cd kbguard
python -m venv .venv
source .venv/bin/activate   # or .venv/Scripts/activate on Windows (Git Bash)
pip install -e ".[dev,chroma]"
```

Add other extras as needed for what you're working on, e.g. `-e ".[dev,chroma,pgvector,qdrant]"` once those adapters exist.

## Running checks locally

```bash
pytest                                   # unit tests + contract tests
ruff check src tests                     # lint
mypy src/kbguard                         # strict type checking
```

All three must pass before a change is considered done — this project runs `mypy --strict`, so untyped function bodies and implicit `Any` are not allowed anywhere in `src/kbguard`.

## Docker-based tests

Some adapters (pgvector, Qdrant) are verified against real containers, not mocked clients — a mock would let a broken query pass. Start the fixtures with:

```bash
docker compose up -d
```

before running tests that touch those adapters, and `docker compose down` when done.

## Design rules that apply to every change

1. **Everything downstream of adapters works on `Chunk` records**, never on a database client directly — this is what keeps any vector store pluggable.
2. **Checks and metrics are plugins**, registered through Python entry points — no hardcoded `if adapter_name == "..."` branching outside `registry.py`.
3. **Snapshots are the unit of comparison** — checks, evals, and `diff` all read from a `SnapshotReader`, never from a live store connection directly.
4. **Cheap first, LLM last** — deterministic and embedding-based filtering must narrow candidates before any LLM call.
5. **Read-only, always** — kbguard must never write to a client's vector store. There should be no code path, in any adapter, that performs a write.

## Documentation

This guide (`docs/`) is written incrementally, alongside the code — a feature's documentation is written and verified the same day the feature itself is built and tested, not ahead of time. Pages for unbuilt features carry an explicit "Planned" warning with scope only, no invented usage examples. If you're adding a feature, update its doc page in the same change.

Preview the docs site locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```
