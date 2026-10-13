"""Unit tests for the SSTI-safe placeholder engine + HTML sanitiser («Документы 2.0»).

Pure-unit (no DB): the module never touches the ORM — it substitutes `{{code}}`
tokens against a whitelist of resolvers and sanitises template bodies with a stdlib
allowlist. The two security invariants under test:
  1. substituted VALUES are always HTML-escaped (no stored-XSS via deal/company data);
  2. template BODIES keep only allowlisted tags/attributes (script/on*/javascript: gone).
"""

from types import SimpleNamespace

from crm.services.document_placeholders import (
    PLACEHOLDER_CATALOG,
    PLACEHOLDER_GROUPS,
    RESOLVERS,
    PlaceholderContext,
    extract_placeholders,
    render_from_values,
    render_template,
    sanitize_template_html,
)


def _ctx(**overrides):
    company = SimpleNamespace(name="ООО Ромашка", inn="1234567890", legal_address="г. Ташкент, ул. 1")
    counterparty = SimpleNamespace(name="Покупатель", inn="777")
    deal = SimpleNamespace(id=42, title="Поставка рельсов", company_id=99, company=counterparty)
    user = SimpleNamespace(email="s@ex.uz", get_full_name=lambda: "Иван Продавцов")
    base = dict(company=company, deal=deal, contact=None, quote=None, contract=None, user=user)
    base.update(overrides)
    return PlaceholderContext(**base)


# ── extract_placeholders ─────────────────────────────────────────────────────


def test_extract_dedupes_and_preserves_order():
    body = "{{company.name}} — {{deal.number}} — {{company.name}} — {{today}}"
    assert extract_placeholders(body) == ["company.name", "deal.number", "today"]


def test_extract_handles_whitespace_and_empty():
    assert extract_placeholders("{{  company.name  }}") == ["company.name"]
    assert extract_placeholders("") == []
    assert extract_placeholders(None) == []


# ── render_template: whitelist resolution ────────────────────────────────────


def test_known_placeholders_resolve():
    html, values, warnings = render_template("Компания {{company.name}}, сделка {{deal.number}}", _ctx())
    assert "ООО Ромашка" in html
    assert "#42" in html
    assert values["company.name"] == "ООО Ромашка"
    assert warnings == []


def test_unknown_placeholder_left_verbatim_and_warned():
    html, values, warnings = render_template("Секрет {{settings.SECRET_KEY}} тут", _ctx())
    assert "{{settings.SECRET_KEY}}" in html  # left as-is, NOT evaluated (no SSTI)
    assert "settings.SECRET_KEY" in warnings
    assert "settings.SECRET_KEY" not in values


def test_today_resolver_present():
    html, values, _ = render_template("{{today}}", _ctx())
    assert values["today"]
    assert "{{today}}" not in html


def test_missing_context_object_yields_empty_not_crash():
    html, values, warnings = render_template("Q:{{quote.number}}:", _ctx(quote=None))
    assert "Q::" in html
    assert values["quote.number"] == ""


# ── SECURITY: substituted values are HTML-escaped ────────────────────────────


def test_value_with_markup_is_escaped():
    evil = SimpleNamespace(name="<script>alert(1)</script>", inn="1", legal_address="x")
    html, _values, _ = render_template("{{company.name}}", _ctx(company=evil))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_from_values_also_escapes():
    out = render_from_values("{{deal.title}}", {"deal.title": "<img src=x onerror=alert(1)>"})
    assert "<img" not in out
    assert "&lt;img" in out


# ── SECURITY: sanitize_template_html allowlist ───────────────────────────────


def test_sanitizer_drops_script_content():
    out = sanitize_template_html("<p>ok</p><script>steal()</script>")
    assert "steal" not in out
    assert "<script>" not in out
    assert "<p>ok</p>" in out


def test_sanitizer_strips_event_handlers():
    out = sanitize_template_html('<p onclick="x()">текст</p>')
    assert "onclick" not in out
    assert "текст" in out


def test_sanitizer_drops_javascript_href_but_keeps_tag():
    out = sanitize_template_html('<a href="javascript:alert(1)">клик</a>')
    assert "javascript:" not in out
    assert "клик" in out


def test_sanitizer_keeps_safe_href():
    out = sanitize_template_html('<a href="https://railtech.uz">сайт</a>')
    assert 'href="https://railtech.uz"' in out


def test_sanitizer_allows_data_png_on_img():
    out = sanitize_template_html('<img src="data:image/png;base64,iVBORw0KGgo=" alt="logo">')
    assert "data:image/png;base64," in out


def test_sanitizer_drops_data_svg_on_img():
    # data:image/svg+xml can carry <script>/onload — must be dropped even on <img> (A4/m5).
    out = sanitize_template_html('<img src="data:image/svg+xml,<svg onload=alert(1)>" alt="x">')
    assert "svg+xml" not in out
    assert "onload" not in out


def test_sanitizer_drops_data_on_href():
    out = sanitize_template_html('<a href="data:text/html,<script>alert(1)</script>">x</a>')
    assert "data:text/html" not in out


def test_sanitizer_strips_disallowed_tag_keeps_text():
    out = sanitize_template_html("<marquee>бегущая строка</marquee>")
    assert "<marquee>" not in out
    assert "бегущая строка" in out


def test_sanitizer_keeps_formatting_tags_and_tables():
    out = sanitize_template_html("<h2>Заголовок</h2><table><tr><td>ячейка</td></tr></table>")
    assert "<h2>" in out and "<table>" in out and "<td>" in out


def test_sanitizer_handles_empty():
    assert sanitize_template_html("") == ""
    assert sanitize_template_html(None) == ""


# ── T1-c: grouped catalogue ──────────────────────────────────────────────────


def test_placeholder_groups_split_company_from_dynamic():
    by_key = {group["key"]: group for group in PLACEHOLDER_GROUPS}
    # E1b: третья группа — структурные блоки юридических документов (договор / счёт / акт).
    assert set(by_key) == {"dynamic", "company", "legal_blocks"}
    company_codes = {item["code"] for item in by_key["company"]["items"]}
    dynamic_codes = {item["code"] for item in by_key["dynamic"]["items"]}
    legal_codes = {item["code"] for item in by_key["legal_blocks"]["items"]}
    # Every company.* placeholder is in the «уже в шапке» group and NONE leak into dynamic.
    assert company_codes == {"company.name", "company.inn", "company.address"}
    assert not any(code.startswith("company.") for code in dynamic_codes)
    # Legal tokens are exactly the doc.* namespace — and nothing else claims it.
    assert legal_codes and all(code.startswith("doc.") for code in legal_codes)
    assert not any(code.startswith("doc.") for code in dynamic_codes | company_codes)


def test_flat_catalog_derived_from_groups_and_matches_resolvers():
    from crm.services.document_blocks import preview_block_stubs

    # The flat projection covers exactly the grouped codes …
    grouped_codes = {item["code"] for group in PLACEHOLDER_GROUPS for item in group["items"]}
    assert set(PLACEHOLDER_CATALOG) == grouped_codes
    # … and every advertised code resolves: обычные — резолвером, doc.* — блочной машиной
    # (в превью — подписанной заглушкой). Фантомных плейсхолдеров в каталоге нет.
    doc_codes = {code for code in grouped_codes if code.startswith("doc.")}
    assert (grouped_codes - doc_codes) <= set(RESOLVERS)
    assert doc_codes <= set(preview_block_stubs())
