# Installation

**Requirements:** Python 3.10 or newer.

```bash
pip install "kbguard[chroma]"
```

Swap or add extras for the store(s) you actually want — see the full table below. Verified for real: this is a plain, non-editable install from [PyPI](https://pypi.org/project/kbguard/), re-checked on a genuinely clean environment (no extras already present from somewhere else) as part of the release itself, not just assumed from the build passing.

## Install from source (for contributing to kbguard itself)

This is what the project itself uses for development — an editable install against your own clone, so changes under `src/kbguard/` take effect immediately without reinstalling.

```bash
git clone https://github.com/devbyanoop/kbguard.git
cd kbguard
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (Git Bash):
source .venv/Scripts/activate

pip install -e ".[dev,chroma]"
```

- `python -m venv .venv` creates an isolated Python environment just for this project, so kbguard's dependencies never collide with another project's on your machine.
- `-e` installs in **editable** mode — changes to the source under `src/kbguard/` take effect immediately, without reinstalling. This is the right mode for working on kbguard itself; if you're just using kbguard, use the plain `pip install kbguard` above instead.
- `[dev,chroma]` is an **extras** selector: `dev` pulls in `pytest`, `ruff`, and `mypy`; `chroma` pulls in the Chroma client, the quickest vector-store dependency to try first (Chroma runs in-process, no server required). Swap or add extras for the store(s) you actually want — e.g. `[dev,qdrant]`, or `[dev,chroma,pgvector,qdrant,pinecone]` for all four at once.

Verify the install:

```bash
pytest
```

## All extras

Every extra below is built, tested, and verified against a real instance of its own backend (not just mocked) — none of this is planned/future work.

| Extra | Pulls in |
| --- | --- |
| `chroma` | `chromadb` |
| `pgvector` | `psycopg`, `pgvector` |
| `qdrant` | `qdrant-client` |
| `pinecone` | `pinecone` |
| `langchain` | `langchain-core` (wraps an existing LangChain `VectorStore`) |
| `llamaindex` | `llama-index-core` |
| `litellm` | `litellm` — needed for the judge (`contradictions` check, golden-set generation, calibration, answer-quality metrics) |
| `ragas` | `ragas`, `langchain-community<0.4` — answer-quality metrics |
| `deepeval` | `deepeval` — answer-quality metrics |
| `sentence-transformers` | `sentence-transformers` — the default local embedding provider |
| `dedup` | `faiss-cpu`, `datasketch` — needed by the `duplicates` check |
| `nlp` | `spacy` — needed by the `contradictions` check's fact-extraction step |
| `all` | every extra above, plus `dev` and `docs` — what CI itself installs |

See [Roadmap & status](../project/roadmap.md) for the current build state.
