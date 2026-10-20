"""Seeds a small, synthetic company-policy knowledge base into a local,
persistent Chroma collection — with deliberately planted problems for
Week 2's checks (duplicates, stale versions, chunking damage,
contradictions) to find, and three clean chunks for contrast.

Run directly: python examples/policy_corpus/seed.py
Then:         kbguard scan --collection demo --config examples/policy_corpus/kbguard.yaml

Embeddings are hand-crafted, not produced by a real embedding model.
That's a deliberate choice, not a shortcut: this corpus needs to work
against the *actual default* duplicate threshold (cosine >= 0.97) to be a
genuine test of the detection logic, and a real model's output can't be
hand-verified before relying on it. Synthetic vectors can be: every pairwise
cosine similarity below was computed and checked by hand before being
committed here (see the "planted relationships" comment below) — a
real model would require trusting that a specific download happened to
land where expected, which is exactly the kind of unverified assumption
this project exists to catch in other people's RAG systems.
"""

from pathlib import Path

import chromadb

_DEFAULT_PATH = Path(__file__).parent / "chroma_data"

# 14-dim one-hot-ish topic basis. Each genuinely distinct topic gets its own
# dimension; dimension 12 is a shared "noise" dimension used ONLY to create
# controlled partial similarity for the two pairs that are deliberately
# somewhat alike (return-window v1/v2, warranty a/b) without ever pushing an
# unrelated pair above the duplicate threshold. Verified pairwise, by hand,
# before being committed:
#   shipping-near-1 <-> shipping-near-2:   0.9995  (near-duplicate: correctly >= 0.97)
#   refund-exact-1  <-> refund-exact-2:    1.0000  (exact duplicate: identical text+vector)
#   return-window-v1 <-> return-window-v2: 0.7071  (same topic, different version: well below 0.97)
#   warranty-a      <-> warranty-b:        0.6402  (same topic, different value: well below 0.97)
#   every other pair:                      < 0.55
def _vec(**dims: float) -> list[float]:
    v = [0.0] * 14
    for key, value in dims.items():
        v[int(key[1:])] = value
    return v


