"""Акт на общем генераторе rt_docs (план 2.6): тот же состав, подписанный — с кодом и QR проверки, проект — знаком."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from crm.models import Act, InvoiceItem
from crm.tests.test_invoice_rt_docs import _texts
from crm.tests.test_sign_draft_mark import _act, world  # noqa: F401 — общий мир продавца, сделки и договора


@pytest.fixture(autouse=True)
def _rt_docs(settings):
    settings.RT_DOCS_DOCUMENTS = ("invoice", "act")
    settings.CABINET_URL = "https://cabinet.example.test"


def _render(act: Act) -> dict:
    from rt_docs import pdf as rt_pdf

    from crm.services.billing import _render_act_pdf

    seen: dict = {}
    real = rt_pdf.render_pdf

    def spy(body, **kwargs):
        seen["body"], seen["kwargs"] = body, kwargs
        return real(body, **kwargs)

    with patch.object(rt_pdf, "render_pdf", spy):
        _render_act_pdf(act)
    act.refresh_from_db()
    act.pdf_file.open("rb")
    try:
        seen["pdf"] = act.pdf_file.read()
    finally:
        act.pdf_file.close()
    nodes = [seen["body"]["doc"], *[n for block in seen["kwargs"]["blocks"].values() for n in block]]
    seen["text"] = " ".join(t for node in nodes for t in _texts(node))
    return seen


@pytest.mark.django_db
def test_issued_act_has_refs_items_totals_closing_and_signatures(world):  # noqa: F811
    act = _act(world, "ISSUED")
    InvoiceItem.objects.create(
        invoice=act.invoice,
        description="Комплект скрепления КБ-65",
        quantity=Decimal("2"),
        unit_price_excl_vat=Decimal("50"),
        line_total_excl_vat=Decimal("100"),
    )
    seen = _render(act)
    assert seen["pdf"].startswith(b"%PDF")
    text = seen["text"]
    for expected in (
        f"Сделка: #{act.deal_id}",
        "Счёт: INV-SIGN1-0001",
        "Настоящий Акт составлен",
        "Комплект скрепления КБ-65",
        "Итого к оплате:",
        "От Поставщика:",
        "От Покупателя:",
        "Подпись / дата",
    ):
        assert expected in text, expected
    meta = seen["kwargs"]["meta"]
    assert (meta.title, meta.number, meta.verification_code) == ("Акт приёма-передачи", "ACT-SIGN1-0001", None)
    assert seen["kwargs"]["draft"] is False


@pytest.mark.django_db
def test_signed_act_prints_the_signature_stamp_and_verification(world):  # noqa: F811
    act = _act(
        world,
        "ISSUED",
        verification_code="AB12CD34",
        signatory_name="Иванов И. И.",
        signatory_position="Директор",
        issuer_signed_at=timezone.now(),
    )
    seen = _render(act)
    text = seen["text"]
    assert "Иванов И. И." in text and "Официальная подпись" in text and "AB12CD34" in text
    meta = seen["kwargs"]["meta"]
    assert meta.verification_code == "AB12CD34"
    assert meta.verification_url == "https://cabinet.example.test/v/AB12CD34"


@pytest.mark.django_db
def test_draft_act_is_a_project_without_verification(world):  # noqa: F811
    seen = _render(_act(world, "DRAFT", verification_code="AB12CD34"))
    assert seen["kwargs"]["draft"] is True
    assert seen["kwargs"]["meta"].verification_code is None


@pytest.mark.django_db
def test_act_falls_back_to_django_templates_when_switched_off(world, settings):  # noqa: F811
    settings.RT_DOCS_DOCUMENTS = ("invoice",)
    from rt_docs import pdf as rt_pdf

    from crm.services.billing import _render_act_pdf

    with patch.object(rt_pdf, "render_pdf", side_effect=AssertionError("rt_docs не должен вызываться")):
        _render_act_pdf(_act(world, "ISSUED"))
