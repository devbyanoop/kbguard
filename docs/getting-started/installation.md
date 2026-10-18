# Installation

!!! warning "Not yet on PyPI"
    kbguard hasn't published a `0.1.0` release yet. Once it does, installation will be `pip install kbguard`, with extras for whichever vector store you use (e.g. `pip install "kbguard[qdrant]"`). This page will be updated the day that's true — until then, the section below is the real, verified way to run kbguard today.

## Install from source (current, verified)

This is what the project itself uses for development, and it works right now against the current state of the repository.

**Requirements:** Python 3.10 or newer.

```bash
git clone https://github.com/anoopsingh/kbguard.git
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
- `[dev,chroma]` is an **extras** selector: `dev` pulls in `pytest`, `ruff`, and `mypy`; `chroma` pulls in the Chroma client, the only vector-store dependency needed to run the test suite today (Chroma runs in-process, no server required). Swap or add extras for the store you actually want to test against once more adapters exist — e.g. `[dev,qdrant]`.

Verify the install:

```bash
pytest
```

## Planned extras (once the matching adapter ships)

| Extra | Pulls in | Status |
| --- | --- | --- |
| `chroma` | `chromadb` | ✅ Available |
| `pgvector` | `psycopg`, `pgvector` | Planned — Week 1 |
| `qdrant` | `qdrant-client` | Planned — Week 1 |
| `pinecone` | `pinecone-client` | Planned — Week 2 |
| `langchain` / `llamaindex` | `langchain-core` / `llama-index-core` | Planned — Week 2 |
| `ragas` | `ragas` | Planned — Week 3 |
| `deepeval` | `deepeval` | Planned — Week 3 |

See [Roadmap & status](../project/roadmap.md) for the current build state.
