"""FIX-37: приёмка и замечание по строке поставки уходят в CRM событиями `delivery.line_accepted|disputed` (шина rt_bus, B3).

Тело проверяется по схемам `packages/contracts/events/erp/delivery.line_*.v1.json` (DeliveryLineDecision, `actor.type=client`
с именем контакта, `deal` — DealRef из `stages.py`). Событие пишется в outbox в транзакции решения: откат решения — нет
события, ошибка публикации откатывает само решение; отказ (409, 403, 404, 422) и повтор действия событий не дают.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from integration.models import CrmClientMapping
from integration.services import events as bus_events
from integration.tests import bus_support
from sales.models import ActivityLog, DeliveryLine, DeliveryLineStatus

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


def delivered_lines(world):
    deal = world["deliveries"]["delivered"].deal
    return list(DeliveryLine.objects.filter(deal=deal).order_by("line_no"))


def line_events():
    return [*bus_support.published("delivery.line_accepted"), *bus_support.published("delivery.line_disputed")]


def moment(envelope) -> datetime:
    return datetime.fromisoformat(envelope["time"].replace("Z", "+00:00"))


# ── Приёмка ──────────────────────────────────────────────────────────────────────────────────────


def test_accept_publishes_the_event_in_the_decision_transaction_and_it_matches_the_schema(
    contract_world, portal_client, listed, mapped, client_contact
):
    line = delivered_lines(contract_world)[0]

    response = post(portal_client, f"/deliveries/{line.pk}/accept")

    assert response.status_code == 200
    event = bus_support.only("delivery.line_accepted")
    assert event["type"] == "uz.railtech.erp.delivery.line_accepted.v1"
    bus_support.assert_matches_contract(event)
    envelope = event["data"]
    assert envelope["erp_company_id"] == line.deal.company_id and envelope["crm_client_id"] == CRM_CLIENT_ID
    assert envelope["actor"] == {"type": "client", "name": client_contact.name}
    assert envelope["deal"] == bus_events.build_deal_ref(line.deal)
    line.refresh_from_db()
    assert abs(moment(event) - line.accepted_at) < timedelta(milliseconds=1), "время события — момент решения клиента"
    assert envelope["payload"] == {
        "line_no": line.line_no,
        "title": line.title,
        "status": "accepted",
        "decided_at": line.accepted_at.isoformat(),
    }


def test_repeat_accept_is_409_and_sends_no_second_event(contract_world, portal_client, listed, mapped):
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    again = post(portal_client, f"/deliveries/{line.pk}/accept")
    assert again.status_code == 409 and again.json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}
    assert len(line_events()) == 1


# ── Замечание ────────────────────────────────────────────────────────────────────────────────────


def test_dispute_publishes_the_event_with_the_remark(contract_world, portal_client, listed, mapped, client_contact):
    line = delivered_lines(contract_world)[0]

    response = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "  Часть труб с трещинами "})

    assert response.status_code == 200
    event = bus_support.only("delivery.line_disputed")
    bus_support.assert_matches_contract(event)
    envelope = event["data"]
    assert envelope["actor"] == {"type": "client", "name": client_contact.name}
    assert envelope["payload"]["status"] == "disputed"
    assert envelope["payload"]["remark"] == "Часть труб с трещинами"  # то же, что записано в строке, без пробелов
    line.refresh_from_db()
    assert (
        envelope["payload"]["remark"] == line.remark
        and envelope["payload"]["decided_at"] == line.accepted_at.isoformat()
    )


def test_dispute_and_accept_of_neighbour_lines_give_one_event_each(contract_world, portal_client, listed, mapped):
    accepted, disputed = delivered_lines(contract_world)
    post(portal_client, f"/deliveries/{accepted.pk}/accept")
    post(portal_client, f"/deliveries/{disputed.pk}/dispute", {"reason": "брак"})
    by_type = {event["type"]: event["data"]["payload"]["line_no"] for event in line_events()}
    assert by_type == {
        "uz.railtech.erp.delivery.line_accepted.v1": accepted.line_no,
        "uz.railtech.erp.delivery.line_disputed.v1": disputed.line_no,
    }
    for event in line_events():
        bus_support.assert_matches_contract(event)


# ── Отказы: события нет ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["assembling", "shipped", "in_transit", "accepted", "disputed"])
def test_no_event_when_the_line_is_not_acceptable_409(contract_world, portal_client, listed, mapped, key):
    line = DeliveryLine.objects.filter(deal=contract_world["deliveries"][key].deal).first()
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 409
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "нет"}).status_code == 409
    assert not line_events()


def test_no_event_for_blank_reason_without_can_act_and_other_company(
    contract_world, portal_client, readonly_portal_client, other_portal_client, listed, mapped
):
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "   "}).status_code == 422
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x" * 2001}).status_code == 422
    assert post(readonly_portal_client, f"/deliveries/{line.pk}/accept").status_code == 403
    assert post(readonly_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"}).status_code == 403
    assert post(other_portal_client, f"/deliveries/{line.pk}/accept").status_code == 404
    assert post(other_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"}).status_code == 404
    assert not line_events()
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED


def test_no_event_for_a_company_not_linked_to_crm(contract_world, portal_client, listed):
    """Компания без клиента в CRM: решение принято, события нет (как у остальных событий — слать некому)."""
    line = delivered_lines(contract_world)[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    assert not line_events()


@pytest.mark.parametrize("action", ["accept", "dispute"])
def test_a_publication_failure_rolls_the_decision_back(
    contract_world, portal_client, listed, mapped, monkeypatch, action
):
    """Решение клиента и событие — одна транзакция: ошибка публикации откатывает и решение (клиент повторит)."""

    def boom(*args, **kwargs):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(bus_events, "publish_delivery_line_decision", boom)
    line = delivered_lines(contract_world)[0]
    body = {"reason": "брак"} if action == "dispute" else None
    with pytest.raises(RuntimeError):
        post(portal_client, f"/deliveries/{line.pk}/{action}", body)
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED and line.accepted_at is None
    assert not line_events()
    assert not ActivityLog.objects.filter(event_code=f"delivery.line_{action}ed", deal=line.deal).exists()


# ── Схема сама ловит нарушения ───────────────────────────────────────────────────────────────────


def _valid_disputed():
    return {
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


def data_errors(data, event_type="uz.railtech.erp.delivery.line_disputed.v1"):
    return bus_support.registry().validate_data(event_type, data, tolerant=False)


def test_schema_accepts_a_valid_body_and_rejects_broken_ones():
    assert data_errors(_valid_disputed()) == []

    no_remark = _valid_disputed()
    del no_remark["payload"]["remark"]
    assert data_errors(no_remark)  # замечание при disputed обязательно

    staff = _valid_disputed()
    staff["actor"] = {"type": "staff"}
    assert data_errors(staff)  # решение принимает только клиент

    no_deal = _valid_disputed()
    del no_deal["deal"]
    assert data_errors(no_deal)

    extra = _valid_disputed()
    extra["payload"]["supplier"] = "секрет"
    assert data_errors(extra)

    wrong_status = _valid_disputed()
    wrong_status["payload"]["status"] = "delivered"
    assert data_errors(wrong_status)
