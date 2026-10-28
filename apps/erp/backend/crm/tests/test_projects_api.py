"""Проекты (D2-5): список и карточка «Все проекты» — шаг, статус для клиента, проблемы, действия по документам, доступ.

Читает сотрудник компании-владельца (любая роль: у ERP чтение открыто, `Permission` — это действия) и администратор;
покупатель и посторонний — 403 `PROJECT_STAFF_ONLY`. Доступные действия в карточке считает сервер: у менеджера и снабженца
их нет, у директора и бухгалтера — по статусу договора и акта. Ответы проверяются схемой OpenAPI.
"""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from integration.tests import world as w

from crm.constants import ActStatusCode as A
from crm.constants import ContractStatusCode as S
from crm.constants import DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import ActivityLog
from crm.services import projects
from crm.tests.projects_world import api, contract_in, pw  # noqa: F401

pytestmark = pytest.mark.django_db

LIST = "/api/v1/crm/projects/"


def _card(user, deal_id):
    return api(user).get(f"{LIST}{deal_id}/")


def test_list_shows_the_project_with_documents_and_client_status(pw):  # noqa: F811
    contract_in(pw, S.PENDING_CLIENT)
    response = api(pw.director).get(LIST)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 1
    row = body["results"][0]
    assert row["deal_id"] == pw.deal.id and row["title"] == "Поставка рельсов" and row["company_name"] == "ООО Клиент"
    assert row["step"] == "CONTRACT" and row["client_status"] == "contract_review"
    assert (
        row["documents"]["contract"]["status"] == "project" and row["documents"]["contract"]["sent_to_client"] is True
    )
    assert row["documents"]["quote"]["status"] == "accepted" and row["documents"]["invoice"] is None
    assert row["manager"]["name"] and row["problems"] == []


@pytest.mark.parametrize(
    ("status", "step", "client_status"),
    [
        (S.DRAFT, "CONTRACT", "contract_review"),
        (S.PENDING_CLIENT, "CONTRACT", "contract_review"),
        (S.PENDING_MANAGER, "CONTRACT", "contract_signing"),
        (S.ISSUED_EXTERNAL, "CONTRACT", "contract_signing"),
        (S.SIGNED, "PAYMENT", "fulfilling"),
    ],
)
def test_step_and_client_status_by_contract(pw, status, step, client_status):  # noqa: F811
    contract_in(pw, status)
    row = api(pw.manager).get(LIST).json()["results"][0]
    assert (row["step"], row["client_status"]) == (step, client_status)


def test_payment_step_waits_for_the_invoice_then_for_acceptance(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.ISSUED, total="5000000", contract=contract)
    assert api(pw.manager).get(LIST).json()["results"][0]["client_status"] == "awaiting_payment"
    w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    assert api(pw.manager).get(LIST).json()["results"][0]["client_status"] == "awaiting_acceptance"


def test_problems_are_derived_from_documents(pw):  # noqa: F811
    contract = contract_in(pw, S.REJECTED)
    assert api(pw.manager).get(LIST).json()["results"][0]["problems"] == ["contract_rejected"]
    contract.delete()
    c2 = contract_in(pw, S.SIGNED)
    invoice = w.add_invoice(
        pw.deal,
        InvoiceStatusCode.ISSUED,
        total="5",
        contract=c2,
        due=datetime.date.today() - datetime.timedelta(days=3),
    )
    w.add_act(pw.deal, A.DRAFT, contract=c2, invoice=invoice, rejection_reason="Опечатка")
    problems = api(pw.manager).get(LIST).json()["results"][0]["problems"]
    assert set(problems) == {"act_returned", "invoice_overdue"}
    assert api(pw.manager).get(LIST, {"problems": "true"}).json()["count"] == 1


def test_project_without_contract_is_a_problem(pw):  # noqa: F811
    assert api(pw.manager).get(LIST).json()["results"][0]["problems"] == ["no_contract"]


def test_filters_step_mine_q_and_deal_id(pw):  # noqa: F811
    contract_in(pw, S.PENDING_CLIENT)
    other = w.make_deal(pw.client, DealStageCode.CLOSED_WON, title="Другой проект")
    other_quote = w.add_quote(other, 1, QuoteStatusCode.APPROVED, "100")
    w.add_contract(other, other_quote, S.SIGNED)
    lost = w.make_deal(pw.client, DealStageCode.CLOSED_LOST, title="Потерянная")  # noqa: F841
    client = api(pw.manager)
    assert client.get(LIST).json()["count"] == 2, "проигранная заявка — не проект"
    assert client.get(LIST, {"step": "PAYMENT"}).json()["results"][0]["deal_id"] == other.id
    assert client.get(LIST, {"mine": "true"}).json()["results"][0]["deal_id"] == pw.deal.id
    assert client.get(LIST, {"q": "Другой"}).json()["count"] == 1
    assert client.get(LIST, {"q": "ООО Клиент"}).json()["count"] == 2
    assert client.get(LIST, {"deal_id": other.id}).json()["count"] == 1
    assert client.get(LIST, {"step": "nonsense"}).json()["count"] == 2, "неизвестный шаг игнорируется"
    page = client.get(LIST, {"limit": 1, "offset": 1}).json()
    assert page["count"] == 2 and len(page["results"]) == 1


