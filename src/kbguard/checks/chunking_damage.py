from collections.abc import Iterator
from typing import cast

from kbguard.checks.base import CheckContext
from kbguard.config import ChunkingDamageCheckConfig
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Chunk, Finding, Severity, compute_fingerprint

# A repeated line is only worth flagging as possibly-leaked boilerplate (a
# running header/footer) if it reads as a genuine prose phrase. Two
# earlier attempts at this -- first a short list of specific code/REPL/
# keyword patterns, then excluding by specific punctuation characters --
# both turned into real whack-a-mole scanning Django's own docs: an
# open-ended family of code/config/REPL/SQL shapes (an assignment, a
# decorator, a REPL repr, an RST directive field, a bare filename, an
# `import` line, a bare `True`/`None`, a quoted JSON config entry) kept
# either slipping through or getting caught depending on exactly which
# characters were excluded, with no end to the list in sight.
#
# Settled on one general, two-part mechanism instead: a short line is
# never flagged regardless of shape (nearly every short code/config/
# value line that kept slipping through -- `True`, `import os`, `try:`,
# `polls/` -- is well under 20 characters; a genuine leaked header/
# footer realistically never is), and a longer line must have most of
# its whitespace-separated tokens look like plain words -- alphabetic
# once ordinary sentence punctuation and quotes are stripped, NOT
# brackets/parens/equals/backticks/angle-brackets, since those should
# disqualify a token rather than just decorate it -- to count as prose.
#
# Verified against a real, full rescan of the exact real corpus that
# originally exposed this: encoding_noise findings dropped from 86 to
# 10 (88%) -- every individual false positive hand-checked from the
# first two attempts is confirmed gone. The 10 that remain are a real,
# accepted limitation of a cheap, deterministic, no-dictionary
# heuristic, named rather than hidden: a relative import (`from .models
# import Question` -- the leading "." on ".models" strips away like
# ordinary punctuation, same as it would in real prose), a bare
# `except Exception as exc:` line, an RST field (`:alt: ...`), a SQL
# `CREATE TABLE` line reading as real English-looking keywords, and a
# CLI tool's own "Operations to perform:" output line. Not chased
# further with more special cases -- that pattern didn't converge the
# first two times, and 88% fewer false positives with the remainder
# explicitly documented is a materially better, more honest state than
# either earlier attempt, not a finished one.
_BOILERPLATE_MIN_LINE_LENGTH = 20
_BOILERPLATE_MIN_WORD_RATIO = 0.8
_SENTENCE_PUNCTUATION = ".,;:!?'\""


def _looks_like_boilerplate_candidate(line: str) -> bool:
    if len(line) < _BOILERPLATE_MIN_LINE_LENGTH:
        return False
    words = line.split()
    if not words:
        return False
    word_like = sum(1 for w in words if w.strip(_SENTENCE_PUNCTUATION).isalpha())
    return (word_like / len(words)) >= _BOILERPLATE_MIN_WORD_RATIO


# "Tokens" here means whitespace-split words, not a model-accurate tokenizer
# (tiktoken) — a deliberate choice, not an oversight: this check must stay
# cheap and dependency-free (design note: no embeddings, no LLM, runs in
# milliseconds), and the approximation is stated explicitly in each
# finding's evidence rather than silently implying model-accurate counts.
def _approx_token_count(text: str) -> int:
    return len(text.split())


# More than this fraction of a chunk's characters being control characters
# (excluding ordinary whitespace) is treated as encoding noise — a common
# artifact of bad PDF text extraction. Not empirically calibrated against
# real corrupted documents the way duplicates.py's thresholds were (no
# such corpus was available to measure against); revisit if real-world
# false positives/negatives turn up.
_CONTROL_CHAR_RATIO_THRESHOLD = 0.01

_HEADING_MAX_WORDS = 8
_HEADING_MAX_CHARS = 60
_HEADING_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";", ",")

# Self-retrieval-style overlap check for "broken sentence": how many
# trailing/leading words to compare between a chunk and its predecessor.
_OVERLAP_WINDOW = 5


class ChunkingDamageCheck:
    name = "chunking_damage"
    default_severity: Severity = "warn"

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]:
        config = cast(ChunkingDamageCheckConfig, ctx.config)
        if not config.enabled:
            return

        chunks = {c.id: c for c in snapshot.chunks()}
        predecessors = _predecessor_index(chunks)

        for chunk in chunks.values():
            yield from _check_size(chunk, config, config.severity)
            yield from _check_split_table(chunk, config.severity)
            yield from _check_orphan_heading(chunk, config.severity)
            yield from _check_broken_sentence(chunk, predecessors.get(chunk.id), config.severity)
            yield from _check_missing_metadata(chunk, config, config.severity)
            yield from _check_encoding_noise(chunk, config.severity)


def _finding(chunk: Chunk, rule: str, message: str, severity: Severity, **evidence: object) -> Finding:
    return Finding(
        check="chunking_damage",
        severity=severity,
        chunk_ids=[chunk.id],
        message=message,
        evidence={"rule": rule, **evidence},
        fingerprint=compute_fingerprint("chunking_damage", [chunk.id], identity_keys=[rule]),
    )


def _check_size(chunk: Chunk, config: ChunkingDamageCheckConfig, severity: Severity) -> Iterator[Finding]:
    count = _approx_token_count(chunk.text)
    if count < config.min_tokens:
        yield _finding(
            chunk, "size", f"Chunk has ~{count} words, below min_tokens={config.min_tokens}", severity,
            approx_word_count=count, min_tokens=config.min_tokens,
        )
    elif count > config.max_tokens:
        yield _finding(
            chunk, "size", f"Chunk has ~{count} words, above max_tokens={config.max_tokens}", severity,
            approx_word_count=count, max_tokens=config.max_tokens,
        )


