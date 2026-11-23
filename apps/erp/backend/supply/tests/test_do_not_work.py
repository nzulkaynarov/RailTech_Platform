"""Х-8: отметка «Не работать» у контрагента — факты, отказы сервера, журнал, шина.

`POST|DELETE /api/v1/parties/organizations/{id}/do-not-work/`; отказ создания КП, договора, заказа поставщику, заявки и
приглашения в кабинет у отмеченной компании (409 `COMPANY_DO_NOT_WORK` с причиной и тем, кто отметил); документы в работе
не отменяются; кабинет остаётся доступным на чтение. Мир — `inventory.tests.support` (поставщик, клиент, сотрудник снабжения).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from integration.mcp.context import AgentContext
from integration.mcp.tools import ToolExecutionError, create_request_tool
from integration.models import CrmClientMapping
from integration.tests.bus_support import published
from inventory.models import Reservation, ReservationStatus
from inventory.tests.support import api, make_deal
from inventory.tests.test_stock import _adjust
from parties import do_not_work
from parties.do_not_work import CompanyDoNotWork
from parties.models import CompanyRelationship, Contact
from portal.desk import service_counterparty as counterparty
from portal.desk.service import AccessError
from portal.desk.service import invite as desk_invite
from portal.services.access import company_has_cabinet_access
from portal.services.invitation import invite_contact, invite_team_member
from portal.services.requests import create_client_request
from supply.models import OrderStatus, SupplierOrder
from supply.services.provision import provision_accepted_quote
from supply.tests.test_provision import _accept, _offer, _sent_quote

from crm.models import ActivityLog, Contract, Deal, DealStage, Quote

pytestmark = pytest.mark.django_db

URL = "/api/v1/parties/organizations/"
STOCK = "/api/v1/stock/"


def _mark(world, company, reason="Дважды не оплатил отгрузку", **extra):
    return api(world["supply"]).post(f"{URL}{company.pk}/do-not-work/", {"reason": reason, **extra}, format="json")


def _order(world, **extra):
    body = {"supplier_id": world["vendor"].pk, "lines": [{"product_id": world["rail"].pk, "quantity": 5}], **extra}
    return api(world["supply"]).post(f"{STOCK}orders/", body, format="json")


def _journal(company):
    return list(
        ActivityLog.objects.filter(entity_type="company", entity_id=company.pk, event_code="admin.company.updated")
        .order_by("id")
        .values_list("action", flat=True)
    )


def test_mark_and_remove_are_facts_with_journal(world):
    vendor = world["vendor"]
    response = _mark(world, vendor, "  Дважды  не оплатил   отгрузку ")
    assert response.status_code == 200, response.content
    facts = response.json()["do_not_work"]
    assert facts["reason"] == "Дважды не оплатил отгрузку"
    assert facts["set_by"] and facts["set_at"] and facts["until"] is None
    vendor.refresh_from_db()
    assert vendor.do_not_work_by_id == world["supply"].pk and vendor.do_not_work_at is not None
    assert _journal(vendor) == ["Контрагенту поставлено «Не работать»"]
    # карточка и повторное чтение отдают те же факты
    assert api(world["supply"]).get(f"{URL}{vendor.pk}/").json()["do_not_work"] == facts

    removed = api(world["supply"]).delete(f"{URL}{vendor.pk}/do-not-work/")
    assert removed.status_code == 200 and removed.json()["do_not_work"] is None
    vendor.refresh_from_db()
    assert vendor.do_not_work_at is None and vendor.do_not_work_reason == "" and vendor.do_not_work_by_id is None
    # повторное снятие безопасно и в журнал не пишет
    assert api(world["supply"]).delete(f"{URL}{vendor.pk}/do-not-work/").status_code == 200
    assert _journal(vendor) == ["Контрагенту поставлено «Не работать»", "С контрагента снято «Не работать»"]


def test_reason_is_required_until_is_not_in_the_past_and_a_permission_is_needed(world):
    vendor = world["vendor"]
    empty = _mark(world, vendor, "   ")
    assert (empty.status_code, empty.json()["detail"]) == (400, "REASON_REQUIRED")
    past = _mark(world, vendor, until=(timezone.localdate() - timedelta(days=1)).isoformat())
    assert (past.status_code, past.json()["detail"]) == (400, "UNTIL_PAST")
    # право — раздел правки контрагента (`deal.manage` / `supply.manage`), а не роль: у читателя нет ни одного
    denied = api(world["reader"]).post(f"{URL}{vendor.pk}/do-not-work/", {"reason": "x"}, format="json")
    assert denied.status_code == 403
    assert api(world["reader"]).delete(f"{URL}{vendor.pk}/do-not-work/").status_code == 403
    vendor.refresh_from_db()
    assert vendor.do_not_work_at is None and _journal(vendor) == []


def test_supplier_order_is_refused_with_the_reason_and_who_set_it(world):
    assert _order(world).status_code == 201
    _mark(world, world["vendor"])
    refused = _order(world)
    assert refused.status_code == 409, refused.content
    body = refused.json()
    assert body["detail"] == "COMPANY_DO_NOT_WORK" and body["company_id"] == world["vendor"].pk
    assert body["do_not_work"]["reason"] == "Дважды не оплатил отгрузку" and body["do_not_work"]["set_by"]
    assert SupplierOrder.objects.count() == 1, "заказ в работе не отменён, новый не создан"
    assert SupplierOrder.objects.first().status == "draft"
    # снятие возвращает возможность
    api(world["supply"]).delete(f"{URL}{world['vendor'].pk}/do-not-work/")
    assert _order(world).status_code == 201


def test_new_deal_quote_and_contract_are_refused_but_documents_in_work_stay(world):
    client = world["client"]
    deal, quote, _items = make_deal(world, [(world["rail"], 2)])
    counterparty.set_do_not_work(client, {"reason": "Недобросовестный плательщик"}, actor=world["supply"])
    # то, что уже идёт, живёт: сохранение сделки и КП не отказывает
    deal.refresh_from_db()
    deal.title = "Стрелочные переводы, правка"
    deal.save()
    quote.save()
    for create in (
        lambda: Deal.objects.create(title="Новая", company=client, stage=DealStage.objects.first()),
        lambda: Quote.objects.create(deal=deal, version=2, seller_company=world["seller"]),
        lambda: Contract.objects.create(deal=deal, quote=quote, number="CT-X-1"),
    ):
        with pytest.raises(CompanyDoNotWork) as caught:
            create()
        assert caught.value.status_code == 409
        assert caught.value.detail["detail"] == "COMPANY_DO_NOT_WORK"
        assert caught.value.detail["do_not_work"]["reason"] == "Недобросовестный плательщик"
    assert Deal.objects.filter(company=client).count() == 1 and deal.quotes.count() == 1


def test_until_date_ends_the_mark_by_itself(world):
    client = world["client"]
    today = timezone.localdate()
    counterparty.set_do_not_work(client, {"reason": "Пауза до конца недели", "until": today}, actor=world["supply"])
    client = do_not_work.fresh(client)
    assert do_not_work.is_marked(client), "в последний день срока отметка ещё действует"
    client.do_not_work_until = today - timedelta(days=1)
    client.save()
    assert not do_not_work.is_marked(client)
    assert do_not_work.facts(client) is None
    Deal.objects.create(title="После срока", company=client, stage=DealStage.objects.first())


def test_invitations_are_refused_and_the_cabinet_stays_readable(world):
    client = world["client"]
    contact = Contact.objects.create(company=client, name="Нилуфар", email="nilufar@client.example", can_act=True)
    CrmClientMapping.objects.create(crm_client_id=77, company=client)
    open_before = company_has_cabinet_access(client.pk)
    counterparty.set_do_not_work(client, {"reason": "Спор по оплате"}, actor=world["supply"])
    outcome = invite_contact(contact, channel="email")
    assert outcome.error == "COMPANY_DO_NOT_WORK" and outcome.sent_via == ()
    # кабинет не закрывается: доступ на чтение остаётся тем же, новых заявок нет
    assert company_has_cabinet_access(client.pk) is open_before
    with pytest.raises(CompanyDoNotWork):
        create_client_request(client, contact, summary="Рельсы", lines=[{"text": "Рельс Р65"}], attachments=[])
    assert not Deal.objects.filter(company=client, notes__contains="Cabinet").exists()
    counterparty.clear_do_not_work(client, actor=world["supply"])
    assert invite_contact(contact, channel="email").error != "COMPANY_DO_NOT_WORK"


def test_the_mark_travels_in_the_company_snapshot(world):
    vendor = world["vendor"]
    CrmClientMapping.objects.create(crm_client_id=55, company=vendor)
    _mark(world, vendor, "Отказались от договора")
    [snapshot] = published("company.updated")[-1:]
    sent = snapshot["data"]["company"]["do_not_work"]
    assert sent["reason"] == "Отказались от договора" and sent["set_by"] and sent["set_at"] and sent["until"] is None
    api(world["supply"]).delete(f"{URL}{vendor.pk}/do-not-work/")
    [cleared] = published("company.updated")[-1:]
    assert cleared["data"]["company"]["do_not_work"] is None
    assert cleared["data"]["company"]["updated_at"] > snapshot["data"]["company"]["updated_at"]


def test_accepting_a_quote_with_a_marked_supplier_keeps_the_reservation_and_the_other_drafts(world):
    """Принятие КП не теряет резерв и черновики других поставщиков, если один из поставщиков отмечен (Х-8)."""
    _adjust(world, world["rail"], 15)
    _offer(world, world["rail"], supplier="vendor")
    _offer(world, world["bolt"], supplier="silent")
    deal, quote, (rail, bolt) = _sent_quote(world, [(world["rail"], 40), (world["bolt"], 5)])
    _mark(world, world["vendor"])

    summary = provision_accepted_quote(quote)

    assert Reservation.objects.get(quote_item=rail, status=ReservationStatus.ACTIVE).quantity == 15
    (order,) = SupplierOrder.objects.all()
    assert order.supplier == world["silent"] and order.status == OrderStatus.DRAFT
    assert summary["without_supplier"] == [rail.pk] and summary["orders"] == [order.number]
    log = ActivityLog.objects.get(deal=deal, event_code="supply.shortage_without_supplier")
    assert "С поставщиком ООО Вымышленный Поставщик не работаем" in log.detail

    # принятие через весь поток тоже доходит до конца
    deal2, quote2, _ = _sent_quote(world, [(world["rail"], 3)])
    _accept(quote2)
    deal2.refresh_from_db()
    assert deal2.stage.code == "CONTRACT_SIGNED"


def test_inviting_a_contact_from_the_counterparty_card_is_refused(world):
    client = world["client"]
    contact = Contact.objects.create(company=client, name="Нилуфар", email="nilufar@client.example", can_act=True)
    counterparty.set_do_not_work(client, {"reason": "Спор по оплате"}, actor=world["supply"])
    with pytest.raises(AccessError) as caught:
        desk_invite(client, contact.pk, world["supply"])
    assert caught.value.code == "COMPANY_DO_NOT_WORK" and caught.value.status == 409
    assert not CompanyRelationship.objects.filter(company=client).exists(), "отношение не заведено"
    assert not mail.outbox, "письмо не ушло"


def test_inviting_a_colleague_from_the_cabinet_is_refused(world):
    client = world["client"]
    contact = Contact.objects.create(company=client, name="Нилуфар", email="nilufar@client.example", can_act=True)
    counterparty.set_do_not_work(client, {"reason": "Спор по оплате"}, actor=world["supply"])
    data = {"channels": ["email"], "email": "colleague@client.example", "can_act": False}
    with pytest.raises(CompanyDoNotWork):
        invite_team_member(client, contact, data)
    assert not Contact.objects.filter(email="colleague@client.example").exists()
    assert not mail.outbox


def test_the_assistant_tool_does_not_create_a_request_for_a_marked_company(world):
    client = world["client"]
    context = AgentContext(
        crm_client_id=1, erp_company_id=client.pk, mode="customer", language="ru", iat=0, exp=0, jti="x"
    )
    arguments = {"summary": "Нужен рельс", "lines": [{"text": "Рельс Р65"}]}
    counterparty.set_do_not_work(client, {"reason": "Спор по оплате"}, actor=world["supply"])
    with pytest.raises(ToolExecutionError, match="company_do_not_work"):
        create_request_tool(context, arguments)
    assert not Deal.objects.filter(company=client).exists()
