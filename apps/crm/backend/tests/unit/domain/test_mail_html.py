"""HTML письма: санитизация по белому списку и текст из HTML (W18A-P2-4). Адреса — вымышленные."""

import base64
import re

import pytest

from app.domain.mail_html import InlineImage, html_text_parts, sanitize_html

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _clean(html: str, inline: dict[str, InlineImage] | None = None) -> str:
    result = sanitize_html(html, inline)
    assert result is not None
    return result.html


# --- XSS: вектор → подстроки, которых в результате быть не должно ------------------------------
XSS: list[tuple[str, str, list[str]]] = [
    ("script", "<p>a</p><script>alert(1)</script>", ["<script", "alert(1)"]),
    ("script-case", "<ScRiPt>alert(1)</sCrIpT><p>a</p>", ["script", "alert"]),
    ("img-onerror", '<img src="x" onerror="alert(1)">', ["onerror", "alert"]),
    ("onclick", '<p onclick="alert(1)">a</p>', ["onclick", "alert"]),
    ("onmouseover-a", '<a href="https://a.test" onmouseover="alert(1)">a</a>', ["onmouseover"]),
    ("href-javascript", '<a href="javascript:alert(1)">a</a>', ["javascript", "alert"]),
    ("href-javascript-case", '<a href="JaVaScRiPt:alert(1)">a</a>', ["javascript", "alert"]),
    ("href-javascript-tab", '<a href="java\tscript:alert(1)">a</a>', ["alert"]),
    ("href-entity", '<a href="&#106;avascript:alert(1)">a</a>', ["alert"]),
    ("href-data", '<a href="data:text/html,<script>alert(1)</script>">a</a>', ["data:", "alert"]),
    ("href-vbscript", '<a href="vbscript:msgbox(1)">a</a>', ["vbscript"]),
    ("href-cid", '<a href="cid:abc">a</a>', ["cid:"]),
    ("href-relative", '<a href="/admin/delete">a</a>', ["/admin"]),
    ("href-protocol-relative", '<a href="//evil.test/x">a</a>', ["evil.test"]),
    ("img-src-javascript", '<img src="javascript:alert(1)">', ["javascript", "alert"]),
    ("img-src-svg-data", '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">', ["svg"]),
    ("img-src-html-data", '<img src="data:text/html;base64,PHNjcmlwdD4=">', ["data:text"]),
    ("img-relative", '<img src="/api/v1/secret.png">', ["/api/"]),
    ("img-srcset", '<img src="https://a.test/1.png" srcset="https://b.test/2.png 2x">', ["srcset"]),
    ("svg-onload", "<svg onload=alert(1)><circle r=1></circle></svg>", ["svg", "onload", "alert"]),
    ("svg-script", "<svg><script>alert(1)</script></svg>", ["script", "alert"]),
    ("math", '<math><mi xlink:href="javascript:alert(1)">x</mi></math>', ["javascript", "alert"]),
    ("iframe", '<iframe src="https://evil.test"></iframe><p>a</p>', ["iframe", "evil.test"]),
    ("iframe-srcdoc", '<iframe srcdoc="<script>alert(1)</script>"></iframe>', ["iframe", "alert"]),
    ("object", '<object data="https://evil.test/x.swf"></object>', ["object", "evil.test"]),
    ("embed", '<embed src="https://evil.test/x.swf">', ["embed", "evil.test"]),
    (
        "form",
        '<form action="https://evil.test/steal"><input name="p"></form>',
        ["form", "evil.test"],
    ),
    ("input", '<input type="text" value="x" autofocus onfocus="alert(1)">', ["input", "onfocus"]),
    ("button-formaction", '<button formaction="https://evil.test">x</button>', ["formaction"]),
    ("textarea", "<textarea>x</textarea>", ["textarea"]),
    (
        "meta-refresh",
        '<meta http-equiv="refresh" content="0;url=https://evil.test">',
        ["meta", "evil"],
    ),
    ("base", '<base href="https://evil.test/"><a href="x">a</a>', ["<base", "evil.test"]),
    (
        "link-stylesheet",
        '<link rel="stylesheet" href="https://evil.test/a.css">',
        ["<link", "evil"],
    ),
    (
        "style-block",
        "<style>body{background:url(https://evil.test/t.gif)}</style><p>a</p>",
        ["<style", "evil"],
    ),
    ("style-import", '<style>@import "https://evil.test/a.css";</style>', ["import", "evil"]),
    ("style-expression", '<p style="width:expression(alert(1))">a</p>', ["expression", "alert"]),
    (
        "style-url-js",
        '<p style="background:url(javascript:alert(1))">a</p>',
        ["javascript", "alert"],
    ),
    (
        "style-url-remote",
        '<p style="background-image:url(https://evil.test/t.gif)">a</p>',
        ["evil"],
    ),
    ("style-url-escaped", '<p style="background:\\75rl(https://evil.test/t.gif)">a</p>', ["evil"]),
    ("style-behavior", '<p style="behavior:url(x.htc)">a</p>', ["behavior"]),
    ("style-moz-binding", '<p style="-moz-binding:url(x)">a</p>', ["binding"]),
    (
        "style-position-fixed",
        '<p style="position:fixed;top:0;left:0;width:9999px">a</p>',
        ["position", "fixed"],
    ),
    (
        "style-comment",
        '<p style="color:red;/* x */background:u/**/rl(https://evil.test)">a</p>',
        ["evil"],
    ),
    (
        "table-background",
        '<table background="https://evil.test/t.gif"><tr><td>a</td></tr></table>',
        ["evil"],
    ),
    (
        "td-background",
        '<table><tr><td background="https://evil.test/t.gif">a</td></tr></table>',
        ["evil"],
    ),
    ("body-onload", '<body onload="alert(1)"><p>a</p></body>', ["onload", "alert"]),
    ("template", "<template><script>alert(1)</script></template>", ["template", "alert"]),
    ("noscript", "<noscript><img src=x onerror=alert(1)></noscript>", ["noscript", "alert"]),
    (
        "comment-conditional",
        "<!--[if mso]><script>alert(1)</script><![endif]--><p>a</p>",
        ["alert", "<!--"],
    ),
    ("nested-broken", "<<script>script>alert(1)<</script>/script>", ["<script", "alert(1)"]),
    (
        "video-poster",
        '<video poster="https://evil.test/p.png"><source src="x"></video>',
        ["video", "evil"],
    ),
    ("audio", '<audio src="https://evil.test/a.mp3" autoplay></audio>', ["audio", "evil"]),
    ("id-clobber", '<p id="location" name="cookie">a</p>', ["id=", "name="]),
]


