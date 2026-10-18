# kbguard

**Knowledge-base QA and evals for RAG systems, across any vector database.**

!!! note "Status: early development"
    kbguard is being built in the open, feature by feature. This guide grows alongside the code — every page below is either real, verified documentation for something that works today, or a clearly marked placeholder for something planned. See [Roadmap & status](project/roadmap.md) for exactly what's implemented right now.

## The problem

A RAG system can fail in two completely different places, and most teams can't tell which one just broke:

1. **The knowledge base itself** — the documents sitting in your vector store. Duplicates. Stale policies that got re-uploaded without removing the old version. Chunks cut mid-table or mid-sentence by a bad splitter. Two documents quietly disagreeing about a number ("refunds within 30 days" vs. "refunds within 14 days").
2. **Retrieval and generation** — the system built on top of that knowledge base. Does it find the right chunk? Does the model actually use what it found, or hallucinate past it?

When an answer is wrong, "the retrieval is broken" and "the knowledge base has bad content" look identical from the outside — a wrong answer is a wrong answer. Most RAG evaluation tools only check the second half (recall@k, faithfulness, etc.) and assume the knowledge base underneath is clean. It usually isn't.

## What kbguard does

kbguard tests **both halves in one run**, against whichever vector database you already use, and traces every failure to a cause: **content**, **retrieval**, or **generation** — with the exact chunks involved, so you're not left guessing.

```mermaid
flowchart LR
    A[Your vector store] -->|read-only scan| B[kbguard]
    B --> C{Findings}
    C -->|content| D[Duplicates, stale versions,<br/>chunking damage, contradictions]
    C -->|retrieval / generation| E[recall@k, MRR,<br/>faithfulness, relevancy]
    B --> F[Health score + HTML report]
    B --> G[kbguard diff — fails CI<br/>on regression]
```

A `kbguard diff` between two scans is what makes this usable in CI: it can block a document upload or a chunking-config change the moment it makes the knowledge base measurably worse, before it ever reaches production.

## Who this is for

- **Teams running a RAG system in production** who want a recurring, automated check on knowledge-base quality — not just a one-time audit.
- **Anyone evaluating a vector database migration or a chunking strategy change** who wants a before/after number, not a guess.
- **Consultants and auditors** who need a tool that works against a client's existing stack (pgvector, Qdrant, Pinecone, Chroma, or anything wrapped by LangChain/LlamaIndex) without asking them to change anything.

## Design principles that shape every feature

- **Read-only, always.** kbguard never writes to your vector store. It can't corrupt your data, by construction — there's no code path that would let it.
- **Runs entirely in your environment.** No hosted service, no data leaving your infrastructure. A local judge model (via Ollama) is explicitly supported for teams that can't send document text to a third-party API at all.
- **Any vector store, same checks.** Everything downstream of the adapter layer works on a plain `Chunk` record — the duplicate detector doesn't know or care whether the data came from Qdrant or a Postgres table.
- **Cheap signals before expensive ones.** Deterministic rules and embedding similarity narrow candidates before any LLM call ever happens — this is what keeps cost sane on a million-chunk collection.

## Next steps

- New to kbguard? Start with [Installation](getting-started/installation.md).
- Want to see what's actually built today? Check [Roadmap & status](project/roadmap.md).
- Curious how a specific check works? See the [Knowledge-base checks](guide/checks/overview.md) section.
