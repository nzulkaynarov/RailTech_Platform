"""FIX-2xa — рендер PDF не откатывает статус документа.

Рендер долгий (WeasyPrint в Celery), а объект прочитан до него. Раньше после рендера шёл полный
``save()`` (``pdf_file.save(..., save=True)``) и записывал в БД старый статус поверх нового. Тест
воспроизводит гонку в одном потоке: во время «рендера» (подмена ``weasyprint.HTML.write_pdf``)
документ меняется другой операцией, а после рендера статус и даты должны остаться новыми.
"""

from unittest.mock import patch

import pytest

from crm.models import Act, ActStatus, Contract, Invoice, InvoiceStatus
from crm.tasks import _render_pdf_for
from crm.tests.test_permission_guards import (  # noqa: F401 — фикстуры мира
    _issued_invoice,
    _make_member,
    _make_user,
    _pending_client_contract,
    _sent_quote,
    buyer_company,
    deal,
    lookups,
    seller_company,
)


def _fake_html(during_render):
    """Подмена WeasyPrint: «рендер» выполняет конкурирующую операцию и отдаёт байты PDF."""

    class FakeHTML:
        def __init__(self, *args, **kwargs):
            pass

        def write_pdf(self, target=None, *args, **kwargs):
            during_render()
            target.write(b"%PDF-1.4 race test")

    return FakeHTML


@pytest.mark.django_db
def test_quote_render_does_not_roll_back_client_acceptance(lookups, buyer_company, seller_company, deal):  # noqa: F811
    from crm.services.quotes import QuoteLifecycleService

    seller = _make_user("race_seller@s.test")
    _make_member(seller, seller_company, is_primary=True)
    buyer = _make_user("race_buyer@b.test")
    _make_member(buyer, buyer_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)

    def client_accepts_mid_render():
        QuoteLifecycleService.approve_quote(quote.id, buyer)

    with patch("weasyprint.HTML", _fake_html(client_accepts_mid_render)):
        _render_pdf_for("quote", quote.id)

    quote.refresh_from_db()
    assert quote.status.code == "APPROVED", "рендер откатил статус КП на устаревший"
    assert quote.approved_at is not None
    assert quote.approved_by_id == buyer.id
    assert Contract.objects.filter(quote=quote).exists(), "договор принятого КП потерян"
    assert quote.pdf_file, "рендер должен сохранить свой файл"


@pytest.mark.django_db
def test_invoice_render_does_not_roll_back_payment(lookups, buyer_company, seller_company, deal):  # noqa: F811
    seller = _make_user("race_inv_seller@s.test")
    _make_member(seller, seller_company, is_primary=True)
    contract = _pending_client_contract(deal, _sent_quote(deal, prepared_by=seller))
    invoice = _issued_invoice(deal, contract)

    def payment_arrives_mid_render():
        Invoice.objects.filter(pk=invoice.pk).update(
            status=InvoiceStatus.objects.get(code="PAID"), amount_paid=invoice.total_incl_vat
        )

    with patch("weasyprint.HTML", _fake_html(payment_arrives_mid_render)):
        _render_pdf_for("invoice", invoice.id)

    invoice.refresh_from_db()
    assert invoice.status.code == "PAID", "рендер откатил статус счёта"
    assert invoice.amount_paid == invoice.total_incl_vat
    assert invoice.pdf_file


@pytest.mark.django_db
def test_act_render_does_not_roll_back_signature(lookups, buyer_company, seller_company, deal):  # noqa: F811
    seller = _make_user("race_act_seller@s.test")
    _make_member(seller, seller_company, is_primary=True)
    contract = _pending_client_contract(deal, _sent_quote(deal, prepared_by=seller))
    invoice = _issued_invoice(deal, contract)
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-RACE-001",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=invoice.total_incl_vat,
        created_by=seller,
    )

    def client_signs_mid_render():
        Act.objects.filter(pk=act.pk).update(status=ActStatus.objects.get(code="SIGNED"))

    with patch("weasyprint.HTML", _fake_html(client_signs_mid_render)):
        _render_pdf_for("act", act.id)

    act.refresh_from_db()
    assert act.status.code == "SIGNED", "рендер откатил статус акта"
    assert act.pdf_file
