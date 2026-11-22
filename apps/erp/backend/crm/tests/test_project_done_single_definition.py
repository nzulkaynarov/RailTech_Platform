"""Одно определение «проект выполнен» (СЦ-8, решение владельца 2026-11-22).

Факт, из которого выводятся все статусы: каждый живой акт принят клиентом в Кабинете или подписан сканом И все
выставленные счета оплачены. Приёмка строк поставки условием не является. Читатели — предикат `project_is_done`,
флаг `execution_complete`, стадия контракта `won`, закрытие заявки для склада и исход запроса в портале — на каждой
комбинации документов дают один и тот же ответ.
"""

from __future__ import annotations

import pytest
from integration.services import stages
from integration.tests import bus_support
from integration.tests.world import add_act, add_fulfillment, add_invoice, build_signed_contract_deal, make_company
from inventory.services.stock import deal_closed_for_stock
from portal import projections

from crm.constants import ActStatusCode, FulfillmentStatusCode, InvoiceStatusCode
from crm.models import ActivityLog, Deal
from crm.services import projects
from crm.services.deal_documents import deal_execution_is_complete
from crm.tests.projects_world import pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

I, A, F = InvoiceStatusCode, ActStatusCode, FulfillmentStatusCode

#: (имя, статус счёта, статус акта (None — акта нет), файл скана, исполнение (None — нет), проект выполнен?)
CASES = [
    ("contract signed only", None, None, False, None, False),
    ("invoice paid, no act", I.PAID, None, False, F.DELIVERED, False),
    ("act issued, not accepted", I.PAID, A.ISSUED, False, F.DELIVERED, False),
    ("act accepted in cabinet, invoice unpaid", I.ISSUED, A.SIGNED, False, F.DELIVERED, False),
    ("act scan attached, invoice unpaid", I.ISSUED, A.SIGNED, True, F.SHIPPED, False),
    ("act accepted in cabinet (no file) and paid", I.PAID, A.SIGNED, False, F.SHIPPED, True),
    ("act scan and paid", I.PAID, A.SIGNED, True, F.DELIVERED, True),
    ("act accepted, paid, delivery lines not accepted", I.PAID, A.SIGNED, False, None, True),
    ("act accepted, paid, delivery accepted", I.PAID, A.SIGNED, False, F.ACCEPTED, True),
]


def _build(invoice_status, act_status, with_file, fulfillment):
    deal, contract = build_signed_contract_deal(make_company())
    invoice = None
    if invoice_status:
        paid = "5000000" if invoice_status == I.PAID else "0"
        invoice = add_invoice(deal, invoice_status, total="5000000", paid=paid, contract=contract)
    if act_status:
        fields = {"signed_file": scan()} if with_file else {}
        add_act(deal, act_status, contract=contract, invoice=invoice, **fields)
    if fulfillment:
        add_fulfillment(deal, fulfillment)
    return Deal.objects.get(pk=deal.pk)


@pytest.mark.parametrize(
    ("name", "invoice", "act", "with_file", "fulfillment", "done"), CASES, ids=[c[0] for c in CASES]
)
def test_every_reader_agrees_with_the_one_predicate(name, invoice, act, with_file, fulfillment, done):
    deal = _build(invoice, act, with_file, fulfillment)
    fresh = projects.project_queryset().prefetch_related("quotes__status").get(pk=deal.pk)

    assert projects.project_is_done(fresh) is done
    assert deal_execution_is_complete(fresh) is done  # `execution_complete` сделки
    assert (stages.deal_stage(fresh) == "won") is done
    assert deal_closed_for_stock(fresh) is done
    assert projects.project_step(fresh) == ("DONE" if done else "PAYMENT")
    assert (projections.request_outcome(fresh) == "won") is done
    assert projections.request_status(fresh) == ("closed" if done else "in_progress")
    if not done:
        assert projections.request_outcome(fresh) is None


def test_cancelled_and_draft_documents_do_not_change_the_answer():
    deal, contract = build_signed_contract_deal(make_company())
    paid = add_invoice(deal, I.PAID, total="5000000", paid="5000000", contract=contract)
    add_invoice(deal, I.CANCELLED, contract=contract)
    add_invoice(deal, I.DRAFT, contract=contract)
    add_act(deal, A.SIGNED, contract=contract, invoice=paid)
    add_act(deal, A.CANCELLED, contract=contract, invoice=paid)
    fresh = projects.project_queryset().get(pk=deal.pk)
    assert projects.project_is_done(fresh) and deal_execution_is_complete(fresh)
    assert stages.deal_stage(fresh) == "won"


# ── Событие `deal.won` уходит в момент «выполнено», а не при подписании договора ────────────────────────────


def _deal_won_events():
    return bus_support.published("deal.won")


