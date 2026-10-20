import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Any, cast

import numpy as np

from kbguard.checks.base import CheckContext, JudgeLike
from kbguard.config import ContradictionsCheckConfig, FactType
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Chunk, Finding, Severity, compute_fingerprint

# Chunks are clustered by embedding cosine similarity before any fact
# extraction happens at all — the spec's first narrowing step (see
# Plan/kbguard.md section 8.4's pipeline diagram), done with plain numpy,
# not faiss: unlike duplicates.py's near-duplicate ANN search, this is a
# much looser "roughly the same topic" grouping (0.6, well below
# duplicates' 0.97), and v0.1 doesn't need ANN-scale performance for it.
# Brute-force O(n^2) cosine is a real v0.1 scaling limit for a large
# corpus, not hidden: revisit with faiss if that ever matters in practice.
#
# 0.6 isn't independently measured against a broad corpus of real
# contradicting-fact pairs (no such corpus was available) — it's picked
# to clear a real, measured gap in the one corpus available: the example
# corpus's two genuine same-topic pairs sit at 0.7071 and 0.6402, and its
# highest *unrelated* pair sits at 0.5432 (verified by hand, see
# examples/policy_corpus/seed.py's pairwise comment). 0.6 clears both
# with margin. Revisit if a real corpus ever disagrees.
_CLUSTER_COSINE_THRESHOLD = 0.6

_MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# Priority order matters: scanned in this sequence, and a later pattern's
# match is discarded if it overlaps a span an earlier (higher-priority)
# pattern already claimed — e.g. "14" inside "14 days" must not also
# become its own bare "number" fact, and "2026" inside "2026-06-01" must
# not become its own bare "number" fact either.
_FACT_PATTERNS: list[tuple[FactType, re.Pattern[str]]] = [
    ("money", re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")),
    ("percent", re.compile(r"\d+(?:\.\d+)?\s?%")),
    (
        "duration",
        re.compile(
            r"\d+(?:\.\d+)?[\s-]?(?:day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "date",
        re.compile(
            r"\d{4}-\d{2}-\d{2}|"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2},?\s+\d{4}",
            re.IGNORECASE,
        ),
    ),
    # Deliberately last and broadest — only ever claims a span none of the
    # four more specific patterns above already consumed.
    ("number", re.compile(r"\d+(?:\.\d+)?")),
]


class ContradictionsCheckError(Exception):
    """Raised when this check is enabled but genuinely can't run: no judge
    configured, or the 'nlp' extra / its spaCy model isn't installed. This
    check never reports an unconfirmed candidate pair as a finding — cheap
    regex/embedding matching alone is nowhere near reliable enough for
    that — so running it without a judge isn't "fewer findings," it's
    "can't do the one thing this check exists to do," which should surface
    as a clear error, not silently report zero contradictions found."""


@dataclass
class _Fact:
    chunk_id: str
    source: str | None
    fact_type: FactType
    raw_text: str
    value: Any  # comparable within the same fact_type; see _parse_value
    subject: str | None  # normalized (lemmatized, lowercased) head noun, or None


class ContradictionsCheck:
    name = "contradictions"
    default_severity: Severity = "error"

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]:
        config = cast(ContradictionsCheckConfig, ctx.config)
        if not config.enabled:
            return
        if ctx.judge is None:
            raise ContradictionsCheckError(
                "the contradictions check needs a judge: every candidate pair is confirmed "
                "by an LLM before being reported, never reported unconfirmed — set `judge:` "
                "in kbguard.yaml and pass a JudgeClient via CheckContext.judge"
            )

        chunks = {c.id: c for c in snapshot.chunks()}
        if len(chunks) < 2:
            return

        nlp = _load_spacy_model()
        vectors_by_id = dict(snapshot.vectors())
        clusters = _cluster_by_embedding(chunks, vectors_by_id)

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            facts: list[_Fact] = []
            for chunk_id in cluster:
                facts.extend(_extract_facts(chunks[chunk_id], config.types, nlp))

            for fact_a, fact_b in _candidate_pairs(facts):
                finding = _confirm(fact_a, fact_b, chunks, ctx.judge, config.severity)
                if finding is not None:
                    yield finding


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class _UnionFind:
    """Same small disjoint-set structure as duplicates.py's — duplicated
    rather than imported from it, so this check stays a self-contained
    file, same as a third-party check would be (checks/base.py's own
    design principle: no built-in check depends on another's internals)."""

    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _cluster_by_embedding(chunks: dict[str, Chunk], vectors_by_id: dict[str, list[float]]) -> list[list[str]]:
    ids = [cid for cid in chunks if cid in vectors_by_id]
    uf = _UnionFind(ids)
    arrays = {cid: np.array(vectors_by_id[cid]) for cid in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if _cosine(arrays[a], arrays[b]) >= _CLUSTER_COSINE_THRESHOLD:
                uf.union(a, b)

    groups: dict[str, list[str]] = defaultdict(list)
    for cid in ids:
        groups[uf.find(cid)].append(cid)
    return [sorted(members) for members in groups.values()]


_spacy_model: Any = None  # module-level singleton, loaded lazily and once


def _load_spacy_model() -> Any:
    global _spacy_model
    if _spacy_model is None:
        try:
            import spacy
        except ImportError as exc:
            raise ContradictionsCheckError(
                'the contradictions check needs the \'nlp\' extra: pip install "kbguard[nlp]", '
                "then download its small English model: python -m spacy download en_core_web_sm"
            ) from exc
        try:
            _spacy_model = spacy.load("en_core_web_sm")
        except OSError as exc:
            raise ContradictionsCheckError(
                "the contradictions check needs spaCy's small English model: "
                "python -m spacy download en_core_web_sm"
            ) from exc
    return _spacy_model


def _parse_value(fact_type: FactType, raw: str) -> Any:
    if fact_type == "money":
        return float(raw.lstrip("$").replace(",", "").strip())
    if fact_type == "percent":
        return float(raw.rstrip("%").strip())
    if fact_type == "duration":
        # (amount, unit) as a comparable pair, not unit-converted (e.g. "1
        # year" vs "365 days" are never recognized as equal) — a known,
        # deliberate v0.1 limitation: unit conversion adds real complexity
        # (leap years, "month" having no fixed day count) for a case this
        # corpus-driven build never needed to solve.
        match = re.match(r"(\d+(?:\.\d+)?)[\s-]?([a-zA-Z]+)", raw)
        assert match is not None  # guaranteed by the pattern that produced raw
        amount, unit = float(match.group(1)), match.group(2).lower().rstrip("s")
        return (amount, unit)
    if fact_type == "date":
        iso_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if iso_match:
            y, mo, d = iso_match.groups()
            return date(int(y), int(mo), int(d))
        month_match = re.match(r"([a-zA-Z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
        assert month_match is not None
        month_name, day, year = month_match.groups()
        return date(int(year), _MONTH_NUMBERS[month_name.lower()], int(day))
    return float(raw)  # "number"


def _nearest_subject(doc: Any, start: int, end: int) -> str | None:
    """The normalized (lemmatized, lowercased) head noun of whichever noun
    chunk is most relevant to the fact at [start, end) in this doc's text:

    - If a noun chunk *contains* the fact's span (e.g. "a 2-year warranty"
      contains "2-year") and its grammatical head is outside that span
      (the head is "warranty", not "2-year" itself), that's the strongest
      possible signal — the value's own surrounding phrase.
    - Otherwise, the nearest noun chunk that doesn't overlap the fact's
      span at all (e.g. "Returns ... 14 days ... delivery" — "delivery" is
      the nearest external noun phrase to "14 days").
    - A chunk that overlaps the fact's span without containing it, or
      whose head noun falls inside the span (e.g. "14 days" is itself a
      noun chunk whose head is "days" — not a *subject*, just the value's
      own unit word), doesn't qualify as either case and is skipped.

    Verified against this project's two real planted contradiction pairs
    before trusting this design: both produce the same subject for both
    members of the pair ("warranty" for the warranty-a/b pair, "delivery"
    for the return-window-v1/v2 pair), which is what actually matters —
    not that the chosen word is the most natural human label.
    """
    best: str | None = None
    best_priority: tuple[int, int] | None = None
    for chunk in doc.noun_chunks:
        root_start = chunk.root.idx
        root_end = root_start + len(chunk.root.text)
        contains = chunk.start_char <= start and chunk.end_char >= end
        root_outside_fact = root_end <= start or root_start >= end

        if contains and root_outside_fact:
            priority = (0, 0)
        elif chunk.end_char <= start or chunk.start_char >= end:
            gap = (start - chunk.end_char) if chunk.end_char <= start else (chunk.start_char - end)
            priority = (1, gap)
        else:
            continue

        if best_priority is None or priority < best_priority:
            best_priority = priority
            best = chunk.root.lemma_.lower()
    return best


def _extract_facts(chunk: Chunk, enabled_types: list[FactType], nlp: Any) -> list[_Fact]:
    doc = nlp(chunk.text)
    consumed: list[tuple[int, int]] = []
    facts: list[_Fact] = []
    # Every pattern scans and claims its span regardless of whether its
    # fact_type is in enabled_types — not just the enabled ones. Otherwise,
    # disabling "duration" would let the bare digit inside e.g. "1-year"
    # leak through and get reported as a "number" fact instead (the two
    # chunks' "1" and "2" genuinely differ) — the same contradiction
    # resurfacing under a type the user didn't ask to disable, which
    # defeats the point of disabling it. Found by a test that assumed
    # disabling a type meant "nothing extracted at all" and was wrong.
    for fact_type, pattern in _FACT_PATTERNS:
        for match in pattern.finditer(chunk.text):
            if any(not (match.end() <= c_start or match.start() >= c_end) for c_start, c_end in consumed):
                continue
            consumed.append((match.start(), match.end()))
            if fact_type not in enabled_types:
                continue
            subject = _nearest_subject(doc, match.start(), match.end())
            if subject is None:
                continue  # no usable subject -> can't be meaningfully paired, so dropped
            facts.append(
                _Fact(
                    chunk_id=chunk.id,
                    source=chunk.source,
                    fact_type=fact_type,
                    raw_text=match.group(),
                    value=_parse_value(fact_type, match.group()),
                    subject=subject,
                )
            )
    return facts


def _candidate_pairs(facts: list[_Fact]) -> list[tuple[_Fact, _Fact]]:
    by_key: dict[tuple[FactType, str], list[_Fact]] = defaultdict(list)
    for fact in facts:
        if fact.subject is not None:
            by_key[(fact.fact_type, fact.subject)].append(fact)

    pairs: list[tuple[_Fact, _Fact]] = []
    for group in by_key.values():
        for fact_a, fact_b in combinations(group, 2):
            if fact_a.value == fact_b.value:
                continue  # same value -> not a contradiction candidate
            if fact_a.source is None or fact_b.source is None or fact_a.source == fact_b.source:
                continue  # need *confirmed* different sources, not just "not provably the same"
            pairs.append((fact_a, fact_b))
    return pairs


_SCHEMA_HINT = '{"conflict": bool, "explanation": str}'


def _confirm(
    fact_a: _Fact, fact_b: _Fact, chunks: dict[str, Chunk], judge: JudgeLike, base_severity: Severity
) -> Finding | None:
    chunk_a, chunk_b = chunks[fact_a.chunk_id], chunks[fact_b.chunk_id]
    prompt = (
        f"Chunk A: {chunk_a.text!r}\n"
        f"Chunk B: {chunk_b.text!r}\n\n"
        f"Chunk A states a {fact_a.fact_type} value of {fact_a.raw_text!r} regarding '{fact_a.subject}'. "
        f"Chunk B states a {fact_b.fact_type} value of {fact_b.raw_text!r} regarding the same thing. "
        "Do these two values genuinely conflict (describe the same real-world fact but disagree), or "
        "could both be true at once (e.g. they apply to different situations, tiers, or conditions)?"
    )
    response = judge.ask_json(prompt, _SCHEMA_HINT)
    if not response.get("conflict"):
        return None

    # Guaranteed by _candidate_pairs, which only ever groups facts whose
    # subject is not None — mypy can't see that invariant across the
    # dataclass field, so it's asserted here rather than fought.
    assert fact_a.subject is not None

    return Finding(
        check="contradictions",
        severity=base_severity,
        chunk_ids=sorted([fact_a.chunk_id, fact_b.chunk_id]),
        message=(
            f"Chunks disagree on {fact_a.fact_type} for '{fact_a.subject}': "
            f"{fact_a.raw_text!r} vs {fact_b.raw_text!r}"
        ),
        evidence={
            "fact_type": fact_a.fact_type,
            "subject": fact_a.subject,
            "value_a": fact_a.raw_text,
            "value_b": fact_b.raw_text,
            "explanation": response.get("explanation"),
        },
        fingerprint=compute_fingerprint(
            "contradictions", [fact_a.chunk_id, fact_b.chunk_id], identity_keys=[fact_a.fact_type, fact_a.subject]
        ),
    )