def test_card_has_documents_history_and_actions_for_the_accountant(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_MANAGER)
    api(pw.accountant).post(f"/api/v1/crm/contracts/{contract.id}/mark-issued/", {"note": "Didox"}, format="json")
    response = _card(pw.accountant, pw.deal.id)
    assert response.status_code == 200, response.content
    card = response.json()
    assert card["contract"]["status"] == "issued_at_operator"
    assert card["contract"]["actions"] == ["reject", "attach_scan"]
    assert [h["code"] for h in card["contract"]["history"]] == ["contract.issued_external"]
    assert card["contract"]["history"][0]["actor_name"] and card["contract"]["history"][0]["document"] == "contract"
    assert card["quote"]["number"] == "" or card["quote"]["status"] == "accepted"
    assert card["can_create_contract"] is False and card["act"] is None and card["act_blocker"] == "no_invoice"
    assert card["journal"][0]["code"] == "contract.issued_external"


def test_card_actions_are_empty_for_read_only_roles(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_CLIENT)
    for user in (pw.manager, pw.supply):
        card = _card(user, pw.deal.id).json()
        assert card["contract"]["actions"] == [] and card["can_create_contract"] is False
        assert card["act_blocker"] == "forbidden"
    assert contract.id


def test_card_offers_to_create_the_contract_when_none_exists(pw):  # noqa: F811
    assert _card(pw.accountant, pw.deal.id).json()["can_create_contract"] is True
    assert _card(pw.manager, pw.deal.id).json()["can_create_contract"] is False
    assert _card(pw.accountant, pw.deal.id).json()["contract"] is None


def test_card_act_blocker_and_act_actions(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    assert _card(pw.accountant, pw.deal.id).json()["act_blocker"] == "no_invoice"
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.ISSUED, total="5", contract=contract)
    assert _card(pw.accountant, pw.deal.id).json()["act_blocker"] is None
    act = w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    card = _card(pw.accountant, pw.deal.id).json()
    assert card["act_blocker"] == "act_exists" and card["act"]["actions"] == ["attach_scan", "return"]
    assert card["invoices"][0]["status"] == "issued" and card["act"]["id"] == act.id


def test_card_has_the_fulfillment_read_only(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    w.add_fulfillment(pw.deal, "SHIPPED", expected_delivery_date=datetime.date(2026, 12, 1), carrier="Авиа")
    card = _card(pw.manager, pw.deal.id).json()
    assert card["fulfillment"]["status"] == "SHIPPED" and card["fulfillment"]["carrier"] == "Авиа"
    assert card["due_date"] == "2026-12-01"
    assert contract.id


def test_everyone_outside_the_staff_gets_403_and_not_found_hides_the_object(pw):  # noqa: F811
    contract_in(pw, S.PENDING_CLIENT)
    for user in (pw.outsider, pw.stranger):
        assert api(user).get(LIST).status_code == 403
        assert api(user).get(f"{LIST}{pw.deal.id}/").status_code == 403
    from rest_framework.test import APIClient

    assert APIClient().get(LIST).status_code == 401
    assert _card(pw.director, 10**8).status_code == 404
    draft = w.make_deal(pw.client, DealStageCode.RFQ_OPEN)  # заявка, а не проект
    assert _card(pw.director, draft.id).status_code == 404
    assert api(pw.director).post(LIST, {}, format="json").status_code in (403, 405)


def test_admin_reads_and_acts_everywhere(pw):  # noqa: F811
    contract = contract_in(pw, S.DRAFT)
    assert api(pw.admin).get(LIST).json()["count"] == 1
    assert _card(pw.admin, pw.deal.id).json()["contract"]["actions"] == ["send_to_client"]
    assert (
        api(pw.admin).post(f"/api/v1/crm/contracts/{contract.id}/send-to-client/", {}, format="json").status_code == 200
    )


def test_list_runs_in_a_bounded_number_of_queries(pw):  # noqa: F811
    """Список не ходит в базу на каждую сделку: число запросов не растёт с числом проектов."""

    def build(n):
        for i in range(n):
            deal = w.make_deal(pw.client, DealStageCode.CLOSED_WON, title=f"Проект {i}")
            quote = w.add_quote(deal, 1, QuoteStatusCode.APPROVED, "100")
            contract = w.add_contract(deal, quote, S.SIGNED)
            invoice = w.add_invoice(deal, InvoiceStatusCode.ISSUED, total="100", contract=contract)
            w.add_act(deal, A.ISSUED, contract=contract, invoice=invoice)

    client = api(pw.director)
    build(2)
    client.get(LIST)  # прогрев кэшей прав и словарей
    with CaptureQueriesContext(connection) as few:
        client.get(LIST)
    build(10)
    with CaptureQueriesContext(connection) as many:
        client.get(LIST)
    assert len(many) <= len(few) + 4, (len(few), len(many))


def test_project_journal_lists_only_document_events(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_CLIENT)
    ActivityLog.objects.create(action="Что-то другое", event_code="deal.stage_changed", deal=pw.deal)
    api(pw.accountant).post(f"/api/v1/crm/contracts/{contract.id}/client-agreed/", {}, format="json")
    codes = [row["code"] for row in _card(pw.director, pw.deal.id).json()["journal"]]
    assert codes == ["contract.client_agreed"]


def test_done_project_reports_the_done_step(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.PAID, total="5", paid="5", contract=contract)
    w.add_act(pw.deal, A.SIGNED, contract=contract, invoice=invoice)
    row = api(pw.manager).get(LIST, {"step": "DONE"}).json()["results"][0]
    assert row["step"] == "DONE" and row["client_status"] == "done"
    deal = projects.project_queryset().get(pk=pw.deal.pk)
    assert projects.project_is_done(deal)
