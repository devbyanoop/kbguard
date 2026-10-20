"""Seeds a small, clean knowledge base into a local, persistent Chroma
collection using kbguard's own REAL embedder (sentence-transformers,
all-MiniLM-L6-v2, 384-dim) -- unlike examples/policy_corpus/seed.py, which
uses hand-crafted 14-dim vectors on purpose for exact-threshold Week 2
checks. Golden-question retrieval needs to embed brand-new question text
into the *same* space the corpus's own chunks live in, which only works if
that space is a real embedder's, not a one-off hand-crafted basis -- so
this corpus exists specifically for Plan/TESTING_GUIDE.md's Week 3 walk
through (golden set -> calibrate -> eval -> diff), not for Week 2's checks.

Run directly: python examples/eval_demo/seed.py
Then:         kbguard scan --collection eval_demo --config examples/eval_demo/kbguard.yaml
"""

from pathlib import Path

import chromadb

from kbguard.config import EmbeddingsConfig
from kbguard.ingest.embeddings import get_embedder

_DEFAULT_PATH = Path(__file__).parent / "chroma_data"

CHUNKS = [
    {
        "id": "ship-1",
        "text": "Standard shipping takes 5 to 7 business days within the continental US.",
        "metadata": {"doc_id": "shipping-policy"},
    },
    {
        "id": "ship-2",
        "text": "Express shipping takes 1 to 2 business days and costs an additional $15.",
        "metadata": {"doc_id": "shipping-policy"},
    },
    {
        "id": "support-1",
        "text": "Customer support is available via live chat Monday through Friday, 9am to 6pm Eastern Time.",
        "metadata": {"doc_id": "support-policy"},
    },
    {
        "id": "support-2",
        "text": "Priority support with a dedicated account manager is included with the Enterprise plan only.",
        "metadata": {"doc_id": "support-policy"},
    },
    {
        "id": "privacy-1",
        "text": "Customer data is retained for 24 months after account closure, then permanently deleted.",
        "metadata": {"doc_id": "privacy-policy"},
    },
    {
        "id": "privacy-2",
        "text": "Customers can request a full export of their data at any time by emailing privacy@example.com.",
        "metadata": {"doc_id": "privacy-policy"},
    },
]


def seed() -> None:
    client = chromadb.PersistentClient(path=str(_DEFAULT_PATH))
    collection = client.get_or_create_collection("eval_demo")
    if collection.count() >= len(CHUNKS):
        print(f"eval_demo collection at {_DEFAULT_PATH} already has all {len(CHUNKS)} chunks — nothing to do.")
        return

    embed = get_embedder(EmbeddingsConfig())
    collection.add(
        ids=[c["id"] for c in CHUNKS],
        documents=[c["text"] for c in CHUNKS],
        metadatas=[c["metadata"] for c in CHUNKS],
        embeddings=[embed(c["text"]) for c in CHUNKS],
    )
    print(f"Seeded {len(CHUNKS)} chunks into the eval_demo collection at {_DEFAULT_PATH}")


if __name__ == "__main__":
    seed()
