"""FIX-22: строки поставки — своя модель на строке подтверждённого заказа, приёмка и замечание клиента.

`GET /deliveries` собирается из `sales.DeliveryLine`; `POST /deliveries/{id}/accept` — только `delivered` → `accepted`,
`/dispute {reason}` — `delivered` → `disputed` с замечанием и задачей менеджеру сделки. События для CRM
(`delivery.line_accepted|disputed`) — волна 3: здесь их нет. На каждый эндпоинт — чужая компания → 404,
`can_act=false` → 403, повтор действия → 409.
"""

from __future__ import annotations

import pytest
from django.utils import timezone
from integration.models import IntegrationWebhookEvent
from portal.tests.contract_support import check_response, component, response_schema
from sales.models import DeliveryLine, DeliveryLineStatus
from sales.services.delivery_lines import accept_delivery_line, dispute_delivery_line, sync_delivery_lines

from accounts.models import CustomUser
from crm.constants import FulfillmentStatusCode, QuoteStatusCode
from crm.models import ActivityLog, Fulfillment, FulfillmentStatus, Quote, QuoteItem, QuoteStatus
from notifications.models import Notification, NotificationType

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


def lines_of(world, key):
    """Строки сделки с данным статусом исполнения — после того как клиент открыл список (строки создаёт он)."""
    deal = world["deliveries"][key].deal
    return list(DeliveryLine.objects.filter(deal=deal).order_by("line_no"))


@pytest.fixture
def listed(contract_world, portal_client):
    """Клиент открыл `GET /deliveries`: строки заказов созданы из подтверждённых КП."""
    response = portal_client.get(f"{API}/deliveries")
    assert response.status_code == 200
    return response.json()


# ── GET /deliveries ──────────────────────────────────────────────────────────────────────────────


def test_list_is_built_from_the_delivery_line_model(contract_world, portal_client, listed):
    stored = {line.pk: line for line in DeliveryLine.objects.all()}
    assert {item["id"] for item in listed} == set(stored)
    assert len(listed) == 12  # шесть сделок исполнения по две оплачиваемые позиции; сделка без КП строк не даёт
    by_status = {item["status"] for item in listed}
    assert by_status == {"assembling", "shipped", "in_transit", "delivered", "accepted", "disputed"}
    for item in listed:
        assert not check_response(item, component("DeliveryLine"))
        line = stored[item["id"]]
        assert item["line_no"] == line.line_no and item["title"] == line.title and item["deal_id"] == line.deal_id


def test_list_is_only_my_company(contract_world, other_portal_client, listed):
    assert other_portal_client.get(f"{API}/deliveries").json() == []


def test_list_does_not_query_per_line(contract_world, portal_client, listed, django_assert_max_num_queries):
    with django_assert_max_num_queries(12):
        assert len(portal_client.get(f"{API}/deliveries").json()) == 12


def test_warehouse_progress_flows_into_lines_until_the_client_decides(contract_world, portal_client, listed):
    shipped = contract_world["deliveries"]["shipped"]
    Fulfillment.objects.filter(pk=shipped.pk).update(
        status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.DELIVERED), tracking_number="TRK-NEW"
    )
    after = [i for i in portal_client.get(f"{API}/deliveries").json() if i["deal_id"] == shipped.deal_id]
    assert {i["status"] for i in after} == {"delivered"} and {i["tracking"] for i in after} == {"TRK-NEW"}

    first = after[0]["id"]
    assert post(portal_client, f"/deliveries/{first}/accept").status_code == 200
    Fulfillment.objects.filter(pk=shipped.pk).update(
        status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.PENDING)
    )
    again = {i["id"]: i for i in portal_client.get(f"{API}/deliveries").json()}
    assert again[first]["status"] == "accepted"  # решение клиента ход склада не откатывает
    assert {i["status"] for key, i in again.items() if key != first and i["deal_id"] == shipped.deal_id} == {
        "assembling"
    }


# ── POST /deliveries/{id}/accept ─────────────────────────────────────────────────────────────────


def test_accept_delivered_line(contract_world, portal_client, listed, client_contact):
    line = lines_of(contract_world, "delivered")[0]
    response = post(portal_client, f"/deliveries/{line.pk}/accept")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == line.pk and body["status"] == "accepted" and body["accepted_at"] and body["remark"] is None
    assert not check_response(body, response_schema("/deliveries/{id}/accept", "post", "200"))
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.ACCEPTED and line.accepted_at
    event = ActivityLog.objects.get(event_code="delivery.line_accepted", deal=line.deal)
    assert event.event_params["line_id"] == line.pk and event.event_params["contact_id"] == client_contact.pk
    # соседняя строка той же сделки не затронута
    sibling = lines_of(contract_world, "delivered")[1]
    assert sibling.status == DeliveryLineStatus.DELIVERED


