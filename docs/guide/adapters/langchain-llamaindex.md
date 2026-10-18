# LangChain / LlamaIndex bridge

!!! warning "Planned — Week 2"
    Not implemented yet.

## Why this adapter matters most for real adoption

Most RAG applications are already built on top of a LangChain or LlamaIndex vector store object, not a bare database client. This bridge wraps that existing object directly, so you can point kbguard at a knowledge base without standing up a second, separate connection to the underlying store.

## Planned behavior

- **Full iteration when available:** if the wrapped store exposes a true "iterate everything" method, the bridge uses it.
- **Search-based sampling fallback:** some LangChain/LlamaIndex store wrappers don't expose full iteration at all. When that's the case, the bridge falls back to **sampling** via repeated searches — and marks the resulting snapshot's manifest as `iteration_mode: "sampled"` rather than `"full"`, so a sampled scan is never mistaken for a complete one. This is a deliberate, documented limitation, not a bug to be silently worked around.

This page becomes a real usage guide, including exactly which LangChain/LlamaIndex store classes support full iteration vs. require sampling, once `adapters/bridge_langchain.py` is built and tested against both cases.
