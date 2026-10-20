"""`contract.signed` по новому договору (FIX-31, хвост FIX-30): прежнего статуса у нового договора нет, сигнал не падает."""

import pytest
from django.utils import timezone
from integration.models import IntegrationWebhookEvent
from integration.tests import world

from crm.constants import ContractStatusCode, QuoteStatusCode

pytestmark = pytest.mark.django_db


def _signed_events():
    return IntegrationWebhookEvent.objects.filter(event_type="contract.signed")


def _deal_with_quote():
    company = world.make_company()
    deal = world.make_deal(company)
    quote = world.add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    return deal, quote


def test_contract_created_already_signed_by_both_emits_contract_signed_once():
    deal, quote = _deal_with_quote()

    contract = world.add_contract(deal, quote, ContractStatusCode.SIGNED)

    events = list(_signed_events())
    assert len(events) == 1
    assert events[0].payload["payload"]["by"] == "both"
    assert events[0].payload["payload"]["erp_contract_id"] == contract.pk


def test_contract_created_unsigned_emits_nothing_and_later_signature_emits_once():
    deal, quote = _deal_with_quote()
    contract = world.add_contract(deal, quote, ContractStatusCode.PENDING_CLIENT)
    assert _signed_events().count() == 0

    contract.client_signed_at = timezone.now()
    contract.save()

    events = list(_signed_events())
    assert len(events) == 1
    assert events[0].payload["payload"]["by"] == "client"

    contract.save()  # повторное сохранение без новой подписи — нового события нет
    assert _signed_events().count() == 1
