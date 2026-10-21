"""FIX-60a: код акцепта в событии `quote.acceptance_code_requested` — секрет доставки, а не журнала (Q-FIX22-1).

* журнал (`IntegrationWebhookEvent.payload`), заголовки и логи хранят маску; настоящий код лежит в кэше до доставки;
* тело запроса в CRM — полное, по `events.schema.json`, подпись считается по нему;
* код протух или кэш потерян — доставка отменяется (`FAILED`, без запроса и ретраев);
* после доставки секрет убирается из кэша; чужие события (`invite.sent` и др.) не затронуты.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone
from integration.models import CrmContactMapping, IntegrationWebhookEvent, WebhookEventStatus
from integration.services.webhooks import (
    SECRET_MASK,
    delivery_payload,
    emit_quote_acceptance_code_requested,
    sign_payload,
    webhook_signing_secret,
)
from integration.tasks import deliver_webhook_event
from integration.tests.world import add_quote, make_company, make_deal
from parties.models import Contact

from core.tests.events_contract import event_errors, example_event
from crm.constants import QuoteStatusCode

pytestmark = pytest.mark.django_db

CODE = "739104"


@pytest.fixture
def setup():
    company = make_company(crm_client_id=7001)
    contact = Contact.objects.filter(company=company).first()
    mapping = CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    deal = make_deal(company)
    quote = add_quote(deal, 1, QuoteStatusCode.SENT, "5000000")
    return quote, contact, mapping


def emit(quote, contact, **kwargs):
    return emit_quote_acceptance_code_requested(
        quote, contact, CODE, timezone.now() + timedelta(minutes=15), send_async=False, **kwargs
    )


def test_example_of_the_contract_is_what_the_emitter_builds(setup):
    quote, contact, _ = setup
    event = emit(quote, contact)
    body = delivery_payload(event)
    assert event_errors(body) == []
    example = example_event("quote.acceptance_code_requested")
    assert set(body) == set(example) and set(body["payload"]) == set(example["payload"])
    assert body["actor"]["type"] == "client"


def test_journal_payload_headers_and_logs_never_contain_the_code(setup, caplog):
    quote, contact, _ = setup
    with caplog.at_level(logging.DEBUG):
        event = emit(quote, contact)
    event.refresh_from_db()

    assert event.payload["payload"]["code"] == SECRET_MASK
    assert CODE not in json.dumps(event.payload) and CODE not in json.dumps(event.headers)
    assert CODE not in caplog.text
    assert delivery_payload(event)["payload"]["code"] == CODE


def test_delivery_sends_the_real_code_signs_the_real_body_and_keeps_the_journal_masked(setup):
    quote, contact, _ = setup
    event = emit(quote, contact)

    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")) as post:
        assert deliver_webhook_event(event.pk) is True

    sent = post.call_args.kwargs
    body = json.loads(sent["content"])
    assert body["payload"]["code"] == CODE and event_errors(body) == []
    assert sent["headers"]["X-Signature"] == sign_payload(webhook_signing_secret(), sent["content"])
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.SENT
    assert event.payload["payload"]["code"] == SECRET_MASK, "после доставки журнал по-прежнему без кода"
    assert CODE not in json.dumps(event.headers) and CODE not in event.last_error
    assert delivery_payload(event) is None, "секрет убран из кэша после доставки"


def test_a_failed_attempt_keeps_the_secret_for_the_retry(setup):
    from celery.exceptions import Retry

    quote, contact, _ = setup
    event = emit(quote, contact)
    with patch("httpx.Client.post", return_value=MagicMock(status_code=500, text="boom")):
        with patch.object(deliver_webhook_event, "retry", side_effect=Retry("r")):
            with pytest.raises(Retry):
                deliver_webhook_event(event.pk)
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.PENDING and CODE not in event.last_error
    assert delivery_payload(event)["payload"]["code"] == CODE

    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")) as post:
        assert deliver_webhook_event(event.pk) is True
    assert json.loads(post.call_args.kwargs["content"])["payload"]["code"] == CODE


def test_a_lost_secret_cancels_the_delivery_without_a_request(setup, caplog):
    quote, contact, _ = setup
    event = emit(quote, contact)
    cache.clear()  # код протух или Redis перезапущен

    with caplog.at_level(logging.DEBUG), patch("httpx.Client.post") as post:
        assert deliver_webhook_event(event.pk) is False

    post.assert_not_called()
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.FAILED and event.next_attempt_at is None
    assert event.last_error.startswith("SECRET_EXPIRED") and event.attempts == 0
    assert CODE not in caplog.text and CODE not in event.last_error


def test_contact_without_a_crm_mapping_gets_no_event(setup):
    quote, contact, mapping = setup
    mapping.delete()
    assert emit(quote, contact) is None
    assert not IntegrationWebhookEvent.objects.filter(event_type="quote.acceptance_code_requested").exists()


def test_other_events_are_stored_and_delivered_unchanged(setup):
    from integration.services.webhooks import emit_invite_sent

    _, contact, _ = setup
    event = emit_invite_sent(contact=contact, channels=["email"], send_async=False)
    assert event.payload["payload"]["erp_contact_id"] == contact.pk and SECRET_MASK not in json.dumps(event.payload)
    assert delivery_payload(event) is event.payload