CHUNKS = [
    # --- Exact duplicate (different sources — copy-pasted policy text) ---
    {
        "id": "refund-exact-1",
        "text": (
            "Customers may request a refund within 30 days of purchase, "
            "provided the item is unused and in its original packaging."
        ),
        "embedding": _vec(d0=1),
        "metadata": {"doc_id": "refund-policy", "title": "Refund Policy"},
    },
    {
        "id": "refund-exact-2",
        "text": (
            "Customers may request a refund within 30 days of purchase, "
            "provided the item is unused and in its original packaging."
        ),
        "embedding": _vec(d0=1),
        "metadata": {"doc_id": "customer-faq", "title": "Customer FAQ"},
    },
    # --- Near duplicate (reworded, different sources) ---
    {
        "id": "shipping-near-1",
        "text": "Standard shipping typically takes 3 to 5 business days after an order is confirmed.",
        "embedding": _vec(d1=1),
        "metadata": {"doc_id": "shipping-policy", "title": "Shipping Policy"},
    },
    {
        "id": "shipping-near-2",
        "text": "Standard shipping usually takes three to five business days once an order has been confirmed.",
        "embedding": _vec(d1=0.985, d12=0.03),
        "metadata": {"doc_id": "shipping-faq", "title": "Shipping FAQ"},
    },
    # --- Stale version pair (same doc family; also a numeric contradiction
    # if both remain live, which is realistic — old content often lingers) ---
    {
        "id": "return-window-v1",
        "text": "Returns are accepted within 14 days of delivery for a full refund.",
        "embedding": _vec(d2=1),
        "metadata": {
            "doc_id": "return-policy",
            "title": "Return Policy",
            "version": "v1",
            "updated_at": "2024-01-15T00:00:00Z",
        },
    },
    {
        "id": "return-window-v2",
        "text": "Returns are accepted within 30 days of delivery for a full refund.",
        "embedding": _vec(d2=0.55, d12=0.55),
        "metadata": {
            "doc_id": "return-policy",
            "title": "Return Policy",
            "version": "v2",
            "updated_at": "2026-06-01T00:00:00Z",
        },
    },
    # --- Contradiction between two unrelated docs (not a version pair) ---
    {
        "id": "warranty-a",
        "text": "All electronics purchased through our store come with a 1-year manufacturer warranty.",
        "embedding": _vec(d3=1),
        "metadata": {"doc_id": "warranty-policy", "title": "Warranty Policy"},
    },
    {
        "id": "warranty-b",
        "text": "All electronics are covered by a 2-year warranty from the date of purchase.",
        "embedding": _vec(d3=0.5, d12=0.6),
        "metadata": {"doc_id": "product-faq", "title": "Product FAQ"},
    },
    # --- Chunking damage: split table ---
    {
        "id": "pricing-table-cut",
        "text": "| Plan | Price | Users |\n| --- | --- | --- |\n| Basic | $10/mo | 1 |\n| Pro | $25/mo",
        "embedding": _vec(d4=1),
        "metadata": {"doc_id": "pricing-page", "title": "Pricing"},
    },
    # --- Chunking damage: orphan heading ---
    {
        "id": "orphan-heading-1",
        "text": "## Frequently Asked Questions",
        "embedding": _vec(d5=1),
        "metadata": {"doc_id": "faq-page", "title": "FAQ"},
    },
    # --- Chunking damage: undersized chunk ---
    {
        "id": "tiny-chunk-1",
        "text": "Yes, we do.",
        "embedding": _vec(d6=1),
        "metadata": {"doc_id": "faq-page", "title": "FAQ"},
    },
    # --- Chunking damage: broken sentence, no overlap from a previous chunk ---
    {
        "id": "broken-sentence-1",
        "text": "...and therefore the company reserves the right to modify these terms at any time without prior notice.",
        "embedding": _vec(d7=1),
        "metadata": {"doc_id": "terms-of-service", "title": "Terms of Service"},
    },
    # --- Chunking damage: missing required metadata (no doc_id at all) ---
    {
        "id": "no-source-chunk",
        "text": "Subscriptions can be cancelled at any time from your account settings page.",
        "embedding": _vec(d8=1),
        "metadata": {},
    },
    # --- Chunking damage: encoding noise (stray control characters, a
    # common artifact of bad PDF text extraction) ---
    {
        "id": "encoding-noise-1",
        "text": "Payment methods include credit card\x00\x00 debit card\x01 and bank transfer\x02\x02 for all purchases.",
        "embedding": _vec(d13=1),
        "metadata": {"doc_id": "payment-methods", "title": "Payment Methods"},
    },
    # --- Clean chunks, for contrast (no planted problem) ---
    {
        "id": "privacy-1",
        "text": "We collect only the information necessary to process your order and never sell your personal data to third parties.",
        "embedding": _vec(d9=1),
        "metadata": {"doc_id": "privacy-policy", "title": "Privacy Policy"},
    },
    {
        "id": "contact-1",
        "text": "You can reach our support team by email at support@example.com or by phone during business hours.",
        "embedding": _vec(d10=1),
        "metadata": {"doc_id": "contact-page", "title": "Contact Us"},
    },
    {
        "id": "account-1",
        "text": "To delete your account, go to Settings, then Account, then Delete Account, and confirm your request.",
        "embedding": _vec(d11=1),
        "metadata": {"doc_id": "account-help", "title": "Account Help"},
    },
]


def seed(path: Path = _DEFAULT_PATH) -> None:
    client = chromadb.PersistentClient(path=str(path))
    collection = client.get_or_create_collection(name="demo", embedding_function=None)

    existing = set(collection.get(include=[])["ids"])
    new_chunks = [c for c in CHUNKS if c["id"] not in existing]
    if not new_chunks:
        print(f"demo collection at {path} already has all {len(CHUNKS)} chunks — nothing to do.")
        return

    collection.add(
        ids=[c["id"] for c in new_chunks],
        embeddings=[c["embedding"] for c in new_chunks],
        documents=[c["text"] for c in new_chunks],
        metadatas=[c["metadata"] or {"_empty": True} for c in new_chunks],  # Chroma rejects {} metadata
    )
    print(f"Seeded {len(new_chunks)} chunks into the demo collection at {path}")


if __name__ == "__main__":
    seed()
