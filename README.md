# kbguard

**Knowledge-base QA and evals for RAG systems — across any vector database.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![CI](https://github.com/devbyanoop/kbguard/actions/workflows/kbguard.yml/badge.svg)](https://github.com/devbyanoop/kbguard/actions/workflows/kbguard.yml)
[![Status: v0.1 complete](https://img.shields.io/badge/status-v0.1%20complete-brightgreen.svg)](docs/project/roadmap.md)

## The problem

A RAG (retrieval-augmented generation) system — a support chatbot, an internal knowledge assistant, a "chat with your docs" feature — is only as good as the knowledge base it retrieves from. Two things go wrong in every real deployment, and almost nobody tests for either:

1. **The knowledge base rots silently.** A policy doc gets updated but the old version is still sitting in the vector store. Two documents state contradictory facts (a 1-year vs. a 2-year warranty). A PDF got chunked mid-sentence or mid-table. None of this throws an error — it just means the bot occasionally gives a wrong or contradictory answer, and nobody notices until a customer does.
2. **Nobody can tell *why* an answer was wrong.** Did retrieval fail to surface the right chunk? Did the right chunk get surfaced but the model ignored it? Or was the underlying content wrong to begin with? Without that distinction, "the bot gave a bad answer" is undebuggable.

kbguard is built around closing both gaps: a set of deterministic and LLM-assisted checks that find knowledge-base rot before a user hits it, plus retrieval/answer-quality evals that trace a bad answer back to a specific cause — content, retrieval, or generation — instead of leaving you to guess.

## What it does

- **`kbguard scan`** — pulls every chunk from your real vector store and runs four checks against it:
  - **`duplicates`** — exact and near-duplicate content (cosine + MinHash Jaccard, both signals required to agree)
  - **`stale_versions`** — superseded document versions still live in the store, escalated if a self-retrieval probe shows both old and new versions surfacing together
  - **`chunking_damage`** — six deterministic rules: undersized chunks, split tables, orphan headings, broken sentences, missing required metadata, encoding noise
  - **`contradictions`** — numeric/date/money/percent/duration facts extracted and cross-checked for genuine conflicts, confirmed by an LLM judge (off by default — opt in once a judge is configured)
  
  Produces a health score (0–100) and an HTML/JSON report.
- **`kbguard golden generate` / `golden freeze`** — samples real chunks, has a judge draft candidate questions, and lets a human review and approve them into a stable golden Q&A set.
- **`kbguard calibrate`** — scores a human-labeled calibration set with the configured judge and reports Cohen's kappa, so answer-quality metrics are gated behind a judge that's actually been checked against human judgment, not trusted blindly.
- **`kbguard eval`** — runs retrieval metrics (hit@k, recall@k, precision@k, MRR@k, nDCG@k) against the golden set, always; optionally runs answer-quality metrics (faithfulness, answer relevancy, context precision/recall via [ragas](https://pypi.org/project/ragas/) or [DeepEval](https://pypi.org/project/deepeval/)) against your real RAG pipeline if a judge, target, and passing calibration are all configured. Every result is cause-tagged back to the content checks above, so a bad answer traces to a specific cause instead of a guess.
- **`kbguard diff`** — compares two snapshots and fails (non-zero exit code) on a health drop, a new error-severity finding, or a metric regression — the piece that turns this from a one-off audit into a CI gate.

## Supported vector stores

| Store | Install extra | Notes |
| --- | --- | --- |
| [Chroma](https://www.trychroma.com/) | `chroma` | Local/in-process, no server required |
| [pgvector](https://github.com/pgvector/pgvector) | `pgvector` | Works against your existing schema, read-only |
| [Qdrant](https://qdrant.tech/) | `qdrant` | |
| [Pinecone](https://www.pinecone.io/) | `pinecone` | |
| LangChain / LlamaIndex | `langchain` / `llamaindex` | Wraps an existing `VectorStore` object directly — no migration needed |

Any other store is a small adapter away (the simplest built-in one, Chroma's, is 125 lines — `kbguard.adapters` is a plugin entry-point group, see [Writing a custom adapter](docs/guide/adapters/custom-adapter.md)).

## Installation

Not yet published to PyPI — install from source:

```bash
git clone https://github.com/devbyanoop/kbguard.git
cd kbguard
python -m venv .venv
source .venv/bin/activate   # Windows (Git Bash): source .venv/Scripts/activate

pip install -e ".[dev,chroma]"
```

Swap or add extras for the store(s) you actually want (`pgvector`, `qdrant`, `pinecone`, `langchain`, `llamaindex`), plus `litellm` for the judge, and `ragas`/`deepeval` for answer-quality metrics. `pip install -e ".[all]"` pulls in everything the test suite itself needs.

See [Installation](docs/getting-started/installation.md) for the full breakdown.

## Quickstart

A bundled example corpus (`examples/policy_corpus/`) lets you try this with no vector database setup of your own:

```bash
python examples/policy_corpus/seed.py
kbguard scan --collection demo --config examples/policy_corpus/kbguard.yaml
```

```text
Wrote snapshot '2026-10-20T06-47-31_demo': 17 chunks -> .kbguard\snapshots\2026-10-20T06-47-31_demo (report.html, results.json)
```

Open `report.html` in the printed snapshot directory — you'll see a health score of **86** and 10 real findings (2 duplicate pairs, 1 stale-version pair, 7 chunking-damage findings) across the corpus's deliberately planted problems. Full walkthrough, including evals/golden sets/CI gating, in [Quickstart](docs/getting-started/quickstart.md).

Pointing this at your own store is a config change, not a code change — set `store.adapter` and `store.settings` in `kbguard.yaml` to your real vector database and rerun `kbguard scan`.

## Documentation

Full guide (configuration, every check, every adapter, evals, judge calibration, CI integration) lives under [`docs/`](docs/) — build it locally with `mkdocs serve`, or browse the Markdown directly on GitHub.

- [Getting started](docs/getting-started/installation.md)
- [Configuration reference](docs/guide/configuration.md)
- [CLI reference](docs/reference/cli.md)
- [Roadmap & status](docs/project/roadmap.md) — what's actually built vs. planned, updated the same day anything changes
- [Sample audit report](docs/project/sample-audit-report.md) — a real `kbguard scan` run against LangChain's own live public documentation, not a synthetic test corpus

## Project status

Every check, every adapter, and the full evals/calibration/diff/CI pipeline are complete and have been verified against real vector databases and a real LLM provider, not just mocks. Packaging has been verified against a real clean-venv install from the built wheel, and this README and the rest of the docs site are filled in end to end. Not yet published to PyPI. See [Roadmap & status](docs/project/roadmap.md) for the exact current state.

## Contributing

Issues and PRs welcome. See [Contributing](docs/project/contributing.md) for how the test suite, linting, and docs policy work.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright 2026 Anoop Singh.
