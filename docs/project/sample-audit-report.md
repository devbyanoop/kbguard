# Sample audit report: a real public documentation site

Every other example in this guide uses `examples/policy_corpus/` — a synthetic corpus with deliberately planted problems, built to make the content checks' own thresholds hand-verifiable. This page is different: it's a real run of `kbguard scan` against a real, live, third-party production knowledge base kbguard had never seen before, to answer one question honestly — does kbguard find genuine problems in real content, or only the ones it was built to find?

**Target:** LangChain's own real, public Python documentation (`docs.langchain.com/oss/python/langchain/` — 68 pages as of 2026-10-26). Chosen because it's large enough to have accumulated genuine real-world documentation drift, public and permissively crawlable (`robots.txt`: `Content-Signal: ai-train=yes, ai-input=yes`), and — fittingly — it's the documentation for an AI framework, being audited by an AI-testing tool.

**Method:** fetched all 68 pages (a descriptive User-Agent, rate-limited requests), extracted real body text with BeautifulSoup, chunked by H2 section — a common, realistic RAG chunking strategy, not a strategy picked to flatter the results — and embedded every chunk with kbguard's own default embedder (`sentence-transformers/all-MiniLM-L6-v2`) into a local Chroma collection. 459 real chunks. No synthetic problems were planted; every finding below is something kbguard found in LangChain's actual, current documentation on its own. The scraped content and resulting vector database are not part of this repository — only this write-up is.

## Result: health score 92, 166 findings

| Check | Findings | Severity |
| --- | --- | --- |
| `chunking_damage` | 148 | warn |
| `stale_versions` | 15 | warn |
| `duplicates` | 3 | error |

## What was real, and what wasn't — reported honestly

The first run of `stale_versions` produced **395** findings, not 15. That turned out to be a bug in this report's own methodology, not a real finding: every chunk's metadata used the *page's* title for every section on that page, so the check correctly grouped same-titled chunks together and then — just as correctly, given the bad input — flagged every section of a page as a "superseded version" of every other section of the *same* page. Fixed by giving each chunk a per-section title (`page title — heading`) instead of the page's title alone. The real count dropped to 15. This is kept in rather than quietly corrected, because it's the most useful finding on this whole page for anyone running kbguard against their own real vector store: if you chunk below the document level, `stale_versions`' title-grouping needs a title that's unique *per chunk*, not just per source document.

### `duplicates` — real, verified by hand

The exact same "Setup" boilerplate (`pip install langchain`, LangSmith tracing environment variables) appears **verbatim** across six different real tutorial pages: `multi-agent/handoffs-customer-support`, `multi-agent/skills-sql-assistant`, `multi-agent/subagents-personal-assistant`, `sql-agent`, `test/integration-testing`, and `test/unit-testing`. Confirmed by reading the actual extracted text, not just trusting the check's own output. This is exactly the retrieval-diversity problem `duplicates` exists to catch: a user asking "how do I set up LangChain" against a RAG system built on this content would get up to six near-identical hits instead of six different, useful answers.

### `stale_versions` — a real, legitimate information-architecture finding

After the methodology fix above, ~7 of the 15 remaining findings are genuinely interesting: LangChain has the same topic documented in two different places under different URL prefixes — `frontend/human-in-the-loop` vs. `human-in-the-loop`, `frontend/structured-output` vs. `structured-output`, `mcp/tools` vs. `tools` — with real, different last-modified timestamps on each pair. Whether this is intentional (a `frontend/`-specific variant of a general topic) or accidental drift from a docs restructuring isn't something an automated check can decide — and it isn't supposed to. The honest claim is narrower and still useful: it correctly surfaced a real candidate for a human to look at, out of 459 chunks, instead of requiring someone to read all of them.

The remaining ~8 of the 15 are a real limitation worth naming rather than hiding: a handful of pages share a generic, non-descriptive H2 heading ("View example trace," labeling an embedded trace-viewer widget) that produces a same-title match on content that isn't actually related. `stale_versions`' title-based grouping is vulnerable to generic repeated headings — a real, documented edge case, not a bug to silently work around in this report.

### `chunking_damage` — a real problem this check's original design never anticipated

The largest category, and the most genuinely surprising one. A meaningful share of the 148 findings come from real interactive page elements — flow diagrams, trace-viewer widgets — whose underlying text, once naively extracted the way a real ingestion pipeline would, reads as disconnected fragments: `"approve edit reject respond"`, `"current_step active_agent transfer_to_sales_agent"`. These are genuinely confusing chunks if a RAG system retrieved them as context, and `chunking_damage`'s `broken_sentence`/`orphan_heading` rules correctly flag them — on content kbguard's original synthetic test corpus (plain prose documents) never modeled, because modern documentation sites didn't look like this when that corpus was built. The rest of the category is a more mundane, equally real finding: an H2-section chunking strategy produces very unevenly sized chunks against real content — some single-heading sections ran to several thousand words (mostly multi-provider code examples stacked under one heading), others to three or four words. Both are genuine properties of applying a common, realistic chunking strategy to this real site, not an artifact of this report.

## Conclusion

Every one of these findings traces to something a person can go look up right now at a real, public URL. Nothing here was planted, and the one mistake found along the way (the `stale_versions` metadata bug) is reported rather than quietly fixed before publishing — the same standard this report holds LangChain's own documentation to.