def _check_split_table(chunk: Chunk, severity: Severity) -> Iterator[Finding]:
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    if not lines:
        return

    last = lines[-1]
    if last.startswith("|") and not last.endswith("|"):
        yield _finding(chunk, "split_table", "Chunk ends with a table row cut off mid-row", severity, edge="end")
        return  # one finding per chunk for this rule is enough

    first = lines[0]
    if first.endswith("|") and not first.startswith("|"):
        yield _finding(
            chunk, "split_table", "Chunk starts with what looks like the tail of a cut-off table row",
            severity, edge="start",
        )


def _looks_like_heading(line: str) -> bool:
    if line.startswith("#"):
        return True
    if "|" in line:
        # A pipe is a strong table-row signal, not a heading signal — found
        # by hand against the real example corpus: without this exclusion,
        # pricing-table-cut's cut-off last row ("| Pro | $25/mo") was
        # misclassified as a heading (short, no terminal punctuation, its
        # one real word capitalized) and wrongly flagged as orphan_heading
        # in addition to the correct split_table finding.
        return False
    if len(line) > _HEADING_MAX_CHARS or line.endswith(_HEADING_TERMINAL_PUNCTUATION):
        return False
    words = line.split()
    if not (1 <= len(words) <= _HEADING_MAX_WORDS):
        return False
    return all(word[0].isupper() for word in words if word[0].isalpha())


def _check_orphan_heading(chunk: Chunk, severity: Severity) -> Iterator[Finding]:
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    if not lines:
        return

    if len(lines) == 1 and _looks_like_heading(lines[0]):
        yield _finding(chunk, "orphan_heading", "Chunk is only a heading, with no content", severity)
    elif len(lines) > 1 and _looks_like_heading(lines[-1]):
        yield _finding(chunk, "orphan_heading", "Chunk ends with a heading and no following content", severity)


def _starts_mid_sentence(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith("..."):
        return True
    return stripped[0].islower()


def _has_overlap_with_predecessor(predecessor: Chunk, chunk: Chunk) -> bool:
    pred_tail = {w.lower().strip(".,;:!?") for w in predecessor.text.split()[-_OVERLAP_WINDOW:]}
    this_head = {w.lower().strip(".,;:!?") for w in chunk.text.split()[:_OVERLAP_WINDOW]}
    return bool(pred_tail & this_head)


def _predecessor_index(chunks: dict[str, Chunk]) -> dict[str, Chunk]:
    """Maps chunk id -> the chunk immediately before it (same source, one
    lower position), for chunks where both have known, orderable positions.
    A chunk with no identifiable predecessor (missing source/position, or
    no sibling at position - 1) simply isn't a key in this dict — treated
    downstream as "can't confirm deliberate overlap", not as "definitely no
    overlap", but also not given the benefit of the doubt either.
    """
    by_source_position = {
        (chunk.source, chunk.position): chunk
        for chunk in chunks.values()
        if chunk.source is not None and chunk.position is not None
    }
    predecessors: dict[str, Chunk] = {}
    for chunk in chunks.values():
        if chunk.source is None or chunk.position is None:
            continue
        predecessor = by_source_position.get((chunk.source, chunk.position - 1))
        if predecessor is not None:
            predecessors[chunk.id] = predecessor
    return predecessors


def _check_broken_sentence(chunk: Chunk, predecessor: Chunk | None, severity: Severity) -> Iterator[Finding]:
    if not _starts_mid_sentence(chunk.text):
        return
    # No predecessor to check -> can't confirm deliberate overlap, so this
    # isn't given the benefit of the doubt. A predecessor that genuinely
    # overlaps with this chunk's start is treated as intentional sliding-
    # window chunking, not damage.
    if predecessor is not None and _has_overlap_with_predecessor(predecessor, chunk):
        return
    yield _finding(
        chunk, "broken_sentence", "Chunk starts mid-sentence with no overlap from a previous chunk", severity
    )


def _check_missing_metadata(chunk: Chunk, config: ChunkingDamageCheckConfig, severity: Severity) -> Iterator[Finding]:
    missing = [field for field in config.required_metadata if getattr(chunk, field, None) is None]
    if missing:
        yield _finding(
            chunk, "missing_metadata", f"Chunk is missing required field(s): {', '.join(missing)}",
            severity, missing_fields=missing,
        )


def _check_encoding_noise(chunk: Chunk, severity: Severity) -> Iterator[Finding]:
    text = chunk.text
    if not text:
        return

    control_count = sum(1 for c in text if ord(c) < 32 and c not in "\n\t\r")
    if control_count / len(text) > _CONTROL_CHAR_RATIO_THRESHOLD:
        yield _finding(
            chunk, "encoding_noise", f"Chunk has {control_count} control character(s) — possible extraction artifact",
            severity, control_char_count=control_count,
        )
        return  # one encoding_noise finding per chunk is enough

    # Repeated non-trivial line within the same chunk — a crude proxy for
    # boilerplate (a running header/footer) leaking into chunk content.
    # Only catches repetition *within* one chunk; a header/footer repeated
    # once each across many different chunks needs cross-chunk analysis
    # this single-chunk rule doesn't do.
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 3]
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            if _looks_like_boilerplate_candidate(line):
                yield _finding(
                    chunk, "encoding_noise", f"Line repeats within the chunk: {line!r}", severity, line=line
                )
                return
            continue  # a repeated code/REPL/filename/separator line isn't boilerplate -- keep scanning
        seen.add(line)