@pytest.mark.parametrize("key", ["assembling", "shipped", "in_transit", "accepted", "disputed"])
def test_accept_is_only_for_delivered_lines(contract_world, portal_client, listed, key):
    line = lines_of(contract_world, key)[0]
    response = post(portal_client, f"/deliveries/{line.pk}/accept")
    assert response.status_code == 409 and response.json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}
    status_before = line.status
    line.refresh_from_db()
    assert line.status == status_before


def test_accept_repeat_is_409(contract_world, portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    again = post(portal_client, f"/deliveries/{line.pk}/accept")
    assert again.status_code == 409 and again.json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}


def test_accept_other_company_is_404(contract_world, other_portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    response = post(other_portal_client, f"/deliveries/{line.pk}/accept")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED


def test_accept_without_can_act_is_403(contract_world, readonly_portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    response = post(readonly_portal_client, f"/deliveries/{line.pk}/accept")
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED


def test_accept_unknown_line_is_404_and_without_session_401(contract_world, portal_client, anon_portal_client):
    assert post(portal_client, "/deliveries/999999/accept").status_code == 404
    assert post(anon_portal_client, "/deliveries/1/accept").status_code == 401


# ── POST /deliveries/{id}/dispute ────────────────────────────────────────────────────────────────


def test_dispute_delivered_line_records_the_remark_and_notifies_the_deal_manager(
    contract_world, portal_client, listed, client_contact, django_capture_on_commit_callbacks
):
    line = lines_of(contract_world, "delivered")[0]
    manager = CustomUser.objects.create_user(email="mgr@fix22.test", username="mgr@fix22.test", password="x")
    type(line.deal).objects.filter(pk=line.deal_id).update(assigned_to=manager)
    NotificationType.objects.get_or_create(code="WARNING", defaults={"name": "Warning", "sort_order": 20})

    with django_capture_on_commit_callbacks(execute=True):
        response = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "Часть труб с трещинами"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disputed" and body["remark"] == "Часть труб с трещинами" and body["accepted_at"]
    assert not check_response(body, response_schema("/deliveries/{id}/dispute", "post", "200"))
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DISPUTED and line.remark == "Часть труб с трещинами"
    event = ActivityLog.objects.get(event_code="delivery.line_disputed", deal=line.deal)
    assert (
        event.event_params["reason"] == "Часть труб с трещинами"
        and event.event_params["contact_id"] == client_contact.pk
    )
    task = Notification.objects.get(event_code="delivery.line_disputed", user=manager)
    assert "Часть труб с трещинами" in task.message and task.deal_id == line.deal_id


@pytest.mark.parametrize("key", ["assembling", "shipped", "in_transit", "accepted", "disputed"])
def test_dispute_is_only_for_delivered_lines(contract_world, portal_client, listed, key):
    line = lines_of(contract_world, key)[0]
    response = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "нет"})
    assert response.status_code == 409 and response.json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}


def test_dispute_repeat_and_accept_after_dispute_are_409(contract_world, portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "брак"}).status_code == 200
    assert post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "брак"}).status_code == 409
    assert post(portal_client, f"/deliveries/{line.pk}/accept").json() == {"detail": "DELIVERY_LINE_NOT_ACCEPTABLE"}


