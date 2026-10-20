"""FIX-37: приёмка и замечание по строке поставки уходят в CRM событиями `delivery.line_accepted|disputed`.

Тело события валидируется по `packages/contracts/events.schema.json` (DeliveryLineDecision, `actor.type=client` с
именем контакта, `deal` — DealRef из `stages.py`). Событие ставится в очередь только после коммита решения; отказ
(409, 403, 404, 422) и повтор действия событий не дают.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from integration.services import webhooks
from sales.models import DeliveryLine, DeliveryLineStatus

from core.tests.events_contract import event_errors

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
CRM_CLIENT_ID = 4242


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


@pytest.fixture
def listed(contract_world, portal_client):
    assert portal_client.get(f"{API}/deliveries").status_code == 200


@pytest.fixture
def mapped(client_company):
    return CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)


@pytest.fixture
def delay(monkeypatch):
    """Постановка доставки вебхука в Celery: проверяем, когда и с чем её вызвали."""
    from integration import tasks

    mock = MagicMock()
    monkeypatch.setattr(tasks.deliver_webhook_event, "delay", mock)
    return mock


def delivered_lines(world):
    deal = world["deliveries"]["delivered"].deal
    return list(DeliveryLine.objects.filter(deal=deal).order_by("line_no"))


def line_events():
    return IntegrationWebhookEvent.objects.filter(event_type__startswith="delivery.line_")


# ── Приёмка ──────────────────────────────────────────────────────────────────────────────────────


def test_accept_sends_the_event_after_commit_and_it_matches_the_schema(
    contract_world, portal_client, listed, mapped, client_contact, delay, django_capture_on_commit_callbacks
):
    line = delivered_lines(contract_world)[0]

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = post(portal_client, f"/deliveries/{line.pk}/accept")

    assert response.status_code == 200
    event = line_events().get()
    assert event.event_type == "delivery.line_accepted"
    assert event.headers["X-Event-Type"] == "delivery.line_accepted"
    envelope = event.payload
    assert event_errors(envelope) == []
    assert envelope["erp_company_id"] == line.deal.company_id and envelope["crm_client_id"] == CRM_CLIENT_ID
    assert envelope["actor"] == {"type": "client", "name": client_contact.name}
    assert envelope["deal"] == webhooks.build_deal_ref(line.deal)
    line.refresh_from_db()
    assert envelope["occurred_at"] == line.accepted_at.isoformat()
    assert envelope["payload"] == {
        "line_no": line.line_no,
        "title": line.title,
        "status": "accepted",
        "decided_at": line.accepted_at.isoformat(),
    }
    # до коммита доставку никто не ставил; после — ровно одна задача на это событие
    delay.assert_not_called()
    for callback in callbacks:
        callback()
    delay.assert_called_once_with(event.id)


def test_repeat_accept_is_409_and_sends_no_second_event(contract_world, portal_client, listed, mapped):
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    again = post(portal_client, f"/deliveries/{line.pk}/accept")
    assert again.status_code == 409 and again.json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}
    assert line_events().count() == 1


# ── Замечание ────────────────────────────────────────────────────────────────────────────────────


def test_dispute_sends_the_event_with_the_remark(
    contract_world, portal_client, listed, mapped, client_contact, delay, django_capture_on_commit_callbacks
):
    line = delivered_lines(contract_world)[0]

    with django_capture_on_commit_callbacks(execute=True):
        response = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "  Часть труб с трещинами "})

    assert response.status_code == 200
    event = line_events().get()
    assert event.event_type == "delivery.line_disputed"
    envelope = event.payload
    assert event_errors(envelope) == []
    assert envelope["actor"] == {"type": "client", "name": client_contact.name}
    assert envelope["payload"]["status"] == "disputed"
    assert envelope["payload"]["remark"] == "Часть труб с трещинами"  # то же, что записано в строке, без пробелов
    line.refresh_from_db()
    assert (
        envelope["payload"]["remark"] == line.remark
        and envelope["payload"]["decided_at"] == line.accepted_at.isoformat()
    )
    delay.assert_called_once_with(event.id)


def test_dispute_and_accept_of_neighbour_lines_give_one_event_each(contract_world, portal_client, listed, mapped):
    accepted, disputed = delivered_lines(contract_world)
    post(portal_client, f"/deliveries/{accepted.pk}/accept")
    post(portal_client, f"/deliveries/{disputed.pk}/dispute", {"reason": "брак"})
    by_type = {event.event_type: event.payload["payload"]["line_no"] for event in line_events()}
    assert by_type == {"delivery.line_accepted": accepted.line_no, "delivery.line_disputed": disputed.line_no}
    assert all(event_errors(event.payload) == [] for event in line_events())


# ── Отказы: события нет ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["assembling", "shipped", "in_transit", "accepted", "disputed"])
def test_no_event_when_the_line_is_not_acceptable_409(contract_world, portal_client, listed, mapped, delay, key):
    line = DeliveryLine.objects.filter(deal=contract_world["deliveries"][key].deal).first()
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 409
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "нет"}).status_code == 409
    assert not line_events().exists()
    delay.assert_not_called()


def test_no_event_for_blank_reason_without_can_act_and_other_company(
    contract_world, portal_client, readonly_portal_client, other_portal_client, listed, mapped, delay
):
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "   "}).status_code == 422
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x" * 2001}).status_code == 422
    assert post(readonly_portal_client, f"/deliveries/{line.pk}/accept").status_code == 403
    assert post(readonly_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"}).status_code == 403
    assert post(other_portal_client, f"/deliveries/{line.pk}/accept").status_code == 404
    assert post(other_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"}).status_code == 404
    assert not line_events().exists()
    delay.assert_not_called()
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED


def test_no_event_for_a_company_not_linked_to_crm(contract_world, portal_client, listed, delay):
    """Компания без клиента в CRM: решение принято, события нет (как у остальных событий — слать некому)."""
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    assert not line_events().exists()


def test_a_failing_event_does_not_undo_the_clients_decision(contract_world, portal_client, listed, mapped, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("webhook builder is broken")

    monkeypatch.setattr(webhooks, "emit_event", boom)
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.ACCEPTED


# ── Сторож схемы сам ловит нарушения ─────────────────────────────────────────────────────────────


def _valid_disputed():
    return {
        "version": 1,
        "event": "delivery.line_disputed",
        "occurred_at": "2026-10-20T10:00:00+05:00",
        "erp_company_id": 1,
        "crm_client_id": 2,
        "deal": {
            "erp_deal_id": 3,
            "number": "D-3",
            "title": "Сделка",
            "stage": "fulfilment",
            "amount": None,
            "currency": "UZS",
        },
        "actor": {"type": "client", "name": "Азамат"},
        "payload": {
            "line_no": 1,
            "title": "Труба",
            "status": "disputed",
            "remark": "Брак",
            "decided_at": "2026-10-20T10:00:00+05:00",
        },
    }


def test_schema_guard_accepts_a_valid_body_and_rejects_broken_ones():
    assert event_errors(_valid_disputed()) == []

    no_remark = _valid_disputed()
    del no_remark["payload"]["remark"]
    assert event_errors(no_remark)  # замечание при disputed обязательно

    staff = _valid_disputed()
    staff["actor"] = {"type": "staff"}
    assert event_errors(staff)  # решение принимает только клиент

    no_deal = _valid_disputed()
    del no_deal["deal"]
    assert event_errors(no_deal)

    extra = _valid_disputed()
    extra["payload"]["supplier"] = "секрет"
    assert event_errors(extra)

    wrong_status = _valid_disputed()
    wrong_status["payload"]["status"] = "delivered"
    assert event_errors(wrong_status)
