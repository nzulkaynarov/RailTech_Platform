"""ЛХ-2: «Закрыть заявку» на любом шаге до проекта (`POST /api/v1/calc/<id>/close/`, `crm.services.calculation`).

Причина — из справочника `request-close-reasons` (данные, не код); стадия «Отказ», событие `deal.lost` в CRM, заявка уходит
из очередей; «Ошибка» и «Тест» без отправленных клиенту документов скрываются из списков. КП уже у клиента — только
причины с `allowed_after_quote_sent`. Право — ответственный заявки или `deal.manage`.
"""

from __future__ import annotations

import pytest
from integration.models import CrmClientMapping
from integration.tests import bus_support

from crm.models import ActivityLog, Deal, DealCloseReason, Quote
from crm.services.quotes._shared import _set_quote_status
from crm.tests.test_calc import _api, _started, _url, world  # noqa: F401 — фикстура world
from crm.tests.test_quote_lifecycle_d26g import _decide, _ready, _sent_and_rejected  # noqa: F401

pytestmark = pytest.mark.django_db


def _close(world, user, reason, comment=""):  # noqa: F811
    return _api(user).post(_url(world, "close/"), {"reason": reason, "comment": comment}, format="json")


def _deal(world):  # noqa: F811
    return Deal.objects.get(pk=world["deal"].pk)


@pytest.mark.parametrize(
    ("code", "comment", "hidden"),
    [
        ("ERROR", "", True),
        ("DUPLICATE", "", False),
        ("TEST", "", True),
        ("CHANGED_MIND", "", False),
        ("NO_REPLY", "", False),
        ("OTHER", "Передали другому подрядчику", False),
    ],
)
def test_every_reason_closes_the_request_before_a_quote_is_sent(world, code, comment, hidden):  # noqa: F811
    CrmClientMapping.objects.create(company=world["deal"].company, crm_client_id=77)
    bus_support.reset()
    response = _close(world, world["supply"], code, comment)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["deal"]["stage_code"] == "CLOSED_LOST"
    assert body["close"]["reason"] == code and body["close"]["allowed"] is False
    deal = _deal(world)
    assert deal.close_reason.code == code and deal.hidden_in_lists is hidden
    assert deal.closed_from_stage == "CALCULATING" and deal.closed_after_quote_sent is False
    assert ActivityLog.objects.filter(deal=deal, event_code="calc.closed").exists()
    # событие в CRM несёт причину; стадия лида в CRM не меняется (потребитель — tests/integration/test_erp_events.py)
    (event,) = bus_support.published("deal.lost")
    bus_support.assert_matches_contract(event)
    assert deal.close_reason.name in bus_support.real_data(event)["payload"]["lost_reason"]
    # из очереди «Заявки в расчёте» исчезла
    assert _api(world["supply"]).get("/api/v1/calc/tasks/").json()["results"] == []


def test_reasons_are_data_and_unknown_or_missing_input_is_refused(world):  # noqa: F811
    listed = _api(world["accountant"]).get("/api/v1/calc/close-reasons/").json()["results"]
    assert [r["code"] for r in listed] == ["ERROR", "DUPLICATE", "TEST", "CHANGED_MIND", "NO_REPLY", "OTHER"]
    DealCloseReason.objects.filter(code="DUPLICATE").update(is_active=False)
    assert "DUPLICATE" not in [
        r["code"] for r in _api(world["supply"]).get("/api/v1/calc/close-reasons/").json()["results"]
    ]
    assert _close(world, world["supply"], "DUPLICATE").json()["detail"] == "REASON_UNKNOWN"
    assert _close(world, world["supply"], "NOPE").status_code == 400
    assert _close(world, world["supply"], "OTHER", "  ").json()["detail"] == "COMMENT_REQUIRED"
    assert _deal(world).stage.code == "CALCULATING"


def test_rights_owner_and_deal_manage_may_close_others_may_not(world):  # noqa: F811
    assert _close(world, world["accountant"], "TEST").status_code == 403
    assert _deal(world).stage.code == "CALCULATING"
    assert _api(world["accountant"]).get(_url(world)).json()["close"]["allowed"] is False
    assert _api(world["supply"]).get(_url(world)).json()["close"]["allowed"] is True
    # держатель зоны продаж (deal.manage), не ответственный заявки
    other = Deal.objects.get(pk=world["deal"].pk)
    other.manager = None
    other.save(update_fields=["manager"])
    assert _close(world, world["engineer"], "DUPLICATE").status_code == 200


def test_owner_without_the_sales_zone_may_close_their_own_request(world):  # noqa: F811
    from accounts.models import CompanyMember, CompanyRole

    member = CompanyMember.objects.get(user=world["supply"])
    role = CompanyRole.objects.create(company=world["seller"], name="Без продаж", permissions=["quote.build"])
    member.company_roles.set([role])
    assert _close(world, world["supply"], "TEST").status_code == 200  # ответственный: manager заявки


def test_after_the_quote_is_sent_only_client_side_reasons_are_allowed(world):  # noqa: F811
    _quote, _goods, _service = _sent_and_rejected(world)  # КП отправлено и отклонено клиентом: заявка снова в расчёте
    for code in ("ERROR", "TEST", "DUPLICATE"):
        response = _close(world, world["supply"], code)
        assert response.status_code == 409 and response.json()["detail"] == "REASON_NOT_ALLOWED_AFTER_QUOTE"
    assert _deal(world).stage.code == "CALCULATING"
    assert _api(world["supply"]).get(_url(world)).json()["close"]["quote_sent"] is True
    response = _close(world, world["supply"], "NO_REPLY")
    assert response.status_code == 200, response.json()
    deal = _deal(world)
    assert deal.closed_after_quote_sent is True and deal.hidden_in_lists is False


