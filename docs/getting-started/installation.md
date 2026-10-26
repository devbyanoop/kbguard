# Installation

!!! warning "Not yet on PyPI"
    kbguard hasn't published a `0.1.0` release yet. Once it does, installation will be `pip install kbguard`, with extras for whichever vector store you use (e.g. `pip install "kbguard[qdrant]"`). This page will be updated the day that's true — until then, the section below is the real, verified way to run kbguard today.

## Install from source (current, verified)

This is what the project itself uses for development, and it works right now against the current state of the repository.

**Requirements:** Python 3.10 or newer.

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
- `-e` installs in **editable** mode — changes to the source under `src/kbguard/` take effect immediately, without reinstalling. This is the right mode for working on kbguard itself; once there's a real release, end users will just use a normal (non-editable) install.
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
