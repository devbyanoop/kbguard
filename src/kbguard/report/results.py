from pathlib import Path

from pydantic import BaseModel, Field

from kbguard.models import EvalResult, Finding, Snapshot


class ScanResults(BaseModel):
    """The one JSON-serializable structure combining a scan's snapshot
    metadata, health score, and findings (plus, from Week 3 on, eval
    results) into a single output artifact — spec section 11's "JSON
    results". pydantic, not dataclasses.asdict()/a hand-written to_dict():
    this is a genuine output boundary (written to disk, read back by
    `kbguard report`, potentially consumed by a client's own tooling),
    unlike models.py's Chunk/Finding/Snapshot, which stay plain dataclasses
    since nothing outside this process reads them directly. pydantic
    v2 handles those stdlib dataclasses as field types natively — no
    arbitrary_types_allowed needed, confirmed by hand before relying on it.
    """

    snapshot: Snapshot
    health: int
    findings: list[Finding] = Field(default_factory=list)
    eval_results: list[EvalResult] = Field(default_factory=list)

    def to_json(self, path: Path) -> None:
        # model_dump_json() preserves field declaration order (snapshot,
        # health, findings, eval_results) deterministically on every call —
        # confirmed by hand — so two reports from identical input produce
        # byte-identical JSON, which matters if this is ever committed to
        # version control and diffed.
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "ScanResults":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
