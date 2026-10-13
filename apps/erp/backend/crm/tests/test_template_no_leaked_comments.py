"""Regression guard: no multi-line Django ``{# #}`` comments in any template.

Django's template lexer matches ``{#.*?#}`` WITHOUT re.DOTALL, so a comment that spans
lines is never recognized — the ``{#`` opens with no ``#}`` on the same line and the whole
block is emitted VERBATIM into the rendered output. In a PDF/КП that means raw English
developer notes print for the client (incident: quote_pdf.html #375, swept #410/#411 but a
copy survived; found again 2026-07-26 on the prod КП QR block).

The fix is always ``{% comment %}…{% endcomment %}`` (multi-line safe) or a single-line
``{# … #}``. This test scans every template so the class of bug cannot reappear.
"""

import re
from pathlib import Path

# All template roots in the backend (app-level + project-level).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_DIRS = [
    _BACKEND_ROOT / "crm" / "templates",
    _BACKEND_ROOT / "templates",
]

# {#…#} on a single line is fine; the regex below (no DOTALL) only matches those. Anything
# with a stray {# that has no #} before the newline is the leaking multi-line form.
_SINGLE_LINE_COMMENT = re.compile(r"\{#.*?#\}")


def _leaked_multiline_comments(text: str) -> list[int]:
    """Return 1-based line numbers where a ``{#`` opens without a same-line ``#}``."""
    bad = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        without_ok = _SINGLE_LINE_COMMENT.sub("", line)
        if "{#" in without_ok:
            bad.append(lineno)
    return bad


def test_no_multiline_django_comments_in_templates():
    offenders = []
    for root in _TEMPLATE_DIRS:
        for path in root.rglob("*.html"):
            lines = _leaked_multiline_comments(path.read_text(encoding="utf-8"))
            offenders.extend(f"{path.relative_to(_BACKEND_ROOT)}:{ln}" for ln in lines)
    assert not offenders, (
        "Multi-line Django {# #} comments leak verbatim into rendered output — "
        "use {% comment %}…{% endcomment %} instead:\n  " + "\n  ".join(offenders)
    )
