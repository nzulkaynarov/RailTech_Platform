"""Шина rt_bus в ERP (B3): секреты пар (L12), доставка подписчику, код акцепта в кэше, приёмник `POST /bus/v1/events`.

Что проверяется именно в ERP, а не в библиотеке (её правила — `packages/rt-bus/tests`):
* секрет пары CRM ↔ ERP выводится из секрета вебхуков сопряжения, окружение `RT_BUS_SECRET_*` главнее;
* настоящая доставка в CRM (HTTP подменён `httpx.MockTransport`): заголовки, подпись, код акцепта в теле только на отправке;
* приёмник: подпись, повтор `id`, неизвестный тип — `skipped`, `data` не по схеме — 422, обработчик проекции;
* приёмник работает по внутреннему адресу без JWT и сессии (снаружи его закрывает Caddy).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from django.utils import timezone
from integration.bus import derive_pair_secret, get_bus, pair_secrets
from integration.models import CredentialSlot, CrmClientMapping, CrmContactMapping, ServiceCredential
from integration.services import credentials, events
from integration.tests import bus_support
from integration.tests.world import add_quote, make_company, make_deal
from parties.models import Company, Contact
from rt_bus.django.models import Delivery, Inbox
from rt_bus.signing import format_timestamp, sign, verify

from crm.constants import QuoteStatusCode

CODE = "739104"
WEBHOOK_SECRET = "test-webhook-secret"  # conftest: settings.ERP_WEBHOOK_SECRET


# ── Секреты пар (L12) ───────────────────────────────────────────────────────────────────────────────


def test_pair_secret_is_the_hmac_of_the_webhook_secret_and_is_directional():
    secret = derive_pair_secret("webhook", "erp", "crm")
    assert secret == hmac.new(b"webhook", b"rt-bus/v1/erp->crm", hashlib.sha256).hexdigest()
    assert secret != derive_pair_secret("webhook", "crm", "erp"), "направленный секрет: ERP→CRM и CRM→ERP разные"
    assert len(secret) == 64


@pytest.mark.django_db
def test_pair_secrets_come_from_every_active_webhook_secret_first_one_signs(settings):
    settings.ERP_WEBHOOK_SECRET = "new-secret, old-secret"
    assert pair_secrets("erp", "crm") == [
        derive_pair_secret("new-secret", "erp", "crm"),
        derive_pair_secret("old-secret", "erp", "crm"),
    ]
    assert pair_secrets("crm", "erp")[0] == derive_pair_secret("new-secret", "crm", "erp")


@pytest.mark.django_db
def test_the_secret_from_pairing_overrides_the_env_one():
    ServiceCredential.objects.create(
        slot=CredentialSlot.WEBHOOK_SECRET, ciphertext=credentials.encrypt("db-secret"), last4="cret"
    )
    assert credentials.webhook_secrets() == ["db-secret"]
    assert pair_secrets("erp", "crm") == [derive_pair_secret("db-secret", "erp", "crm")]


@pytest.mark.django_db
def test_env_secret_of_the_pair_wins_over_the_derived_one(monkeypatch):
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", "env-new,env-old")
    monkeypatch.setenv("RT_BUS_SECRET_CRM_ERP", "env-in")
    assert pair_secrets("erp", "crm") == ["env-new", "env-old"]
    assert pair_secrets("crm", "erp") == ["env-in"]


@pytest.mark.django_db
def test_other_pairs_have_no_secret_without_the_environment(monkeypatch):
    """Подписчик платформы (BFF), заглушка, коннектор: секрета нет — доставка откладывается, а не уходит неподписанной."""
    assert pair_secrets("erp", "platform-bff") == []
    monkeypatch.setenv("RT_BUS_SECRET_ERP_PLATFORM_BFF", "bff-secret")
    assert pair_secrets("erp", "platform-bff") == ["bff-secret"]


def test_subscriptions_of_the_image_list_crm_and_erp():
    subscriptions = get_bus().core.subscriptions()
    by_name = {sub.name: sub for sub in subscriptions.subscribers}
    assert set(by_name) >= {"crm", "erp"}
    assert any(pattern.startswith("uz.railtech.erp.") for pattern in by_name["crm"].types)
    assert "uz.railtech.crm.client.updated.v1" in by_name["erp"].types


# ── Доставка в CRM: настоящий publish → pump → подписанный POST ─────────────────────────────────────


def _crm_receiver(monkeypatch, status=200):
    """Подменяет HTTP шины ERP на заглушку CRM; возвращает список принятых запросов."""
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(status, json={"status": "received"})

    monkeypatch.setattr(get_bus(), "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    return received


@pytest.fixture
def code_setup():
    company = make_company(crm_client_id=7001)
    contact = Contact.objects.filter(company=company).first()
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    quote = add_quote(make_deal(company), 1, QuoteStatusCode.SENT, "5000000")
    return quote, contact


def _publish_code(quote, contact):
    with transaction.atomic():
        return events.publish_quote_acceptance_code_requested(
            quote, contact, CODE, timezone.now() + timedelta(minutes=15)
        )


@pytest.mark.django_db(transaction=True)
def test_delivery_to_crm_is_signed_with_the_derived_secret_and_carries_the_real_code(code_setup, monkeypatch):
    quote, contact = code_setup
    received = _crm_receiver(monkeypatch)

    event = _publish_code(quote, contact)
    stats = get_bus().pump()

    assert stats.deliver.delivered == 1 and len(received) == 1
    request = received[0]
    endpoint = get_bus().core.subscriptions().get("crm").url()
    assert str(request.url) == endpoint and request.url.path == "/bus/v1/events"
    assert request.headers["content-type"] == "application/cloudevents+json"
    assert request.headers["x-rt-publisher"] == "erp" and request.headers["x-rt-event-id"] == event.id
    body = request.content
    assert verify(
        [derive_pair_secret(WEBHOOK_SECRET, "erp", "crm")],
        event.id,
        request.headers["x-rt-timestamp"],
        body,
        request.headers["x-rt-signature"],
    ), "подпись считается по реальным байтам тела с кодом и секретом пары ERP → CRM"
    sent = json.loads(body)
    assert sent["type"] == "uz.railtech.erp.quote.acceptance_code_requested.v1" and sent["source"] == "rt://erp"
    assert sent["data"]["payload"]["code"] == CODE
    assert not bus_support.registry().validate_data(sent["type"], sent["data"], tolerant=False)
    assert Delivery.objects.get(event_id=event.id, subscriber="crm").status == "delivered"

    stored = bus_support.only("quote.acceptance_code_requested")
    assert stored["data"]["payload"]["code"] == "***", "в outbox после доставки по-прежнему маска"
    assert CODE not in json.dumps(stored)


@pytest.mark.django_db(transaction=True)
def test_a_lost_secret_makes_the_delivery_dead_without_a_request(code_setup, monkeypatch, caplog):
    quote, contact = code_setup
    received = _crm_receiver(monkeypatch)
    event = _publish_code(quote, contact)
    cache.clear()  # код протух или Redis перезапущен

    with caplog.at_level("DEBUG"):
        get_bus().pump()

    assert not received
    delivery = Delivery.objects.get(event_id=event.id, subscriber="crm")
    assert delivery.status == "dead" and "SECRET_EXPIRED" in (delivery.last_error or "")
    assert CODE not in caplog.text and CODE not in (delivery.last_error or "")


@pytest.mark.django_db(transaction=True)
def test_a_wrong_endpoint_404_goes_dead_at_once_and_retry_all_dead_resends(code_setup, monkeypatch):
    """Неверный адрес подписчика: 404 сразу в `dead`; после исправления адреса «повторить все dead» доставляет."""
    quote, contact = code_setup
    received = _crm_receiver(monkeypatch, status=404)
    event = _publish_code(quote, contact)

    get_bus().pump()

    assert len(received) == 1 and Delivery.objects.get(event_id=event.id, subscriber="crm").status == "dead"

    received_ok = _crm_receiver(monkeypatch, status=200)
    assert get_bus().retry_all_dead("crm") == 1
    get_bus().pump()
    assert len(received_ok) == 1 and Delivery.objects.get(event_id=event.id, subscriber="crm").status == "delivered"


# ── Приёмник POST /bus/v1/events ─────────────────────────────────────────────────────────────────────

EVENTS_DIR = Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events"))


def crm_event(short: str, **changes) -> dict:
    """Пример события CRM из контракта, со свежими `id` и временем."""
    envelope = json.loads((EVENTS_DIR / "crm" / "examples" / f"{short}.v1.json").read_text(encoding="utf-8"))
    envelope["id"] = str(uuid.uuid4())
    envelope["time"] = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope.update(changes)
    return envelope


def signed_post(envelope: dict, *, secret: str | None = None, publisher: str = "crm", timestamp: str | None = None):
    body = json.dumps(envelope, ensure_ascii=False).encode()
    stamp = timestamp or format_timestamp(timezone.now())
    secret = secret or derive_pair_secret(WEBHOOK_SECRET, "crm", "erp")
    return Client().post(
        "/bus/v1/events",
        data=body,
        content_type="application/cloudevents+json",
        HTTP_X_RT_PUBLISHER=publisher,
        HTTP_X_RT_EVENT_ID=envelope["id"],
        HTTP_X_RT_TIMESTAMP=stamp,
        HTTP_X_RT_SIGNATURE=sign(secret, envelope["id"], stamp, body),
    )


@pytest.fixture
def inline_queue(monkeypatch, django_capture_on_commit_callbacks):
    """Очередь обработки inbox без брокера: запись обрабатывается сразу после коммита запроса."""
    bus = get_bus()
    monkeypatch.setattr(bus, "enqueue", bus.process_inbox)
    return django_capture_on_commit_callbacks


@pytest.mark.django_db
def test_receiver_accepts_a_signed_crm_event_and_the_handler_updates_the_projection(inline_queue):
    company = make_company(name="Старое имя", crm_client_id=42)
    envelope = crm_event("client.updated")
    envelope["data"]["client"].update({"crm_client_id": 42, "name": "Новое имя клиента", "erp_company_id": company.pk})

    with inline_queue(execute=True):
        response = signed_post(envelope)

    assert response.status_code == 200 and response.json()["status"] == "received"
    assert Inbox.objects.get(event_id=envelope["id"]).status == "processed"
    company.refresh_from_db()
    assert company.name == "Новое имя клиента"


@pytest.mark.django_db
def test_receiver_needs_no_jwt_or_session_only_the_signature():
    envelope = crm_event("client.updated")
    # Ни токена, ни cookie, ни CSRF — подписанный запрос принят; чужой подписью — 401.
    assert signed_post(envelope).status_code == 200
    assert signed_post(crm_event("client.updated"), secret="x" * 64).status_code == 401


@pytest.mark.django_db
def test_receiver_rejects_bad_signature_wrong_publisher_and_stale_timestamp():
    assert signed_post(crm_event("client.updated"), secret="wrong").status_code == 401
    assert signed_post(crm_event("client.updated"), publisher="someone").status_code == 401
    stale = format_timestamp(timezone.now() - timedelta(minutes=10))
    assert signed_post(crm_event("client.updated"), timestamp=stale).status_code == 401
    assert not Inbox.objects.exists()


@pytest.mark.django_db
def test_receiver_takes_any_of_the_current_secrets_during_rotation(settings):
    settings.ERP_WEBHOOK_SECRET = "new-secret,old-secret"
    old = derive_pair_secret("old-secret", "crm", "erp")
    new = derive_pair_secret("new-secret", "crm", "erp")
    assert signed_post(crm_event("client.updated"), secret=old).status_code == 200
    assert signed_post(crm_event("client.updated"), secret=new).status_code == 200


@pytest.mark.django_db
def test_receiver_repeat_of_an_id_is_200_without_second_processing(inline_queue):
    envelope = crm_event("client.updated")
    with inline_queue(execute=True):
        assert signed_post(envelope).json()["status"] == "received"
    again = signed_post(envelope)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert Inbox.objects.filter(event_id=envelope["id"]).count() == 1


@pytest.mark.django_db
def test_receiver_marks_a_type_without_a_handler_as_skipped():
    """CRM публикует и другие события (лид, сотрудник): ERP на них не подписан — `skipped` с записью, не ошибка."""
    envelope = crm_event("lead.created")
    response = signed_post(envelope)
    assert response.status_code == 200 and response.json()["status"] == "skipped"
    assert Inbox.objects.get(event_id=envelope["id"]).status == "skipped"


@pytest.mark.django_db
def test_receiver_rejects_data_not_by_the_schema_with_422():
    envelope = crm_event("client.updated")
    del envelope["data"]["client"]["name"]
    assert signed_post(envelope).status_code == 422
    assert not Inbox.objects.filter(event_id=envelope["id"]).exists()


@pytest.mark.django_db
def test_receiver_tolerates_an_extra_optional_field_from_a_newer_publisher():
    envelope = crm_event("client.updated")
    envelope["data"]["client"]["new_optional_field"] = "ok"
    assert signed_post(envelope).status_code == 200


@pytest.mark.django_db
def test_receiver_takes_only_post():
    assert Client().get("/bus/v1/events").status_code == 405


@pytest.mark.django_db
def test_company_of_an_unknown_client_is_not_an_error(inline_queue):
    """Клиент CRM, которого ERP ещё не знает (нет передачи): событие обработано как пропуск, не `failed`."""
    envelope = crm_event("client.updated")
    envelope["data"]["client"].update({"crm_client_id": 999999, "erp_company_id": None})
    with inline_queue(execute=True):
        assert signed_post(envelope).status_code == 200
    assert Inbox.objects.get(event_id=envelope["id"]).status == "processed"
    assert not Company.objects.filter(name=envelope["data"]["client"]["name"]).exists()
    assert not CrmClientMapping.objects.filter(crm_client_id=999999).exists()
