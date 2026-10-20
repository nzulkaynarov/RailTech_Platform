"""Единственная функция стадий `deal_stage` и сумма сделки `deal_amount` (FIX-30, находки I-2, I-3).

Таблица правил — в docstring `integration/services/stages.py`. Здесь: каждая из 11 стадий контракта на сделке,
собранной из настоящих документов; граничные случаи (черновики и аннулированное не двигают стадию); сумма без
черновиков КП; стадии контракта = enum `DealStage` в `erp-integration.yaml`.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from integration.services import stages
from integration.tests.contract_support import enum_values
from integration.tests.world import (
    STAGE_CASES,
    add_act,
    add_contract,
    add_fulfillment,
    add_invoice,
    add_order_quote,
    add_quote,
    build_closing,
    build_fulfilment,
    build_invoiced,
    build_paid,
    build_signed_contract_deal,
    build_won,
    make_company,
    make_deal,
    usd,
)

from crm.constants import (
    ActStatusCode,
    ContractStatusCode,
    DealStageCode,
    FulfillmentStatusCode,
    InvoiceStatusCode,
    QuoteStatusCode,
)
from crm.models import Deal, DealStage

pytestmark = pytest.mark.django_db

FSM = DealStageCode
Q = QuoteStatusCode


def stage_of(deal) -> str:
    """Стадия сделки, прочитанная заново из базы со всеми подгрузками (как в ответах integration)."""
    return stages.deal_stage(stages.with_stage_facts(Deal.objects.filter(pk=deal.pk)).get())


# ── По одной сделке на каждую из 11 стадий контракта ──────────────────────────────────────────────


@pytest.mark.parametrize(("expected", "build"), STAGE_CASES, ids=[case[0] for case in STAGE_CASES])
def test_each_contract_stage_is_derived_from_fsm_and_documents(expected, build):
    deal = build(make_company())
    assert stage_of(deal) == expected


def test_cases_cover_every_stage_of_the_contract():
    assert {expected for expected, _ in STAGE_CASES} == set(enum_values("DealStage"))


def test_stages_module_lists_exactly_the_contract_stages_in_lifecycle_order():
    """Список стадий в коде = enum `DealStage` в `erp-integration.yaml`: расхождение ловится здесь, а не у клиента."""
    assert list(stages.DEAL_STAGES) == enum_values("DealStage")


@pytest.mark.parametrize("code", DealStageCode.values)
def test_every_fsm_code_maps_into_the_contract_enum(code):
    deal = make_deal(make_company(), code)
    assert stage_of(deal) in enum_values("DealStage")


# ── Стадия FSM до акцепта ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fsm_code", "expected"),
    [
        (FSM.DRAFT, "request"),
        (FSM.KYC_PENDING, "request"),
        (FSM.RFQ_OPEN, "request"),
        (FSM.SOURCING, "quoting"),
        (FSM.CALCULATING, "quoting"),
        (FSM.QUOTE_SENT, "quote_sent"),
        (FSM.CLOSED_LOST, "lost"),
    ],
)
def test_fsm_code_before_acceptance_maps_directly(fsm_code, expected):
    assert stage_of(make_deal(make_company(), fsm_code)) == expected


def test_deal_without_fsm_stage_is_a_request():
    deal = Deal.objects.create(company=make_company(), title="Без стадии")
    assert deal.stage_id is None
    assert stage_of(deal) == "request"


def test_unknown_fsm_code_falls_back_to_request_and_is_logged(caplog):
    deal = make_deal(make_company(), "WON")  # такого кода в справочнике нет — старые тесты заводили именно такие
    with caplog.at_level(logging.WARNING, logger="integration.services.stages"):
        assert stage_of(deal) == "request"
    assert "неизвестный код стадии FSM" in caplog.text


def test_documents_of_a_reopened_deal_do_not_advance_it_past_its_fsm_stage():
    """Сделку вернули в расчёт (QUOTE_SENT → CALCULATING): документы прежнего заказа стадию не двигают."""
    deal, contract = build_signed_contract_deal(make_company())
    add_invoice(deal, InvoiceStatusCode.PAID, paid="1000000", contract=contract)
    deal.stage = DealStage.objects.get(code=FSM.CALCULATING)
    deal.save()
    assert stage_of(deal) == "quoting"


def test_previous_fsm_code_can_be_substituted_for_the_stage_change_signal():
    deal = make_deal(make_company(), FSM.QUOTE_SENT)
    add_quote(deal, 1, Q.SENT, "1000000")
    deal = stages.with_stage_facts(Deal.objects.filter(pk=deal.pk)).get()
    assert stages.deal_stage(deal) == "quote_sent"
    assert stages.deal_stage(deal, with_fsm_code=FSM.SOURCING) == "quoting"
    assert stages.deal_stage(deal, with_fsm_code=None) == "request"


# ── После акцепта: черновики и аннулированное стадию не двигают (негативные случаи) ──────────────────


def test_draft_and_cancelled_documents_do_not_move_the_stage():
    deal, contract = build_signed_contract_deal(make_company())
    add_invoice(deal, InvoiceStatusCode.DRAFT, contract=contract)
    add_invoice(deal, InvoiceStatusCode.CANCELLED, contract=contract)
    add_act(deal, ActStatusCode.DRAFT, contract=contract)  # черновик без причины возврата клиенту не виден
    add_act(deal, ActStatusCode.CANCELLED, contract=contract)
    assert stage_of(deal) == "contract"


def test_draft_or_cancelled_contract_is_not_a_contract_for_the_client():
    deal = make_deal(make_company(), FSM.CONTRACT_SIGNED)
    quote = add_quote(deal, 1, Q.APPROVED, "5000000")
    add_contract(deal, quote, ContractStatusCode.DRAFT)
    add_contract(deal, quote, ContractStatusCode.CANCELLED)
    assert stage_of(deal) == "accepted"


def test_partially_paid_and_unpaid_alongside_paid_invoice_is_still_invoiced():
    deal, contract = build_signed_contract_deal(make_company())
    add_invoice(deal, InvoiceStatusCode.PAID, total="2000000", paid="2000000", contract=contract)
    add_invoice(deal, InvoiceStatusCode.PARTIAL, total="3000000", paid="1000000", contract=contract)
    assert stage_of(deal) == "invoiced"


def test_cancelled_invoice_does_not_block_paid():
    deal, contract = build_signed_contract_deal(make_company())
    add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_invoice(deal, InvoiceStatusCode.CANCELLED, total="5000000", contract=contract)
    assert stage_of(deal) == "paid"


def test_pending_fulfilment_alone_is_not_the_start_of_delivery():
    deal, _ = build_signed_contract_deal(make_company())
    add_fulfillment(deal, FulfillmentStatusCode.PENDING)
    assert stage_of(deal) == "contract"


def test_delivery_line_past_assembling_means_fulfilment_even_without_fulfillment_status():
    from sales.models import DeliveryLine, DeliveryLineStatus

    deal, _ = build_signed_contract_deal(make_company())
    add_order_quote(deal, version=2)
    add_fulfillment(deal, FulfillmentStatusCode.PENDING)
    from sales.services.delivery_lines import sync_delivery_lines

    sync_delivery_lines([deal.fulfillment])
    DeliveryLine.objects.filter(deal=deal).update(status=DeliveryLineStatus.SHIPPED)
    assert DeliveryLine.objects.filter(deal=deal).exists()
    assert stage_of(deal) == "fulfilment"


def test_returned_act_is_still_closing():
    deal, contract = build_signed_contract_deal(make_company())
    add_act(deal, ActStatusCode.DRAFT, contract=contract, rejection_reason="Не совпадает количество")
    assert stage_of(deal) == "closing"


def test_closed_won_is_not_won_until_execution_is_complete():
    """FSM `CLOSED_WON` наступает при подписании договора; для CRM сделка закрыта, когда оплата, акт и приёмка готовы."""
    deal, contract = build_signed_contract_deal(make_company())
    invoice = add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_act(deal, ActStatusCode.SIGNED, contract=contract, invoice=invoice)
    add_fulfillment(deal, FulfillmentStatusCode.DELIVERED)  # не принята клиентом
    assert stage_of(deal) == "closing"
    assert stages.is_open_stage(stage_of(deal))


def test_closed_lost_wins_over_documents():
    deal, contract = build_signed_contract_deal(make_company())
    add_invoice(deal, InvoiceStatusCode.PAID, paid="1000000", contract=contract)
    deal.stage = DealStage.objects.get(code=FSM.CLOSED_LOST)
    deal.save()
    assert stage_of(deal) == "lost"
    assert not stages.is_open_stage("lost") and not stages.is_open_stage("won") and stages.is_open_stage("closing")


def test_stage_lookup_does_not_query_per_deal():
    """Список сделок идёт с подгрузкой: число запросов не растёт вместе с числом сделок."""
    company = make_company()
    build_closing(company)
    build_paid(company)

    def count_queries():
        with CaptureQueriesContext(connection) as ctx:
            for deal in stages.with_stage_facts(company.deals.all()):
                stages.deal_stage(deal)
                stages.deal_amount(deal)
                stages.deal_currency(deal)
        return len(ctx)

    few = count_queries()
    for build in (build_closing, build_paid, build_won, build_fulfilment, build_invoiced):
        build(company)
    assert count_queries() == few


# ── Сумма сделки ──────────────────────────────────────────────────────────────────────────────────────


def amount_of(deal):
    return stages.deal_amount(stages.with_stage_facts(Deal.objects.filter(pk=deal.pk)).get())


def test_amount_is_none_when_no_quote_was_sent_to_the_client():
    deal = make_deal(make_company(), FSM.CALCULATING)
    assert amount_of(deal) is None
    for version, status in enumerate((Q.DRAFT, Q.PENDING_TRADE_REVIEW, Q.PENDING_APPROVAL, Q.READY_TO_SEND), start=1):
        add_quote(deal, version, status, "9000000")
    assert amount_of(deal) is None, "черновики и КП на согласовании клиенту не обещаны — в сумму сделки не входят"


def test_amount_is_the_total_of_the_latest_sent_version():
    deal = make_deal(make_company(), FSM.QUOTE_SENT)
    add_quote(deal, 1, Q.SENT, "1000000.00")
    add_quote(deal, 2, Q.SENT, "2500000.50")
    assert amount_of(deal) == Decimal("2500000.50")


def test_newer_draft_does_not_replace_the_sent_amount():
    deal = make_deal(make_company(), FSM.QUOTE_SENT)
    add_quote(deal, 1, Q.SENT, "1000000.00")
    add_quote(deal, 2, Q.DRAFT, "7777777.00")  # менеджер правит новую версию — клиент её не видел
    assert amount_of(deal) == Decimal("1000000.00")


@pytest.mark.parametrize("status", [Q.SENT, Q.APPROVED, Q.REJECTED, "EXPIRED"])
def test_amount_counts_every_status_visible_to_the_client(status):
    deal = make_deal(make_company(), FSM.QUOTE_SENT)
    add_quote(deal, 1, status, "3000000.00", sent=True)
    assert amount_of(deal) == Decimal("3000000.00")


def test_amount_currency_follows_the_sent_quote():
    deal = make_deal(make_company(), FSM.QUOTE_SENT)
    add_quote(deal, 1, Q.SENT, "1500.00", currency=usd())
    add_quote(deal, 2, Q.DRAFT, "9000000.00")  # черновик в UZS на валюту суммы не влияет
    fresh = stages.with_stage_facts(Deal.objects.filter(pk=deal.pk)).get()
    assert stages.deal_currency(fresh) == "USD"
    assert stages.deal_amount(fresh) == Decimal("1500.00")


def test_currency_of_a_deal_without_quotes_is_the_default():
    fresh = stages.with_stage_facts(Deal.objects.filter(pk=make_deal(make_company()).pk)).get()
    assert stages.deal_currency(fresh) == "UZS"
