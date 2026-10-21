"""FIX-62 (Q-FIX22-5, ч. 2): все строки поставки приняты клиентом → исполнение сделки `ACCEPTED`.

Переход идёт через сервис `update_fulfillment_status` с актором «клиент» (контакт портала с `can_act`), а не в обход
FIX-13: человека-исполнителя для приёмки по-прежнему нет, сервис отвергает любого пользователя ERP. Частичная приёмка
и спор исполнение не меняют. Переход оставляет запись в журнале (кто принял) и событие `delivery.status_changed` с
`actor.type=client`. Срыв перехода не отменяет решение клиента по строке: след в журнале для ручного разбора.
"""

from __future__ import annotations

import pytest
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from sales.models import ActivityLog, DeliveryLine, DeliveryLineStatus
from sales.services import delivery_lines

from core.tests.events_contract import event_errors
from crm.constants import FulfillmentStatusCode
from crm.services import update_fulfillment_status

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
CRM_CLIENT_ID = 4244


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


@pytest.fixture
def listed(contract_world, portal_client):
    assert portal_client.get(f"{API}/deliveries").status_code == 200


@pytest.fixture
def mapped(client_company):
    return CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)


def delivered_fulfillment(world):
    return world["deliveries"]["delivered"]


def lines_of(fulfillment):
    return list(DeliveryLine.objects.filter(deal=fulfillment.deal).order_by("line_no"))


def status_events():
    return IntegrationWebhookEvent.objects.filter(event_type="delivery.status_changed")


def code_of(fulfillment):
    fulfillment.refresh_from_db()
    return fulfillment.status.code


def test_the_last_accepted_line_moves_the_fulfillment_to_accepted(
    contract_world, portal_client, listed, mapped, client_contact
):
    fulfillment = delivered_fulfillment(contract_world)
    first, last = lines_of(fulfillment)
    assert len(lines_of(fulfillment)) == 2

    assert post(portal_client, f"/deliveries/{first.pk}/accept").status_code == 200
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED  # одной принятой строки мало
    assert not status_events().exists()

    assert post(portal_client, f"/deliveries/{last.pk}/accept").status_code == 200
    assert code_of(fulfillment) == FulfillmentStatusCode.ACCEPTED
    assert fulfillment.accepted_at is not None

    event = status_events().get()
    assert event_errors(event.payload) == []
    assert event.payload["actor"] == {"type": "client", "name": client_contact.name}
    # в контракте у статуса поставки нет `accepted` (Q-FIX62-1): физически это «доставлено», приёмка — в line_summary
    assert event.payload["payload"]["status"] == "delivered"
    assert event.payload["payload"]["line_summary"] == "Все строки приняты клиентом"
    assert event.payload["deal"]["erp_deal_id"] == fulfillment.deal_id


def test_the_change_is_audited_with_the_client_as_the_actor(
    contract_world, portal_client, listed, mapped, client_contact
):
    fulfillment = delivered_fulfillment(contract_world)
    for line in lines_of(fulfillment):
        assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200

    entry = ActivityLog.objects.get(event_code="fulfillment.accepted_by_client", deal=fulfillment.deal)
    assert entry.user is None  # пользователя ERP за этим шагом нет: актор — контакт клиента, он в параметрах
    assert entry.event_params["contact_id"] == client_contact.pk
    assert entry.event_params["deal_id"] == fulfillment.deal_id
    assert client_contact.name in entry.detail


def test_a_dispute_keeps_the_fulfillment_unchanged(contract_world, portal_client, listed, mapped):
    fulfillment = delivered_fulfillment(contract_world)
    first, last = lines_of(fulfillment)
    assert post(portal_client, f"/deliveries/{first.pk}/accept").status_code == 200
    assert post(portal_client, f"/deliveries/{last.pk}/dispute", {"reason": "Брак"}).status_code == 200

    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED
    assert not status_events().exists()
    assert not ActivityLog.objects.filter(event_code="fulfillment.accepted_by_client").exists()


def test_a_disputed_line_first_then_accept_keeps_the_fulfillment_unchanged(
    contract_world, portal_client, listed, mapped
):
    fulfillment = delivered_fulfillment(contract_world)
    first, last = lines_of(fulfillment)
    assert post(portal_client, f"/deliveries/{first.pk}/dispute", {"reason": "Брак"}).status_code == 200
    assert post(portal_client, f"/deliveries/{last.pk}/accept").status_code == 200
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED


