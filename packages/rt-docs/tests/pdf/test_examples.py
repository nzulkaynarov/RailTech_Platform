"""Примеры тел контракта (packages/contracts/documents/examples) печатаются на демо-бланке."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rt_docs.contracts import contracts_dir
from rt_docs.model import DocumentMeta, Layout
from rt_docs.pdf import render_pdf
from tests import samples

LAYOUT = {
    "letter": Layout.LETTER,
    "letter.uz": Layout.LETTER,
    "contract": Layout.COMMERCIAL,
    "invoice": Layout.COMMERCIAL,
}


@pytest.mark.parametrize("path", sorted((contracts_dir() / "examples").glob("*.json")), ids=lambda p: p.stem)
def test_example_renders(path: Path) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    result = render_pdf(
        body,
        letterhead=samples.LETTERHEAD,
        layout=LAYOUT[path.stem],
        meta=DocumentMeta(title=path.stem, number="1"),
        values=samples.VALUES,
    )
    assert result.stats.pages >= 1
    assert result.blocked_urls == ()
    assert not [w for w in result.warnings if w.startswith(("code not in catalog", "characters missing"))]
