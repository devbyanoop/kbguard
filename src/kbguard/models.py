import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class Chunk:
    id: str
    text: str
    # no default: adapters must pass embedding=None explicitly rather than
    # silently omitting it, so "no vector" is always a deliberate value.
    embedding: list[float] | None
    metadata: dict[str, Any] = field(default_factory=dict)
    # standard fields, filled in from `metadata` by ingest/metadata.py's mapper:
    source: str | None = None          # document id or path
    position: int | None = None        # order within source
    version: str | None = None
    updated_at: datetime | None = None
    title: str | None = None


Severity = Literal["info", "warn", "error"]


def compute_fingerprint(check: str, chunk_ids: Sequence[str], identity_keys: Sequence[str] = ()) -> str:
    """Stable id for a Finding, used by `diff` (new/resolved/unchanged) and
    kbguard.ignore.yaml suppressions. Built only from values that don't change
    between re-scans of the same underlying data: the check name, the chunk
    ids (these come from the vector store, not from this run), and any
    evidence keys the check says define the finding's identity (e.g.
    chunking_damage passes ["rule"] so two different rules flagging the same
    chunk get two fingerprints, not one).
    """
    payload = ":".join([check, *sorted(chunk_ids), *sorted(identity_keys)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Finding:
    check: str                         # "duplicates", "contradictions", ...
    severity: Severity
    chunk_ids: list[str]
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    # Each check computes this itself via compute_fingerprint() when it knows
    # which evidence keys matter for identity — not auto-derived here, since
    # that varies per check.
    fingerprint: str = ""


@dataclass
class EvalResult:
    question_id: str
    metric: str                        # "recall@5", "faithfulness", ...
    value: float
    passed: bool
    cause: Literal["content", "retrieval", "generation", "none"] = "none"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Snapshot:
    id: str
    collection: str
    adapter: str
    created_at: datetime
    chunk_count: int
    path: str                          # .kbguard/snapshots/<id>/
