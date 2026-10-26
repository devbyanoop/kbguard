from pathlib import Path

import jinja2

from kbguard.ingest.snapshot import SnapshotReader
from kbguard.report.enrich import (
    category_breakdown,
    enrich_findings,
    executive_verdict,
    group_by_check,
    history_summary,
    top_findings,
)
from kbguard.report.results import ScanResults

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "report.html.j2"


def render_html(
    results: ScanResults,
    out_path: Path,
    reader: SnapshotReader | None = None,
    history: list[ScanResults] | None = None,
) -> None:
    """`reader` and `history` are optional specifically so every existing
    caller/test that only has a `ScanResults` still works unchanged —
    without a reader, findings render without a resolved source/snippet
    (the same bare-chunk-id view the report always had); without history,
    the trend tab just says there's nothing to compare against yet.
    """
    # autoescape=True: finding.message/evidence can contain text pulled
    # straight from the client's own documents, which this project treats
    # as untrusted — a chunk containing "<script>" must render as inert
    # text in the report, not execute, if someone opens report.html in a
    # browser. jinja2's own default is autoescape=False; it has to be
    # turned on explicitly here.
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATE_DIR), autoescape=True)
    template = env.get_template(_TEMPLATE_NAME)

    chunks_by_id = {c.id: c for c in reader.chunks()} if reader is not None else {}
    enriched = enrich_findings(results.findings, chunks_by_id)

    html = template.render(
        results=results,
        grouped_findings=group_by_check(enriched),
        breakdown=category_breakdown(results.findings),
        verdict=executive_verdict(results.findings),
        top_findings=top_findings(enriched),
        history=history_summary(history or [results]),
    )
    out_path.write_text(html, encoding="utf-8")
