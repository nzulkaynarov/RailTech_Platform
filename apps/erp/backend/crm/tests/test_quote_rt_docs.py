"""КП на общем генераторе rt_docs (план 2.6): письмо-предложение с проекцией для клиента, разделы, примечания,
опциональные позиции вне итога; проект — знаком, подписанное — кодом и QR проверки."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from crm.models import Quote, QuoteItem
from crm.tests.test_invoice_rt_docs import _texts
from crm.tests.test_sign_draft_mark import world  # noqa: F401 — общий мир продавца, сделки и КП


@pytest.fixture(autouse=True)
def _rt_docs(settings):
    settings.RT_DOCS_DOCUMENTS = ("invoice", "act", "contract", "quote")
    settings.CABINET_URL = "https://cabinet.example.test"


def _lines(quote: Quote) -> None:
    item = QuoteItem.DisplayType
    QuoteItem.objects.create(quote=quote, display_type=item.SECTION, imported_raw_name="Тормозная система")
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Колодка тормозная", mpn="KT-100", quantity=2, frozen_base_price=Decimal("50")
    )
    QuoteItem.objects.create(quote=quote, display_type=item.NOTE, imported_raw_name="Поставка партиями")
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Набор креплений", is_optional=True, quantity=1, frozen_base_price=Decimal("7")
    )
    quote.recalculate_totals()


def _render(quote: Quote) -> dict:
    from rt_docs import pdf as rt_pdf

    from crm.services.quotes import QuoteLifecycleService

    seen: dict = {}
    real = rt_pdf.render_pdf

    def spy(body, **kwargs):
        seen["body"], seen["kwargs"] = body, kwargs
        return real(body, **kwargs)

    with patch.object(rt_pdf, "render_pdf", spy):
        QuoteLifecycleService.generate_pdf(quote.id)
    quote.refresh_from_db()
    quote.pdf_file.open("rb")
    try:
        seen["pdf"] = quote.pdf_file.read()
    finally:
        quote.pdf_file.close()
    seen["text"] = " ".join(_texts(seen["body"]["doc"]))
    return seen


@pytest.mark.django_db
def test_quote_is_a_letter_with_sections_notes_and_optional_lines(world):  # noqa: F811
    _lines(world["quote"])
    seen = _render(world["quote"])
    assert seen["pdf"].startswith(b"%PDF")
    text = seen["text"]
    for expected in (
        "Тормозная система",
        "Колодка тормозная",
        "Арт. изготовителя KT-100",
        "Поставка партиями",
        "Итого к оплате, сум",
        "Опционально (не входит в итог)",
        "Набор креплений",
    ):
        assert expected in text, expected
    for secret in ("frozen_base_price", "Себестоимость", "Наценка"):
        assert secret not in text
    meta = seen["kwargs"]["meta"]
    # Сетка документа (план ДОК-4): вид — крупно, клиент — в окне конверта, номер и заявка — в инфоблоке.
    assert meta.kind_label == "Коммерческое предложение"
    assert meta.addressee[0] == "Buyer LLC" and meta.addressee_strong == 0
    assert [row.role for row in meta.info[:2]] == ["number", "date"]
    assert seen["kwargs"]["draft"] is True, "КП до отправки — проект, не оферта"


@pytest.mark.django_db
def test_signed_quote_prints_the_stamp_and_verification(world):  # noqa: F811
    quote = world["quote"]
    Quote.objects.filter(pk=quote.pk).update(
        verification_code="QT12CD34",
        signatory_name="Иванов И. И.",
        signatory_position="Директор",
        signed_at=timezone.now(),
        frozen_at=timezone.now(),
    )
    _lines(quote)
    seen = _render(quote)
    assert "Директор Иванов И. И." in seen["text"] and "Подписано электронной подписью" in seen["text"]
    meta = seen["kwargs"]["meta"]
    assert (meta.verification_code, meta.verification_url) == ("QT12CD34", "https://cabinet.example.test/v/QT12CD34")


@pytest.mark.django_db
def test_quote_falls_back_to_django_templates_when_switched_off(world, settings):  # noqa: F811
    settings.RT_DOCS_DOCUMENTS = ("invoice", "act", "contract")
    _lines(world["quote"])
    from rt_docs import pdf as rt_pdf

    from crm.services.quotes import QuoteLifecycleService

    with patch.object(rt_pdf, "render_pdf", side_effect=AssertionError("rt_docs не должен вызываться")):
        QuoteLifecycleService.generate_pdf(world["quote"].id)
