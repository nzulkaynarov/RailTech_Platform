"""Рендер не ходит в сеть и в файловую систему, а документ не берёт системные шрифты.

Контейнер тестов запущен с --network none, но проверка не опирается на это: fetcher отклоняет адрес до любого открытия.
"""

from __future__ import annotations

import pytest
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

from rt_docs.css import _font_faces
from rt_docs.errors import BodyError
from rt_docs.fetcher import ResourcePolicy
from rt_docs.model import Layout
from rt_docs.pdf import SafeURLFetcher, render_html_unsafe_for_tests, render_pdf
from tests import samples
from tests.pdf.pdfcheck import fonts, pages

ATTACK = f"""<html><head>
<link rel="stylesheet" href="http://127.0.0.1:9/evil.css">
<style>
@import url("file:///etc/hostname");
{_font_faces()}
body {{ font-family: "RT Doc Sans"; background: url("https://example.org/track.png"); }}
</style></head><body>
<p>Текст</p>
<img src="file:///etc/passwd">
<img src="http://169.254.169.254/latest/meta-data/">
<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">
<object data="file:///etc/shadow"></object>
</body></html>"""


def test_file_and_network_urls_are_blocked_and_reported() -> None:
    pdf, blocked = render_html_unsafe_for_tests(ATTACK)
    assert pdf.startswith(b"%PDF")
    assert "file:///etc/passwd" in blocked
    assert "http://169.254.169.254/latest/meta-data/" in blocked
    assert "http://127.0.0.1:9/evil.css" in blocked
    assert "https://example.org/track.png" in blocked
    assert any(url.startswith("data:image/svg+xml") for url in blocked)
    assert "file:///etc/hostname" in blocked  # @import в начале CSS — действующее правило, адрес отклонён
    assert "file:///etc/shadow" in blocked  # <object data>
    assert "Текст" in pages(pdf)[0].text


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://example.org/", "ftp://example.org/x"])
def test_fetcher_never_reaches_urllib_handlers(url: str) -> None:
    fetcher = SafeURLFetcher(ResourcePolicy())
    with pytest.raises(ValueError, match="not allowed"):
        fetcher.fetch(url)
    assert fetcher.policy.blocked == [url]


SYSTEM_FONT_HTML = f"""<html><head><style>{_font_faces()}
p {{ font-family: "DejaVu Sans", "RT Doc Sans"; }}</style></head><body><p>Системный шрифт?</p></body></html>"""


def test_system_fonts_are_invisible_to_the_document() -> None:
    pdf, _ = render_html_unsafe_for_tests(SYSTEM_FONT_HTML)
    used = fonts(pdf)
    assert used and not [name for name in used if "DejaVu" in name], used


def test_control_stock_weasyprint_would_take_the_system_font() -> None:
    """Контроль: без изоляции тот же HTML берёт DejaVu из образа — значит, тест выше что-то проверяет."""
    policy = ResourcePolicy()
    pdf = HTML(string=SYSTEM_FONT_HTML, url_fetcher=SafeURLFetcher(policy)).write_pdf(font_config=FontConfiguration())
    assert [name for name in fonts(pdf) if "DejaVu" in name]


def test_document_with_logo_renders_without_blocked_resources() -> None:
    result = render_pdf(
        samples.letter_short(), letterhead=samples.LETTERHEAD, layout=Layout.LETTER, values=samples.VALUES
    )
    assert result.blocked_urls == ()


def test_block_data_with_raw_html_never_reaches_the_renderer() -> None:
    evil = [{"type": "_block", "code": 'doc.x"><img src="file:///etc/passwd">', "content": []}]
    with pytest.raises(BodyError):
        render_pdf(
            samples.invoice(), letterhead=samples.LETTERHEAD, layout=Layout.COMMERCIAL, blocks={"doc.items_table": evil}
        )