def test_deal_won_is_published_when_the_project_becomes_done_not_at_contract_signing(pw):  # noqa: F811
    from decimal import Decimal

    from django.utils import timezone
    from integration.tests import world as w

    from crm.constants import ContractStatusCode, DealStageCode
    from crm.models import DealStage
    from crm.services import act_flow
    from crm.services.billing import record_payment

    contract = w.add_contract(pw.deal, pw.quote, ContractStatusCode.SIGNED)
    invoice = w.add_invoice(pw.deal, I.ISSUED, total="5000000", paid="0", contract=contract)
    act = w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    pw.deal.stage = DealStage.objects.get(code=DealStageCode.CLOSED_WON)
    pw.deal.save(update_fields=["stage"])

    assert _deal_won_events() == [], "договор подписан, но проект не выполнен"

    _, error = act_flow.attach_act_scan(act.id, pw.accountant, scan())
    assert error is None and _deal_won_events() == [], "акт подписан, счёт не оплачен"

    _, error = record_payment(
        invoice.id, actor=pw.admin, amount=Decimal("5000000"), reference="p-1", paid_at=timezone.now().date()
    )
    assert error is None
    envelope = bus_support.only("deal.won")
    bus_support.assert_matches_contract(envelope)
    assert envelope["data"]["deal"]["stage"] == "won"
    assert ActivityLog.objects.filter(event_code="project.done", deal=pw.deal).count() == 1

    assert projects.log_project_done_once(pw.deal) is False
    assert len(_deal_won_events()) == 1, "повтор проверки событие не дублирует"


# ── Каждый путь, на котором проект становится выполненным, публикует `deal.won` ровно один раз ───────────────


def _closed_won(pw):  # noqa: F811
    from crm.constants import DealStageCode
    from crm.models import DealStage

    pw.deal.stage = DealStage.objects.get(code=DealStageCode.CLOSED_WON)
    pw.deal.save(update_fields=["stage"])


def test_cancelling_the_last_unpaid_invoice_completes_the_project_and_publishes_deal_won_once(pw):  # noqa: F811
    from integration.tests import world as w

    from crm.constants import ContractStatusCode
    from crm.services.invoice_lifecycle import cancel_invoice

    contract = w.add_contract(pw.deal, pw.quote, ContractStatusCode.SIGNED)
    w.add_invoice(pw.deal, I.PAID, total="5000000", paid="5000000", contract=contract)
    stray = w.add_invoice(pw.deal, I.ISSUED, total="100", paid="0", contract=contract)
    w.add_act(pw.deal, A.SIGNED, contract=contract, signed_file=scan())
    _closed_won(pw)
    assert not projects.project_is_done(Deal.objects.get(pk=pw.deal.pk)) and _deal_won_events() == []

    _, error = cancel_invoice(stray, pw.accountant)

    assert error is None and projects.project_is_done(Deal.objects.get(pk=pw.deal.pk))
    assert len(_deal_won_events()) == 1
    assert ActivityLog.objects.filter(event_code="project.done", deal=pw.deal).count() == 1


def test_voiding_the_last_open_act_completes_the_project_and_publishes_deal_won_once(pw):  # noqa: F811
    from integration.tests import world as w

    from crm.constants import ContractStatusCode
    from crm.services.billing import cancel_act

    contract = w.add_contract(pw.deal, pw.quote, ContractStatusCode.SIGNED)
    invoice = w.add_invoice(pw.deal, I.PAID, total="5000000", paid="5000000", contract=contract)
    w.add_act(pw.deal, A.SIGNED, contract=contract, invoice=invoice, signed_file=scan())
    open_act = w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    _closed_won(pw)
    assert _deal_won_events() == []

    _, error = cancel_act(open_act.id, pw.accountant, reason="duplicate")

    assert error is None and projects.project_is_done(Deal.objects.get(pk=pw.deal.pk))
    assert len(_deal_won_events()) == 1


def test_project_done_before_contract_won_publishes_deal_won_at_the_transition_once(pw):  # noqa: F811
    from integration.tests import world as w

    from crm.constants import ContractStatusCode, DealStageCode
    from crm.services.deals import transition_deal_stage

    contract = w.add_contract(pw.deal, pw.quote, ContractStatusCode.SIGNED)
    invoice = w.add_invoice(pw.deal, I.PAID, total="5000000", paid="5000000", contract=contract)
    w.add_act(pw.deal, A.SIGNED, contract=contract, invoice=invoice, signed_file=scan())
    deal = Deal.objects.get(pk=pw.deal.pk)
    assert projects.project_is_done(deal) and deal.stage.code == DealStageCode.CONTRACT_SIGNED
    assert projects.log_project_done_once(deal) is True and _deal_won_events() == [], "стадия ещё не won"

    _, error = transition_deal_stage(deal, DealStageCode.CLOSED_WON, pw.admin, validate_fsm=False)

    assert error is None
    bus_support.assert_matches_contract(bus_support.only("deal.won"))
    assert projects.log_project_done_once(Deal.objects.get(pk=pw.deal.pk)) is False
    assert len(_deal_won_events()) == 1