@pytest.mark.parametrize(("html", "forbidden"), [pytest.param(h, f, id=i) for i, h, f in XSS])
def test_xss_vectors_are_removed(html: str, forbidden: list[str]) -> None:
    result = sanitize_html(f"<p>начало</p>{html}<p>конец</p>")
    assert result is not None
    low = result.html.lower()
    for item in forbidden:
        assert item.lower() not in low, (item, result.html)
    assert "начало" in result.html
    assert "конец" in result.html
    # ни один «живой» обработчик события и ни один исходящий адрес без клика не остаётся
    assert not re.search(r"\son\w+\s*=", low)
    assert not re.search(r"\ssrc\s*=\s*\"https?:", low)


def test_formatting_is_kept() -> None:
    html = (
        '<table width="600" cellpadding="0" bgcolor="#eeeeee"><tr><td align="center" valign="top" '
        'colspan="2" style="color:#112233;font-size:14px;padding:8px;text-align:center">'
        '<b>Жирный</b> <i>курсив</i> <a href="https://site.test/a?x=1&y=2" title="t">ссылка</a>'
        '</td></tr></table><ul><li>раз</li></ul><h2>Заголовок</h2><font color="red">f</font>'
    )
    out = _clean(html)
    for part in (
        "<table",
        'width="600"',
        'bgcolor="#eeeeee"',
        'colspan="2"',
        "color:#112233",
        "font-size:14px",
        "<b>Жирный</b>",
        "<i>курсив</i>",
        'href="https://site.test/a?x=1&amp;y=2"',
        "<li>раз</li>",
        "<h2>Заголовок</h2>",
        '<font color="red">',
    ):
        assert part in out, part


def test_links_open_in_new_tab_without_opener() -> None:
    out = _clean('<a href="https://site.test/">a</a><a href="mailto:a@example.test">m</a>')
    assert out.count('target="_blank"') == 2
    assert out.count("noopener") == 2
    assert 'href="mailto:a@example.test"' in out


def test_unknown_style_properties_are_dropped_known_kept() -> None:
    out = _clean('<p style="color:red;position:absolute;z-index:9;margin:0">a</p>')
    assert "color:red" in out
    assert "margin:0" in out
    assert "position" not in out
    assert "z-index" not in out


def test_only_quote_classes_survive() -> None:
    out = _clean(
        '<div class="gmail_quote evil other"><blockquote class="gmail_quote">q</blockquote></div>'
    )
    assert 'class="gmail_quote"' in out
    assert "evil" not in out


# --- Картинки ----------------------------------------------------------------------------------
def test_remote_images_have_no_src_until_click() -> None:
    result = sanitize_html(
        '<img src="https://track.test/p.gif?u=1&amp;v=2" width="1" height="1" alt="">'
        '<img src="http://cdn.test/logo.png" alt="Лого">'
    )
    assert result is not None
    assert result.remote_images == 2
    assert not re.search(r"\ssrc=", result.html)
    assert 'data-rt-src="https://track.test/p.gif?u=1&amp;v=2"' in result.html
    assert 'data-rt-src="http://cdn.test/logo.png"' in result.html


