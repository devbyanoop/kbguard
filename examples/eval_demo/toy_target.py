"""A minimal toy RAG target for `kbguard eval`'s `target:` config, used by
Plan/TESTING_GUIDE.md's Week 3 walkthrough (golden set -> calibrate -> eval
-> diff) against the eval_demo corpus (see seed.py for why this corpus,
not policy_corpus, is used here).

Retrieval reuses the same real embedder the corpus itself was seeded
with, then asks a real LLM to answer from the retrieved context. Good
enough to exercise kbguard's target/eval/metrics wiring end to end
against real embeddings and a real judge model -- not meant to be a
production-grade RAG system.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from kbguard.adapters.chroma import ChromaAdapter
from kbguard.config import EmbeddingsConfig
from kbguard.ingest.embeddings import get_embedder

load_dotenv()

_adapter = ChromaAdapter()
_adapter.connect(path=str(Path(__file__).parent / "chroma_data"))
_embed = get_embedder(EmbeddingsConfig())


def answer(question: str) -> dict[str, Any]:
    import litellm

    results = _adapter.search("eval_demo", _embed(question), k=2)
    contexts = [chunk.text for chunk, _score in results]
    response = litellm.completion(
        model=os.environ.get("KBGUARD_TARGET_MODEL", "groq/qwen/qwen3.8-27b"),
        messages=[
            {
                "role": "system",
                "content": "Answer the question using ONLY the provided context. Be concise (1-2 sentences).",
            },
            {"role": "user", "content": f"Context:\n{chr(10).join(contexts)}\n\nQuestion: {question}"},
        ],
        temperature=0.0,
    )
    return {"answer": response.choices[0].message.content, "contexts": contexts}
