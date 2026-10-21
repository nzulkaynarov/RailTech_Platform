"""FIX-62: возврат акта клиентом выпускает `act.returned` с причиной (Q-FIX35-5).

Статуса «возвращён» у акта в ERP нет: `reject_act` ставит `DRAFT` и пишет причину в `rejection_reason`. Событие уходит по
факту этого перехода (`ISSUED` → `DRAFT` с причиной) из сигнала акта, действующее лицо — клиент с именем контакта. Тело
проверяется по `events.schema.json` строго (`event_errors`). Повторного события нет, отказы (409, 403, 404, 422) событий
не дают. Возврат из ERP невозможен (FIX-13): сотрудник «заказчиком» не бывает.
"""

from __future__ import annotations

import pytest
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from integration.services import webhooks

from core.tests.events_contract import event_errors
from crm.constants import ActStatusCode
from crm.services.billing import reject_act

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
CRM_CLIENT_ID = 4243
REASON = "Не совпадает количество труб"


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


@pytest.fixture
def mapped(client_company):
    return CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)


def returned_events():
    return IntegrationWebhookEvent.objects.filter(event_type="act.returned")


def test_portal_return_emits_act_returned_with_the_reason(contract_world, portal_client, mapped, client_contact):
    act = contract_world["acts"]["issued"]

    response = post(portal_client, f"/acts/{act.pk}/return", {"reason": f"  {REASON} "})

    assert response.status_code == 200
    event = returned_events().get()
    assert event.headers["X-Event-Type"] == "act.returned"
    envelope = event.payload
    assert event_errors(envelope) == []  # строго по схеме: лишних и недостающих полей нет
    assert envelope["event"] == "act.returned"
    assert envelope["erp_company_id"] == act.deal.company_id and envelope["crm_client_id"] == CRM_CLIENT_ID
    assert envelope["actor"] == {"type": "client", "name": client_contact.name}
    assert envelope["deal"] == webhooks.build_deal_ref(act.deal)
    assert envelope["payload"] == {"erp_act_id": act.pk, "number": act.number, "reason": REASON}


def test_service_path_emits_the_same_event(contract_world, mapped, client_contact):
    """Сервис `reject_act` с контактом портала — тот же путь, что и у эндпоинта: событие выпускает переход, а не вьюха."""
    act = contract_world["acts"]["issued"]

    returned, error = reject_act(act.pk, None, REASON, portal_contact=client_contact)

    assert error is None and returned.status.code == ActStatusCode.DRAFT
    event = returned_events().get()
    assert event_errors(event.payload) == []
    assert event.payload["payload"]["reason"] == REASON
    assert event.payload["actor"] == {"type": "client", "name": client_contact.name}


def test_failed_returns_emit_nothing(
    contract_world, portal_client, readonly_portal_client, other_portal_client, mapped
):
    act = contract_world["acts"]["issued"]
    assert post(portal_client, f"/acts/{act.pk}/return", {"reason": "   "}).status_code == 422
    assert post(readonly_portal_client, f"/acts/{act.pk}/return", {"reason": REASON}).status_code == 403
    assert post(other_portal_client, f"/acts/{act.pk}/return", {"reason": REASON}).status_code == 404
    assert (
        post(portal_client, f"/acts/{contract_world['acts']['accepted'].pk}/return", {"reason": REASON}).status_code
        == 409
    )
    assert (
        post(portal_client, f"/acts/{contract_world['acts']['returned'].pk}/return", {"reason": REASON}).status_code
        == 409
    )
    assert not returned_events().exists()


def test_a_repeat_return_gives_no_second_event(contract_world, portal_client, mapped):
    act = contract_world["acts"]["issued"]
    assert post(portal_client, f"/acts/{act.pk}/return", {"reason": REASON}).status_code == 200
    assert post(portal_client, f"/acts/{act.pk}/return", {"reason": REASON}).status_code == 409
    assert returned_events().count() == 1


def test_staff_cannot_return_an_act_from_inside_erp_and_no_event_follows(contract_world, mapped):
    """Сторона-исполнитель акт не возвращает (FIX-13): `ACT_ACCEPTOR_SIDE_REQUIRED`, акт и события не тронуты."""
    from accounts.models import CustomUser

    act = contract_world["acts"]["issued"]
    staff = CustomUser.objects.create_user(
        email="fix62-staff@example.com", username="fix62-staff@example.com", password="x", is_superuser=True
    )
    assert reject_act(act.pk, staff, REASON) == (None, "ACT_ACCEPTOR_SIDE_REQUIRED")
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.ISSUED
    assert not returned_events().exists()


def test_no_event_for_a_company_not_linked_to_crm(contract_world, portal_client):
    act = contract_world["acts"]["issued"]
    assert post(portal_client, f"/acts/{act.pk}/return", {"reason": REASON}).status_code == 200
    assert not returned_events().exists()


def test_a_draft_that_was_never_issued_is_not_a_return(contract_world, mapped):
    """Создание черновика акта или правка draft→draft события не даёт: возврат — это ISSUED → DRAFT с причиной."""
    from integration.tests.world import add_act

    act = add_act(contract_world["acts"]["issued"].deal, ActStatusCode.DRAFT)
    act.rejection_reason = "заметка исполнителя"
    act.save(update_fields=["rejection_reason", "updated_at"])
    assert not returned_events().exists()
