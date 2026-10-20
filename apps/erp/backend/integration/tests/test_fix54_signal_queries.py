"""FIX-54 (P2): pre_save-сигналы не читают прежнюю запись, когда сохраняются не отслеживаемые ими поля.

Раньше каждый `save()` сделки, КП, договора, счёта, акта и исполнения делал лишний SELECT «что было до» — даже при
`update_fields=["notes"]`. Теперь без отслеживаемых полей в `update_fields` читать нечего; со статусом/стадией — читает
ровно один раз (на сделке — один раз на оба обработчика: вебхук и уведомление клиенту).
"""

import datetime
from unittest.mock import patch

import pytest
from core.models import Notification
from crm.constants import ContractStatusCode, DealStageCode, FulfillmentStatusCode, QuoteStatusCode
from crm.models import DealStage
from django.db import connection
from django.test.utils import CaptureQueriesContext

from integration.tests import world

pytestmark = pytest.mark.django_db


@pytest.fixture
def deal():
    company = world.make_company()
    return world.make_deal(company)


def _selects(ctx, table):
    return [q["sql"] for q in ctx.captured_queries if q["sql"].lstrip().startswith("SELECT") and f'"{table}"' in q["sql"]]


@pytest.fixture
def objects(deal):
    quote = world.add_quote(deal, 1, QuoteStatusCode.SENT, "1000")
    contract = world.add_contract(deal, quote, ContractStatusCode.PENDING_CLIENT)
    return {
        "deal": (deal, "title", "sales_deal"),
        "quote": (quote, "valid_until", "sales_quote"),
        "contract": (contract, "notes", "sales_contract"),
        "invoice": (world.add_invoice(deal), "notes", "finance_invoice"),
        "act": (world.add_act(deal), "notes", "finance_act"),
        "fulfillment": (world.add_fulfillment(deal), "notes", "sales_fulfillment"),
    }


@pytest.mark.parametrize("name", ["deal", "quote", "contract", "invoice", "act", "fulfillment"])
def test_save_of_untracked_fields_reads_nothing_before_the_update(objects, name):
    instance, field, table = objects[name]
    with CaptureQueriesContext(connection) as ctx:
        instance.save(update_fields=[field])
    assert len(ctx) == 1, [q["sql"] for q in ctx.captured_queries]
    assert ctx.captured_queries[0]["sql"].lstrip().startswith("UPDATE")


def test_untracked_save_emits_no_event_and_no_notification(deal):
    quote = world.add_quote(deal, 1, QuoteStatusCode.SENT, "1000")
    with patch("integration.signals.webhooks.emit_quote_sent") as sent, patch(
        "integration.signals.webhooks.emit_deal_stage_changed"
    ) as stage:
        quote.save(update_fields=["valid_until"])
        deal.save(update_fields=["title"])
    sent.assert_not_called()
    stage.assert_not_called()


def test_deal_stage_change_reads_the_previous_row_once_for_both_handlers(deal):
    new_stage = DealStage.objects.get_or_create(code=DealStageCode.RFQ_OPEN, defaults={"name": "RFQ"})[0]
    deal.client = None
    deal.stage = new_stage
    with CaptureQueriesContext(connection) as ctx:
        deal.save()
    previous_reads = [s for s in _selects(ctx, "sales_deal") if f'WHERE "sales_deal"."id" = {deal.pk}' in s]
    assert len(previous_reads) == 1, previous_reads


def test_deal_stage_change_still_notifies_the_client(deal, django_user_model):
    client = django_user_model.objects.create_user(username="client54", password="x")
    deal.client = client
    deal.save(update_fields=["client"])
    assert not Notification.objects.filter(user=client, event_code="deal.stage_changed").exists()
    deal.stage = DealStage.objects.get_or_create(code=DealStageCode.CALCULATING, defaults={"name": "Расчёт"})[0]
    deal.save()
    assert Notification.objects.filter(user=client, event_code="deal.stage_changed").count() == 1
    deal.save()  # стадия не менялась — второго уведомления нет
    assert Notification.objects.filter(user=client, event_code="deal.stage_changed").count() == 1


def test_contract_status_change_reads_the_previous_row_with_one_query(deal):
    quote = world.add_quote(deal, 1, QuoteStatusCode.SENT, "1000")
    contract = world.add_contract(deal, quote, ContractStatusCode.PENDING_CLIENT)
    contract.client_signed_at = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.timezone.utc)
    with CaptureQueriesContext(connection) as ctx:
        contract.save(update_fields=["client_signed_at"])
    reads = [s for s in _selects(ctx, "sales_contract") if f'WHERE "sales_contract"."id" = {contract.pk}' in s]
    assert len(reads) == 1, [q["sql"] for q in ctx.captured_queries]
    assert "sales_contractstatus" in reads[0], "статус читается JOIN-ом, а не отдельным запросом"


def test_fulfillment_tracked_field_still_triggers_eta_event(deal):
    fulfillment = world.add_fulfillment(deal, FulfillmentStatusCode.PENDING, expected_delivery_date=datetime.date(2026, 12, 1))
    fulfillment.expected_delivery_date = datetime.date(2026, 12, 9)
    with patch("integration.signals.webhooks.emit_delivery_event") as emit:
        fulfillment.save(update_fields=["expected_delivery_date"])
    assert [c.kwargs["event_type"] for c in emit.call_args_list] == ["delivery.eta_changed"]
