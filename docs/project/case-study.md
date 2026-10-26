# Case study: finding real RAG problems, not just planted ones

Most RAG evaluation tools answer "is this answer good?" and quietly assume the knowledge base underneath it is clean. kbguard tests that assumption instead of making it — and this write-up is the evidence, not just the pitch.

## The problem

A RAG system — a support chatbot, an internal knowledge assistant, a "chat with your docs" feature — is only as good as the content it retrieves from. In practice, two things go wrong in almost every real deployment:

1. **The knowledge base rots silently.** A policy doc gets updated but the old version stays in the vector store. Two documents state contradictory facts. A PDF got chunked mid-sentence or mid-table. None of this throws an error — it just means the system occasionally gives a wrong answer, and nobody notices until a customer does.
2. **Nobody can tell *why* an answer was wrong.** Did retrieval fail to find the right chunk? Did the right chunk get found and ignored? Or was the content wrong to begin with? Without that distinction, "the bot gave a bad answer" is undebuggable.

## What was built

kbguard: four content-quality checks (duplicates, stale document versions, chunking damage, cross-document contradictions), retrieval and answer-quality evals with results traced back to a specific cause, judge calibration against human labels (so an LLM-as-judge is never trusted blindly), and a `diff` command that gates CI on a real regression — all working against any vector database (Chroma, pgvector, Qdrant, Pinecone, or anything already wrapped by LangChain/LlamaIndex), read-only, with zero write access to the store it audits.

## The part that matters: it was validated against real systems, not just its own test suite

A tool that only passes its own tests proves nothing except that its author agreed with itself. Two separate rounds of real-world testing did the opposite:

**Round 1 — hardening against real APIs.** Every judge-dependent code path was re-verified against a real LLM provider and a real cloud vector database, not the fast fakes the unit test suite uses for everyday development. This surfaced three bugs no fake could have caught:

- The same exact prompt to the same real model returned different verdicts across separate calls — confirmed by hand, three calls, three different answers. Fixed with `temperature=0`. That alone wasn't enough: one real model then *deterministically* got a planted test case wrong at zero temperature, while a different real model got it right — a genuine model-capability gap, not noise, and the reason a calibration step exists in the first place rather than trusting any single judge model.
- Running the actual installed command-line tool — not a local script, not `python -m` — failed to import a client's own RAG-calling code, because the installed console script doesn't add the working directory to Python's import path the way a direct script invocation does. Every existing test had used a technique that happened to route around this exact failure mode.
- A real rate limit from a real LLM provider, hit mid-run, crashed the entire evaluation and discarded every already-computed result — directly contradicting the tool's own documented promise that one broken question shouldn't abort the rest. Fixed, with a test that forces the real failure path rather than asserting the happy case.

**Round 2 — a real production documentation site, never seen before, with zero planted problems.** 68 live pages of LangChain's own public Python documentation were scraped, chunked, embedded, and scanned for real. The findings:

- The exact same "Setup" boilerplate, copy-pasted verbatim, across six different real tutorial pages — a genuine retrieval-diversity problem, verified by reading the actual text, not just trusting the tool's own output.
- A real information-architecture issue: the same topic documented in two different places under different URL paths, with real, different last-modified timestamps on each — exactly the kind of candidate a human reviewer would want flagged, not a false alarm invented for a demo.
- Real chunking damage from something the original design never anticipated: interactive diagram and trace-viewer widgets whose underlying text, once extracted the way a real ingestion pipeline would, reads as disconnected fragments — a genuinely new failure mode, found only because the target was real and current, not a static synthetic fixture.

One honest mistake happened along the way too, and it's reported rather than quietly fixed before publishing: a metadata bug produced 395 false "stale version" findings on the first run. It was found, understood, fixed, and the real number (15, with roughly half being genuine) is what's published. That standard — report what's real, including your own mistakes, before calling something done — is the same standard the tool holds every RAG system it audits to.

## Why this is relevant to you

If you're running a support bot, an internal knowledge assistant, or any "chat with your data" feature on a vector database, the two failure modes above are already happening somewhere in your content — most teams just don't have a way to see it yet. This is a tool built specifically to surface exactly that, against whatever store you already run, without needing you to change anything.

Full technical detail, the complete audit report, and the source itself: [github.com/devbyanoop/kbguard](https://github.com/devbyanoop/kbguard).
