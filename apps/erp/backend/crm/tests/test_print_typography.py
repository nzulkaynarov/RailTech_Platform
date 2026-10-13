"""Print-typography wave (2026-07-27) — guards for the document font pipeline.

Root cause this wave closed: a CSS comment in _document_base.html contained `/* */` INSIDE
itself; CSS comments do not nest, so the comment closed early and the garbage tail killed the
`--font-main` declaration — every PDF silently rendered in WeasyPrint's default serif,
ignoring the seller's font choice (owner: «кривые шрифты»). Text-level assertions can't catch
this (the declaration text was present but unparseable), so the guard here PARSES the CSS.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import tinycss2
from django.template.loader import render_to_string

from crm.services.documents.brand import _FONT_STACKS

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_ROOTS = [_BACKEND_ROOT / "crm" / "templates", _BACKEND_ROOT / "templates"]


def _base_ctx(font_key: str) -> dict:
    return {
        "font_stack": _FONT_STACKS[font_key],
        "seller": SimpleNamespace(
            name="ООО «Продавец»", inn="123456789", legal_address="г. Ташкент", phone="", email="s@x.uz"
        ),
        "seller_profile": None,
        "seller_logo_url": None,
        "company": SimpleNamespace(name="ООО «Клиент»", inn="", legal_address="", contact_person=""),
        "is_demo": False,
    }


def _root_declarations(html: str) -> dict:
    """The :root custom properties as ACTUALLY PARSED by a CSS parser (tinycss2 — the same
    tokenizer family WeasyPrint uses), not as raw text. A broken comment upstream makes a
    declaration vanish here even though the text looks fine."""
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    rules = tinycss2.parse_stylesheet(style, skip_whitespace=True, skip_comments=True)
    for rule in rules:
        if rule.type == "qualified-rule" and tinycss2.serialize(rule.prelude).strip() == ":root":
            decls = tinycss2.parse_declaration_list(rule.content, skip_whitespace=True, skip_comments=True)
            return {d.lower_name: tinycss2.serialize(d.value).strip() for d in decls if d.type == "declaration"}
    return {}


@pytest.mark.parametrize("font_key,expected_family", [("sans", "Inter"), ("serif", "PT Serif")])
def test_font_main_survives_css_parsing(font_key, expected_family):
    html = render_to_string("crm/_document_base.html", _base_ctx(font_key))
    decls = _root_declarations(html)
    assert "--font-main" in decls, "the --font-main declaration was eaten by a CSS parse error"
    assert expected_family in decls["--font-main"]
    assert "--accent" in decls  # the rest of the token block survived too


def test_no_nested_css_comments_in_any_template():
    """CSS comments do not nest: `/* … /* … */` closes at the FIRST `*/` and the tail becomes
    garbage that can kill following declarations. Scan every template's inline CSS for it."""
    offenders = []
    for root in _TEMPLATE_ROOTS:
        for path in root.rglob("*.html"):
            text = path.read_text(errors="ignore")
            for match in re.finditer(r"/\*.*?\*/", text, re.S):
                if "/*" in match.group(0)[2:-2]:
                    offenders.append(f"{path}:{text[: match.start()].count(chr(10)) + 1}")
    assert offenders == [], f"nested CSS comments (they close early and corrupt the CSS): {offenders}"


def test_registration_footer_prints_seller_requisites():
    """The ADZ-class multi-column footer prints the seller's registration line on every page;
    a custom footer_text keeps overriding it entirely (pre-wave behavior)."""
    ctx = _base_ctx("sans")
    footer_markup = render_to_string("crm/_document_base.html", ctx).split('class="footer"')[1]
    assert '<table class="footer-grid"' in footer_markup
    assert "ООО «Продавец»" in footer_markup
    assert "ИНН 123456789" in footer_markup

    ctx["seller_profile"] = SimpleNamespace(
        legal_name="",
        legal_address="",
        inn="",
        bank_details="",
        footer_text="Мой собственный подвал",
        show_bank_in_header=False,
        signatory_name="",
        signatory_position="",
    )
    footer_custom = render_to_string("crm/_document_base.html", ctx).split('class="footer"')[1]
    assert "Мой собственный подвал" in footer_custom
    assert '<table class="footer-grid"' not in footer_custom  # owner text replaces the auto grid
