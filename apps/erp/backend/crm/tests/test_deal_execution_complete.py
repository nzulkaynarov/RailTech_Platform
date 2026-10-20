"""«Завершено» — про исполнение, а не про выигрыш сделки (O4).

Прогон глазами 17-08: покупатель видел «Completed» сразу после `CLOSED_WON` — то есть при
подписанном договоре, но неоплаченном счёте и непринятой поставке. Эталоны разделяют продажную
и операционную шкалу: у Odoo продажная кончается нейтральным «Sales Order», а `invoice_status`
и `delivery_status` живут отдельно; «Done» там — ручной Lock, терминальное состояние.
"""

import pytest

from crm.services.deal_documents import deal_execution_is_complete
from crm.tests.test_act_two_sided import act_world, lookups  # noqa: F401


@pytest.mark.django_db
def test_won_deal_with_unpaid_invoice_is_not_complete(act_world):  # noqa: F811
    deal = act_world["act"].deal
    assert deal_execution_is_complete(deal) is False


@pytest.mark.django_db
def test_complete_only_when_paid_delivered_and_act_signed(act_world):  # noqa: F811
    from django.utils import timezone

    from crm.constants import ActStatusCode, FulfillmentStatusCode, InvoiceStatusCode
    from crm.models import ActStatus, Fulfillment, FulfillmentStatus, InvoiceStatus

    world = act_world
    deal = world["act"].deal

    invoice = world["invoice"]
    invoice.status = InvoiceStatus.objects.get(code=InvoiceStatusCode.PAID)
    invoice.amount_paid = invoice.total_incl_vat
    invoice.save(update_fields=["status", "amount_paid"])
    assert deal_execution_is_complete(deal) is False, "акт ещё не подписан"

    act = world["act"]
    act.status = ActStatus.objects.get(code=ActStatusCode.SIGNED)
    act.issuer_signed_at = timezone.now()
    act.acceptor_signed_at = timezone.now()
    act.save(update_fields=["status", "issuer_signed_at", "acceptor_signed_at"])
    assert deal_execution_is_complete(deal) is False, "поставка ещё не принята"

    Fulfillment.objects.create(
        deal=deal,
        status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.ACCEPTED),
        accepted_at=timezone.now(),
    )
    deal.refresh_from_db()
    assert deal_execution_is_complete(deal) is True


@pytest.mark.django_db
def test_cancelled_and_draft_invoices_do_not_block_completion(act_world):  # noqa: F811
    """Аннулированный и черновой счёт — не долг (FIX-30): оплаченный счёт при них всё равно закрывает исполнение."""
    from django.utils import timezone

    from crm.constants import ActStatusCode, FulfillmentStatusCode, InvoiceStatusCode
    from crm.models import ActStatus, Fulfillment, FulfillmentStatus, Invoice, InvoiceStatus

    world = act_world
    deal = world["act"].deal
    invoice = world["invoice"]
    invoice.status = InvoiceStatus.objects.get(code=InvoiceStatusCode.PAID)
    invoice.amount_paid = invoice.total_incl_vat
    invoice.save(update_fields=["status", "amount_paid"])
    for number, code in (("INV-X-CANCELLED", InvoiceStatusCode.CANCELLED), ("INV-X-DRAFT", InvoiceStatusCode.DRAFT)):
        Invoice.objects.create(deal=deal, number=number, status=InvoiceStatus.objects.get(code=code))
    act = world["act"]
    act.status = ActStatus.objects.get(code=ActStatusCode.SIGNED)
    act.save(update_fields=["status"])
    Fulfillment.objects.create(
        deal=deal,
        status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.ACCEPTED),
        accepted_at=timezone.now(),
    )
    deal.refresh_from_db()
    assert deal_execution_is_complete(deal) is True

    Invoice.objects.create(
        deal=deal, number="INV-X-ISSUED", status=InvoiceStatus.objects.get(code=InvoiceStatusCode.ISSUED)
    )
    deal.refresh_from_db()
    assert deal_execution_is_complete(deal) is False, "неоплаченный выставленный счёт по-прежнему держит сделку"
