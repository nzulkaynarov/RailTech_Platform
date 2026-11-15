"""Счёт на общем генераторе rt_docs (план 2.6): тот же состав, коммерческий макет, проект — знаком генератора."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from crm.models import Invoice, InvoiceItem
from crm.tests.test_sign_draft_mark import _invoice, world  # noqa: F401 — общий мир продавца, сделки и договора


def _texts(node) -> list[str]:
    if isinstance(node, dict):
        out = [node["text"]] if node.get("type") == "text" else []
        for key in ("content",):
            for child in node.get(key) or []:
                out += _texts(child)
        for party in (node.get("attrs") or {}).get("parties") or []:
            out += [str(v) for v in party.values() if isinstance(v, str)]
        return out
    return []


def _render(invoice: Invoice) -> dict:
    """Счёт через rt_docs: настоящий PDF, а ввод генератора — для проверки состава."""
    from rt_docs import pdf as rt_pdf

    from crm.services.billing import _render_invoice_pdf

    seen: dict = {}
    real = rt_pdf.render_pdf

    def spy(body, **kwargs):
        seen["body"], seen["kwargs"] = body, kwargs
        return real(body, **kwargs)

    with patch.object(rt_pdf, "render_pdf", spy):
        _render_invoice_pdf(invoice)
    invoice.refresh_from_db()
    invoice.pdf_file.open("rb")
    try:
        seen["pdf"] = invoice.pdf_file.read()
    finally:
        invoice.pdf_file.close()
    nodes = [seen["body"]["doc"], *[n for block in seen["kwargs"]["blocks"].values() for n in block]]
    seen["text"] = " ".join(t for node in nodes for t in _texts(node))
    return seen


@pytest.mark.django_db
def test_issued_invoice_has_parties_items_totals_and_payment_purpose(world):  # noqa: F811
    invoice = _invoice(world, "ISSUED", notes="Отгрузка после оплаты")
    InvoiceItem.objects.create(
        invoice=invoice,
        description="Комплект скрепления КБ-65",
        quantity=Decimal("2"),
        unit_price_excl_vat=Decimal("50"),
        line_total_excl_vat=Decimal("100"),
    )
    seen = _render(invoice)
    assert seen["pdf"].startswith(b"%PDF")
    text = seen["text"]
    for expected in (
        "Поставщик",
        "Плательщик",
        "Комплект скрепления КБ-65",
        "Итого к оплате:",
        "Платёжные реквизиты",
        "Оплата по счёту № INV-SIGN1-0001",
        "Отгрузка после оплаты",
        "Главный бухгалтер:",
    ):
        assert expected in text, expected
    meta = seen["kwargs"]["meta"]
    assert (meta.title, meta.number, seen["kwargs"]["draft"]) == ("Счёт на оплату", "INV-SIGN1-0001", False)
    assert seen["kwargs"]["layout"].value == "commercial"


@pytest.mark.django_db
def test_draft_invoice_is_a_project_without_number(world):  # noqa: F811
    seen = _render(_invoice(world, "DRAFT"))
    assert seen["kwargs"]["draft"] is True
    assert "Оплата по счёту" in seen["text"] and "Оплата по счёту №" not in seen["text"]


@pytest.mark.django_db
def test_invoice_falls_back_to_django_templates_when_switched_off(world, settings):  # noqa: F811
    settings.RT_DOCS_DOCUMENTS = ()
    from rt_docs import pdf as rt_pdf

    from crm.services.billing import _render_invoice_pdf

    with patch.object(rt_pdf, "render_pdf", side_effect=AssertionError("rt_docs не должен вызываться")):
        _render_invoice_pdf(_invoice(world, "ISSUED"))