def test_dispute_reason_is_required_and_bounded(contract_world, portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    blank = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "   "})
    assert blank.status_code == 422 and blank.json() == {"detail": "REASON_REQUIRED"}
    long = post(portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x" * 2001})
    assert long.status_code == 422 and long.json() == {"detail": "VALIDATION_ERROR"}
    line.refresh_from_db()
    assert line.status == DeliveryLineStatus.DELIVERED


def test_dispute_other_company_is_404(contract_world, other_portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    response = post(other_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"})
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_dispute_without_can_act_is_403(contract_world, readonly_portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    response = post(readonly_portal_client, f"/deliveries/{line.pk}/dispute", {"reason": "x"})
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}


def test_dispute_without_session_is_401(contract_world, anon_portal_client):
    assert post(anon_portal_client, "/deliveries/1/dispute", {"reason": "x"}).status_code == 401


def test_no_crm_events_are_emitted_in_this_wave(contract_world, portal_client, listed):
    """`delivery.line_accepted|disputed` — волна 3 (контракт событий не менялся); здесь в очередь вебхуков ничего нет."""
    accepted, disputed = lines_of(contract_world, "delivered")
    post(portal_client, f"/deliveries/{accepted.pk}/accept")
    post(portal_client, f"/deliveries/{disputed.pk}/dispute", {"reason": "брак"})
    assert not IntegrationWebhookEvent.objects.filter(event_type__startswith="delivery.line").exists()


# ── Сервис: инварианты независимо от портала ────────────────────────────────────────────────────


def test_service_requires_a_contact_of_the_same_company_with_can_act(
    contract_world, listed, readonly_contact, other_contact, client_contact
):
    line = lines_of(contract_world, "delivered")[0]
    for contact in (other_contact, readonly_contact):
        assert accept_delivery_line(line.pk, contact) == (None, "MEMBER_REQUIRED_FOR_ACTION")
        assert dispute_delivery_line(line.pk, contact, "брак") == (None, "MEMBER_REQUIRED_FOR_ACTION")
    assert accept_delivery_line(line.pk, client_contact)[1] is None


def test_sync_is_idempotent_and_creates_each_order_line_once(contract_world):
    fulfillments = list(Fulfillment.objects.select_related("status").filter(deal__company=contract_world["company"]))
    assert sync_delivery_lines(fulfillments) == 12
    assert sync_delivery_lines(fulfillments) == 0
    assert DeliveryLine.objects.count() == 12
    assert len({line.quote_item_id for line in DeliveryLine.objects.all()}) == 12  # одна строка на позицию заказа


def test_line_keeps_the_order_snapshot_when_the_quote_item_changes_later(contract_world, portal_client, listed):
    line = lines_of(contract_world, "delivered")[0]
    line.quote_item.__class__.objects.filter(pk=line.quote_item_id).update(
        imported_raw_name="Переименовано", quantity=99
    )
    sync_delivery_lines([Fulfillment.objects.select_related("status").get(deal=line.deal)])
    line.refresh_from_db()
    assert line.title == "Труба 89х4 ст20" and line.quantity == 150  # подтверждённый заказ не правится задним числом


# ── Гонка: решение клиента между чтением и записью sync не теряется ────────────────────────────────


def _client_decides_during_sync(monkeypatch, deal, status):
    """Подмена `_line_status`: пока sync держит прочитанный заранее снимок, клиент принимает/оспаривает строки."""
    from sales.services import delivery_lines as module

    original = module._line_status
    fired = []

    def racing(fulfillment):
        if not fired:
            fired.append(True)
            DeliveryLine.objects.filter(deal=deal).update(status=status, accepted_at=timezone.now())
        return original(fulfillment)

    monkeypatch.setattr(module, "_line_status", racing)


@pytest.mark.parametrize("status", [DeliveryLineStatus.ACCEPTED, DeliveryLineStatus.DISPUTED])
def test_sync_does_not_overwrite_a_decision_made_while_it_was_running(contract_world, listed, monkeypatch, status):
    fulfillment = contract_world["deliveries"]["delivered"]
    deal = fulfillment.deal
    Fulfillment.objects.filter(pk=fulfillment.pk).update(
        status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.IN_TRANSIT)
    )
    _client_decides_during_sync(monkeypatch, deal, status)

    sync_delivery_lines([Fulfillment.objects.select_related("status").get(pk=fulfillment.pk)])

    lines = DeliveryLine.objects.filter(deal=deal)
    assert {line.status for line in lines} == {status} and all(line.accepted_at for line in lines)


def test_sync_does_not_delete_a_line_the_client_decided_on_meanwhile(contract_world, listed, monkeypatch):
    fulfillment = contract_world["deliveries"]["delivered"]
    deal = fulfillment.deal
    old_ids = set(DeliveryLine.objects.filter(deal=deal).values_list("pk", flat=True))
    newer = Quote.objects.create(
        deal=deal,
        version=2,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.APPROVED),
        quote_currency=contract_world["uzs"],
    )
    QuoteItem.objects.create(quote=newer, imported_raw_name="Новая редакция", quantity=1, unit="шт")
    _client_decides_during_sync(monkeypatch, deal, DeliveryLineStatus.ACCEPTED)

    sync_delivery_lines([Fulfillment.objects.select_related("status").get(pk=fulfillment.pk)])

    kept = DeliveryLine.objects.filter(pk__in=old_ids)
    assert kept.count() == len(old_ids) and {line.status for line in kept} == {DeliveryLineStatus.ACCEPTED}