def test_closing_a_sent_quote_stops_the_client_from_accepting_it(world):  # noqa: F811
    from crm.services.quotes.lifecycle_accept import perform_quote_acceptance

    _ready(world)
    quote = Quote.objects.get(deal=world["deal"])
    assert _decide(quote, "approve", quote.version) == "applied"
    _set_quote_status(quote, "SENT")
    assert _close(world, world["supply"], "ERROR").status_code == 409
    assert _close(world, world["supply"], "CHANGED_MIND").status_code == 200
    quote.refresh_from_db()
    assert quote.status.code == "REJECTED"
    with pytest.raises(ValueError):
        perform_quote_acceptance(quote.pk)


def test_a_project_and_a_closed_request_cannot_be_closed(world):  # noqa: F811
    assert _close(world, world["supply"], "TEST").status_code == 200
    again = _close(world, world["supply"], "TEST")
    assert again.status_code == 409 and again.json()["detail"] == "REQUEST_NOT_CLOSABLE"
    deal = _deal(world)
    deal.stage = type(deal.stage).objects.get(code="CONTRACT_SIGNED")
    deal.save(update_fields=["stage"])
    assert _close(world, world["supply"], "TEST").json()["detail"] == "REQUEST_NOT_CLOSABLE"


def test_hidden_requests_leave_the_deal_list_but_stay_by_number_and_in_the_journal(world):  # noqa: F811
    assert _close(world, world["supply"], "TEST").status_code == 200
    listed = _api(world["supply"]).get("/api/v1/crm/deals/")
    assert listed.status_code == 200
    assert world["deal"].pk not in [row["id"] for row in listed.json().get("results", listed.json())]
    with_hidden = _api(world["supply"]).get("/api/v1/crm/deals/", {"include_hidden": "1"})
    assert world["deal"].pk in [row["id"] for row in with_hidden.json().get("results", with_hidden.json())]
    assert _api(world["supply"]).get(_url(world)).status_code == 200  # карточка по номеру открывается
    assert Deal.objects.filter(pk=world["deal"].pk).exists(), "удаления нет"
    assert "TEST" == _api(world["supply"]).get(_url(world)).json()["close"]["reason"]
    assert _api(world["supply"]).get("/api/v1/calc/deals/").json()["results"], "справочник номеров не теряет закрытую"


def test_close_conforms_to_the_v1_schema(world):  # noqa: F811
    from core.tests.openapi_fixtures import conforms, sends

    base = "/api/v1/calc/{deal_id}/"
    sends(f"{base}close/", "post", {"reason": "TEST", "comment": ""})
    conforms(_api(world["supply"]).get(_url(world)), base, "get", status=200)
    conforms(_api(world["supply"]).get("/api/v1/calc/close-reasons/"), "/api/v1/calc/close-reasons/", "get", status=200)
    conforms(_api(world["supply"]).get(_url(world, "request/")), f"{base}request/", "get", status=200)
    conforms(_close(world, world["supply"], "TEST"), f"{base}close/", "post", status=200)


def _draft(world):  # noqa: F811
    """Черновик заявки без задания расчёта — как после передачи лида (резолюции директора ещё нет)."""
    from crm.models import DealStage

    return Deal.objects.create(
        title="Передача из CRM",
        company=world["deal"].company,
        manager=world["supply"],
        stage=DealStage.objects.get(code="DRAFT"),
    )


def test_a_draft_request_without_a_calc_task_has_a_card_and_can_be_closed(world):  # noqa: F811
    draft = _draft(world)
    CrmClientMapping.objects.create(company=draft.company, crm_client_id=78)
    bus_support.reset()
    assert _api(world["supply"]).get(f"/api/v1/calc/{draft.pk}/").status_code == 404, "расчёта у черновика нет"
    card = _api(world["supply"]).get(f"/api/v1/calc/{draft.pk}/request/")
    assert card.status_code == 200, card.json()
    assert card.json()["has_task"] is False and card.json()["close"]["allowed"] is True
    assert _api(world["accountant"]).get(f"/api/v1/calc/{draft.pk}/request/").json()["close"]["allowed"] is False
    refused = _api(world["accountant"]).post(f"/api/v1/calc/{draft.pk}/close/", {"reason": "TEST"}, format="json")
    assert refused.status_code == 403
    closed = _api(world["supply"]).post(f"/api/v1/calc/{draft.pk}/close/", {"reason": "TEST"}, format="json")
    assert closed.status_code == 200, closed.json()
    assert closed.json()["deal"]["stage_code"] == "CLOSED_LOST" and closed.json()["close"]["reason"] == "TEST"
    draft.refresh_from_db()
    assert draft.hidden_in_lists is True and draft.close_reason.code == "TEST"
    assert len(bus_support.published("deal.lost")) == 1


def test_deal_refs_find_a_draft_only_when_any_request_is_asked(world):  # noqa: F811
    draft = _draft(world)
    api = _api(world["supply"])
    number = draft.number
    assert api.get("/api/v1/calc/deals/", {"number": number}).json()["results"] == []
    found = api.get("/api/v1/calc/deals/", {"number": number, "any": "1"}).json()["results"]
    assert [row["id"] for row in found] == [draft.pk]
