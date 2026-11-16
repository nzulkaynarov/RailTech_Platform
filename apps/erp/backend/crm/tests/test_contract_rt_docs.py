"""Договор на общем генераторе rt_docs (план 2.6): статьи по образцу, спецификация, реквизиты и подписи сторон."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from sales.models import QuoteItem

from crm.models import Contract
from crm.tests.test_invoice_rt_docs import _texts
from crm.tests.test_sign_draft_mark import _contract, world  # noqa: F401 — общий мир продавца, сделки и КП


@pytest.fixture(autouse=True)
def _rt_docs(settings):
    settings.RT_DOCS_DOCUMENTS = ("invoice", "act", "contract")
    settings.CABINET_URL = "https://cabinet.example.test"


def _render(contract: Contract) -> dict:
    from rt_docs import pdf as rt_pdf

    from crm.services.contracts import _render_contract_pdf

    seen: dict = {}
    real = rt_pdf.render_pdf

    def spy(body, **kwargs):
        seen["body"], seen["kwargs"] = body, kwargs
        return real(body, **kwargs)

    with patch.object(rt_pdf, "render_pdf", spy):
        _render_contract_pdf(contract)
    contract.refresh_from_db()
    contract.pdf_file.open("rb")
    try:
        seen["pdf"] = contract.pdf_file.read()
    finally:
        contract.pdf_file.close()
    nodes = [seen["body"]["doc"], *[n for block in seen["kwargs"]["blocks"].values() for n in block]]
    seen["text"] = " ".join(t for node in nodes for t in _texts(node))
    return seen


@pytest.mark.django_db
def test_contract_has_articles_specification_requisites_and_signatures(world):  # noqa: F811
    QuoteItem.objects.create(
        quote=world["quote"], imported_raw_name="Колодка тормозная", quantity=2, frozen_base_price=Decimal("50")
    )
    seen = _render(_contract(world, "PENDING_CLIENT", notes="Поставка двумя партиями"))
    assert seen["pdf"].startswith(b"%PDF")
    text = seen["text"]
    for expected in (
        "Предмет договора",
        "Приложение № 1. Спецификация",
        "Колодка тормозная",
        "Всего, сум",
        "НДС по ставке 12%",
        "Реквизиты и подписи Сторон",
        "ИНН: 7700000001",
        "г. Ташкент, ",
        "От Поставщика:",
        "От Покупателя:",
        "Поставка двумя партиями",
    ):
        assert expected in text, expected
    meta = seen["kwargs"]["meta"]
    assert (meta.kind_label, meta.number, seen["kwargs"]["draft"]) == ("Договор поставки", "CT-SIGN1-0001", False)
    assert meta.window is False and [row.role for row in meta.info[:2]] == ["number", "date"]


@pytest.mark.django_db
def test_signed_contract_prints_stamp_and_verification(world):  # noqa: F811
    seen = _render(
        _contract(
            world,
            "PENDING_CLIENT",
            verification_code="CT12CD34",
            signatory_name="Иванов И. И.",
            signatory_position="Директор",
            signed_at=timezone.now(),
        )
    )
    assert "Официальная подпись" in seen["text"] and "CT12CD34" in seen["text"]
    meta = seen["kwargs"]["meta"]
    assert meta.verification_url == "https://cabinet.example.test/v/CT12CD34"


@pytest.mark.django_db
def test_draft_contract_is_a_project(world):  # noqa: F811
    seen = _render(_contract(world, "DRAFT"))
    assert seen["kwargs"]["draft"] is True
    assert seen["kwargs"]["meta"].verification_code is None


@pytest.mark.django_db
def test_contract_falls_back_to_django_templates_when_switched_off(world, settings):  # noqa: F811
    settings.RT_DOCS_DOCUMENTS = ("invoice", "act")
    from rt_docs import pdf as rt_pdf

    from crm.services.contracts import _render_contract_pdf

    with patch.object(rt_pdf, "render_pdf", side_effect=AssertionError("rt_docs не должен вызываться")):
        _render_contract_pdf(_contract(world, "PENDING_CLIENT"))