def test_warehouse_progress_after_acceptance_does_not_reopen_the_fulfillment(
    contract_world, portal_client, listed, mapped
):
    """Принятое исполнение остаётся принятым: повторный список строк не меняет ни статус, ни число событий."""
    fulfillment = delivered_fulfillment(contract_world)
    for line in lines_of(fulfillment):
        post(portal_client, f"/deliveries/{line.pk}/accept")
    assert portal_client.get(f"{API}/deliveries").status_code == 200
    assert code_of(fulfillment) == FulfillmentStatusCode.ACCEPTED
    assert status_events().count() == 1


def test_a_company_not_linked_to_crm_still_gets_the_fulfillment_accepted_without_an_event(
    contract_world, portal_client, listed
):
    fulfillment = delivered_fulfillment(contract_world)
    for line in lines_of(fulfillment):
        assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    assert code_of(fulfillment) == FulfillmentStatusCode.ACCEPTED
    assert not status_events().exists()


def test_a_failing_transition_does_not_undo_the_clients_decision(
    contract_world, portal_client, listed, mapped, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("fulfillment service is broken")

    monkeypatch.setattr("crm.services.fulfillment.update_fulfillment_status", boom)
    fulfillment = delivered_fulfillment(contract_world)
    for line in lines_of(fulfillment):
        assert post(portal_client, f"/deliveries/{line.pk}/accept").status_code == 200
    assert {line.status for line in lines_of(fulfillment)} == {DeliveryLineStatus.ACCEPTED}
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED
    trace = ActivityLog.objects.get(event_code="fulfillment.accept_failed", deal=fulfillment.deal)
    assert trace.event_params["deal_id"] == fulfillment.deal_id and trace.level == "ERROR"


def test_a_fulfillment_not_yet_delivered_is_not_moved(contract_world, portal_client, listed, mapped, client_contact):
    """Строки принять нельзя, пока склад не довёз, но и хелпер сам исполнение до `DELIVERED` не двигает."""
    fulfillment = contract_world["deliveries"]["shipped"]
    line = lines_of(fulfillment)[0]
    DeliveryLine.objects.filter(deal=fulfillment.deal).update(status=DeliveryLineStatus.ACCEPTED)
    assert delivery_lines.close_fulfillment_if_all_accepted(line.deal_id, client_contact) is None
    assert code_of(fulfillment) == FulfillmentStatusCode.SHIPPED


# ── Сервис: клиентский актор не открывает дверь людям ───────────────────────────────────────────


def test_a_user_of_erp_still_cannot_accept_the_fulfillment(contract_world):
    from accounts.models import CustomUser

    fulfillment = delivered_fulfillment(contract_world)
    staff = CustomUser.objects.create_user(
        email="fix62-staff@example.com", username="fix62-staff@example.com", password="x", is_superuser=False
    )
    result = update_fulfillment_status(fulfillment.deal_id, staff, FulfillmentStatusCode.ACCEPTED)
    assert result == (None, "FULFILLMENT_ACCEPTANCE_IS_BUYER_STEP")
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED


def test_the_client_actor_must_be_an_acting_contact_of_the_deals_company(
    contract_world, readonly_portal_client, other_portal_client, client_contact
):
    from parties.models import Contact

    fulfillment = delivered_fulfillment(contract_world)
    outsider = Contact.objects.exclude(company_id=fulfillment.deal.company_id).first()
    readonly = Contact.objects.filter(company_id=fulfillment.deal.company_id, can_act=False).first()
    for contact in (outsider, readonly, None):
        result = update_fulfillment_status(
            fulfillment.deal_id, None, FulfillmentStatusCode.ACCEPTED, client_contact=contact
        )
        assert result[0] is None and result[1] in ("MEMBER_REQUIRED_FOR_ACTION", "FULFILLMENT_ACCEPTANCE_IS_BUYER_STEP")
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED
    obj, error = update_fulfillment_status(
        fulfillment.deal_id, None, FulfillmentStatusCode.ACCEPTED, client_contact=client_contact
    )
    assert error is None and obj.status.code == FulfillmentStatusCode.ACCEPTED


def test_the_client_actor_cannot_drive_seller_statuses(contract_world, client_contact):
    fulfillment = delivered_fulfillment(contract_world)
    for status in (FulfillmentStatusCode.SHIPPED, FulfillmentStatusCode.IN_TRANSIT, FulfillmentStatusCode.DELIVERED):
        result = update_fulfillment_status(fulfillment.deal_id, None, status, client_contact=client_contact)
        assert result[0] is None
    assert code_of(fulfillment) == FulfillmentStatusCode.DELIVERED
