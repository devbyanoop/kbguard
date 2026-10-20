from pathlib import Path

import jinja2

from kbguard.report.results import ScanResults

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "report.html.j2"


def render_html(results: ScanResults, out_path: Path) -> None:
    # autoescape=True: finding.message/evidence can contain text pulled
    # straight from the client's own documents, which this project treats
    # as untrusted — a chunk containing "<script>" must render as inert
    # text in the report, not execute, if someone opens report.html in a
    # browser. jinja2's own default is autoescape=False; it has to be
    # turned on explicitly here.
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATE_DIR), autoescape=True)
    template = env.get_template(_TEMPLATE_NAME)
    html = template.render(results=results)
    out_path.write_text(html, encoding="utf-8")