def test_cid_image_is_inlined_from_attachment() -> None:
    inline = {"logo@mail.test": InlineImage("image/png", PNG)}
    result = sanitize_html('<img src="cid:logo@mail.test" alt="Лого">', inline)
    assert result is not None
    assert result.missing_images == 0
    assert f'src="data:image/png;base64,{base64.b64encode(PNG).decode()}"' in result.html


def test_cid_lookup_ignores_case_and_brackets() -> None:
    inline = {"logo@mail.test": InlineImage("image/png", PNG)}
    result = sanitize_html('<img src="cid:Logo@Mail.test">', inline)
    assert result is not None
    assert "data:image/png;base64," in result.html


@pytest.mark.parametrize(
    "inline",
    [
        pytest.param({}, id="no-attachment"),
        pytest.param({"other": InlineImage("image/png", PNG)}, id="other-cid"),
        pytest.param({"logo": InlineImage("image/svg+xml", b"<svg onload=alert(1)/>")}, id="svg"),
        pytest.param({"logo": InlineImage("application/pdf", b"%PDF")}, id="not-image"),
        pytest.param({"logo": InlineImage("image/png", b"x" * 600_000)}, id="too-big"),
    ],
)
def test_cid_without_usable_attachment_is_placeholder(inline: dict[str, InlineImage]) -> None:
    result = sanitize_html('<img src="cid:logo" alt="Лого">', inline)
    assert result is not None
    assert result.missing_images == 1
    assert "data-rt-missing" in result.html
    assert " src=" not in result.html
    assert "svg" not in result.html


def test_inline_budget_is_shared_between_images() -> None:
    big = InlineImage("image/png", b"x" * 300_000)
    inline = {"a": big, "b": big, "c": big, "d": big}
    html = "".join(f'<img src="cid:{k}">' for k in inline)
    result = sanitize_html(html, inline)
    assert result is not None
    assert result.missing_images >= 1
    assert result.html.count("data:image/png") == 3


def test_data_image_kept_only_for_raster_types() -> None:
    good = f"data:image/png;base64,{base64.b64encode(PNG).decode()}"
    result = sanitize_html(f'<img src="{good}"><img src="data:image/svg+xml;base64,AAAA">')
    assert result is not None
    assert good in result.html
    assert result.missing_images == 1


# --- Размеры -----------------------------------------------------------------------------------
def test_oversized_html_is_not_stored() -> None:
    assert sanitize_html("<p>" + "я" * 900_000 + "</p>") is None


def test_empty_html_is_none() -> None:
    assert sanitize_html("") is None
    assert sanitize_html("<script>alert(1)</script>") is None
    assert sanitize_html("   <!-- x -->  ") is None


# --- Текст из HTML ------------------------------------------------------------------------------
def test_text_parts_plain_markup() -> None:
    main, quoted = html_text_parts(
        "<html><head><title>T</title><style>p{}</style></head><body>"
        "<p>Первая&nbsp;строка</p><div>Вторая<br>третья</div><script>x()</script></body></html>"
    )
    assert "T" not in main
    assert "x()" not in main
    assert [s for s in main.split("\n") if s.strip()] == ["Первая строка", "Вторая", "третья"]
    assert quoted == ""


def test_text_parts_table_cells_are_separated() -> None:
    main, _ = html_text_parts("<table><tr><td>Шпала</td><td>10 шт</td></tr></table>")
    assert "Шпала" in main
    assert "ШпалаК" not in main
    assert re.search(r"Шпала\s+10", main)


def test_text_parts_hidden_preheader_is_skipped() -> None:
    main, _ = html_text_parts(
        '<div style="display:none;max-height:0;overflow:hidden">Скрытый прехедер &zwnj;&nbsp;</div>'
        '<span style="mso-hide:all">тоже скрыто</span><p hidden>и это</p><p>Видимое</p>'
    )
    assert main.strip() == "Видимое"


@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            '<p>Ответ</p><div class="gmail_quote"><div class="gmail_attr">On Mon, A wrote:</div>'
            "<blockquote>Старый текст</blockquote></div>",
            id="gmail",
        ),
        pytest.param('<p>Ответ</p><blockquote type="cite">Старый текст</blockquote>', id="apple"),
        pytest.param('<p>Ответ</p><div class="yahoo_quoted">Старый текст</div>', id="yahoo"),
        pytest.param(
            '<p>Ответ</p><div class="moz-cite-prefix">A wrote:</div>'
            "<blockquote>Старый текст</blockquote>",
            id="thunderbird",
        ),
    ],
)
def test_text_parts_quote_goes_to_tail(html: str) -> None:
    main, quoted = html_text_parts(html)
    assert main.strip() == "Ответ"
    assert "Старый текст" in quoted


def test_text_parts_nested_quotes_and_unclosed_tags() -> None:
    main, quoted = html_text_parts(
        "<p>Ответ<blockquote>1<blockquote>2</blockquote>ещё 1</blockquote><p>после"
    )
    assert "Ответ" in main
    assert "после" in main
    assert "ещё 1" in quoted
    assert "2" in quoted
