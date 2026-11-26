"""КОНТР-1б: роли контрагента — правда на экране и исправление ошибки на месте.

Случай: письмо от будущего партнёра завело компанию КЛИЕНТОМ (тип, связь с клиентом CRM, заявка, вход в кабинет), а заявка
в партнёры висит на рассмотрении. Роли — список с состояниями (`portal.desk.company_roles`); «Не клиент» снимает ошибочную
роль; одобрение заявки переиспользует компанию и контакт. Названия выдуманы.
"""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from integration.models import CrmClientMapping
from parties.models import (
    Company,
    CompanyRelationship,
    CompanyType,
    Contact,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    PartnerKind,
    RelationshipRole,
    RelationshipStatus,
)
from portal.desk import company_roles
from portal.tests.conftest import PortalAPIClient, make_portal_session
from portal.tests.partner_contract_helpers import prepare, with_scan
from sales.models import Deal, DealStage

from catalog.tests.desk_world import build_world
from crm.constants import DealStageCode
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

ORG = "/api/v1/parties/organizations/"
PEOPLE = "/api/v1/parties/people/"
APPS = "/api/v1/catalog/partner-applications/"


def _stage(code):
    return DealStage.objects.get_or_create(code=code, defaults={"name": code})[0]


def _portal(contact):
    from django.conf import settings

    session = make_portal_session(contact, contact.company, "magic_link")
    client = PortalAPIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


@pytest.fixture
def world():
    world = build_world()
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]
    company = Company.objects.create(name="ООО Демо-Письмо", inn="300000555")
    company.types.add(client_type)
    contact = Contact.objects.create(
        company=company,
        name="Демо Контактов",
        email="demo@letter-sender.example",
        phone="+998900000001",
        can_act=True,
        is_admin=True,
        is_primary=True,
        last_login_at=timezone.now() - timedelta(hours=3),
    )
    CrmClientMapping.objects.create(crm_client_id=900, company=company)
    deal = Deal.objects.create(
        company=company, contact=contact, title="Заявка по письму", stage=_stage(DealStageCode.DRAFT)
    )
    app = prepare(
        PartnerApplication.objects.create(
            source=PartnerApplicationSource.LETTER,
            company=company,
            company_name=company.name,
            inn=company.inn,
            contact_name=contact.name,
            email=contact.email,
            phone=contact.phone,
            kind=PartnerKind.SUPPLIER,
            categories_description="Крепёж",
            status=PartnerApplicationStatus.SUBMITTED,
        )
    )
    world.update(company=company, contact=contact, deal=deal, app=app)
    return world


def card(world, who="supply"):
    return world["clients"][who].get(f"{ORG}{world['company'].pk}/")


def states(response):
    return [(s["role"], s["state"], s["kind"]) for s in response.json()["role_states"]]


def test_roles_are_a_list_with_a_state_per_role(world):
    body = card(world).json()
    assert [(s["role"], s["state"]) for s in body["role_states"]] == [
        ("client", "active"),
        ("partner", "application"),
    ]
    assert body["role_states"][1]["kind"] == "supplier"
    # правда о кабинете: вошёл как клиент, виден раздел клиента, последний вход есть
    assert body["cabinet"]["opened"] is True and body["cabinet"]["sees"] == "client"
    assert body["cabinet"]["roles"] == ["client"] and body["cabinet"]["last_login_at"] is not None


def test_partner_states_follow_the_relationship(world):
    company = world["company"]
    rel = CompanyRelationship.objects.create(
        company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE, kind="manufacturer"
    )
    world["app"].status = PartnerApplicationStatus.APPROVED
    world["app"].save()
    assert states(card(world))[1] == ("partner", "active", "manufacturer")
    rel.status = RelationshipStatus.SUSPENDED
    rel.save()
    assert states(card(world))[1][1] == "suspended"
    rel.status = RelationshipStatus.INVITED
    rel.save()
    assert states(card(world))[1][1] == "invited"


def test_not_client_dry_run_changes_nothing_and_names_no_one(world):
    plan = world["clients"]["supply"].get(f"{ORG}{world['company'].pk}/not-client/")
    assert plan.status_code == 200, plan.content
    body = plan.json()
    assert body["requests_to_close"] == [world["deal"].number] and body["has_history"] is False
    assert body["contacts"] == 1 and body["contacts_with_cabinet"] == 1
    world["deal"].refresh_from_db()
    assert world["deal"].close_reason_id is None and world["company"].types.filter(code="CLIENT").exists()
    # то же из оболочки: ничего не меняется, в выводе нет имён, почты, телефона
    shell = company_roles.remove_client_role(world["company"], dry_run=True)
    text = json.dumps(shell, ensure_ascii=False, default=str)
    for secret in ("Демо Контактов", "demo@letter-sender.example", "+998900000001", "ООО Демо-Письмо"):
        assert secret not in text
    assert shell["dry_run"] is True and world["company"].types.filter(code="CLIENT").exists()


def test_not_client_removes_the_mistaken_role_end_to_end(world):
    company, contact, deal = world["company"], world["contact"], world["deal"]
    portal = _portal(contact)
    assert portal.get("/api/portal/v1/me").json()["roles"] == ["client"]

    response = world["clients"]["supply"].post(f"{ORG}{company.pk}/not-client/")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["result"]["requests_closed"] == [deal.number]
    # компания больше не клиент: роли — только партнёр, заявка на подключение рассматривается
    assert [(s["role"], s["state"]) for s in body["card"]["role_states"]] == [("partner", "application")]
    assert body["card"]["roles"]["client"] is False and body["card"]["roles"]["partner"] is True
    # заявка закрыта «по ошибке»: запись и журнал на месте, из списков она скрыта
    deal.refresh_from_db()
    assert deal.close_reason.code == "ERROR" and deal.hidden_in_lists is True and deal.stage.code == "CLOSED_LOST"
    assert ActivityLog.objects.filter(deal=deal, event_code="calc.closed").exists()
    # кто и когда
    company.refresh_from_db()
    assert company.client_role_removed_at is not None and company.client_role_removed_by is not None
    assert ActivityLog.objects.filter(
        entity_type="company", entity_id=company.pk, event_code="admin.company.client_role_removed"
    ).exists()
    # контакт остался, связь с клиентом CRM осталась связью, но клиентом не делает
    assert Contact.objects.filter(pk=contact.pk).exists() and CrmClientMapping.objects.filter(company=company).exists()
    assert not company.types.filter(code="CLIENT").exists()
    # кабинет следует оставшимся ролям: тот же человек видит заявку, а не пустой клиентский кабинет
    me = portal.get("/api/portal/v1/me")
    assert me.status_code == 200 and me.json()["roles"] == ["partner"]
    application = portal.get("/api/portal/v1/company/partner-application").json()
    assert application["has_application"] is True and application["application"]["status"] == "submitted"
    # «Люди»: человек идёт по ролям компании — только «партнёры»
    clients = world["clients"]["supply"].get(PEOPLE, {"kind": "client"}).json()["results"]
    partners = world["clients"]["supply"].get(PEOPLE, {"kind": "partner"}).json()["results"]
    assert contact.pk not in [p["id"] for p in clients]
    assert [p["roles"] for p in partners if p["id"] == contact.pk] == [["partner"]]
    # повтор безопасен
    stamp = company.client_role_removed_at
    entries = ActivityLog.objects.filter(entity_type="company", entity_id=company.pk).count()
    again = world["clients"]["supply"].post(f"{ORG}{company.pk}/not-client/")
    assert again.status_code == 200 and again.json()["result"]["requests_closed"] == []
    # повтор не двигает дату и не пишет второй записи в журнал
    company.refresh_from_db()
    assert company.client_role_removed_at == stamp
    assert ActivityLog.objects.filter(entity_type="company", entity_id=company.pk).count() == entries


def test_real_history_warns_but_does_not_block(world):
    from portal.tests.contract_world import make_quote

    from master_data.models import Currency

    deal = world["deal"]
    sent = Deal.objects.create(
        company=world["company"], title="Настоящая заявка", stage=_stage(DealStageCode.QUOTE_SENT)
    )
    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "iso_numeric": "860"})[0]
    make_quote(sent, 1, "SENT", uzs=uzs, items=False)
    plan = world["clients"]["supply"].get(f"{ORG}{world['company'].pk}/not-client/").json()
    assert plan["has_history"] is True and plan["history"]["quotes_sent"] == 1
    assert plan["requests_kept"] == [sent.number] and plan["requests_to_close"] == [deal.number]
    response = world["clients"]["supply"].post(f"{ORG}{world['company'].pk}/not-client/")
    assert response.status_code == 200
    sent.refresh_from_db()
    assert sent.close_reason_id is None and sent.stage.code == "QUOTE_SENT"
    # роль снята, хотя история есть: решает сотрудник; новая заявка сделала бы компанию клиентом снова
    assert [(s["role"]) for s in response.json()["card"]["role_states"]] == ["partner"]
    Deal.objects.create(company=world["company"], title="Новая настоящая", stage=_stage(DealStageCode.DRAFT))
    assert states(card(world))[0][:2] == ("client", "active")


def test_company_isolation_and_rights(world):
    stranger = Company.objects.create(name="ООО Посторонняя", inn="300000556")
    other = Company.objects.create(name="ООО Другой Клиент", inn="300000557")
    other.types.add(CompanyType.objects.get(code="CLIENT"))
    supply = world["clients"]["supply"]
    # компания вне контрагентов — 404, как и у остальных действий карточки
    assert supply.post(f"{ORG}{stranger.pk}/not-client/").status_code == 404
    assert supply.get(f"{ORG}{stranger.pk}/not-client/").status_code == 404
    # без права вести заявки и поставки — 403, и ничего не меняется
    assert world["clients"]["viewer"].post(f"{ORG}{world['company'].pk}/not-client/").status_code == 403
    assert world["company"].types.filter(code="CLIENT").exists()
    # действие над одной компанией не трогает другую
    supply.post(f"{ORG}{world['company'].pk}/not-client/")
    assert other.types.filter(code="CLIENT").exists()
    other.refresh_from_db()
    assert other.client_role_removed_at is None


def test_both_roles_show_under_both_tabs(world):
    CompanyRelationship.objects.create(
        company=world["company"], role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
    )
    world["app"].status = PartnerApplicationStatus.APPROVED
    world["app"].save()
    supply = world["clients"]["supply"]
    ids = {tab: [p["id"] for p in supply.get(PEOPLE, {"kind": tab}).json()["results"]] for tab in ("client", "partner")}
    assert world["contact"].pk in ids["client"] and world["contact"].pk in ids["partner"]
    everyone = supply.get(PEOPLE).json()["results"]
    assert [p["roles"] for p in everyone if p["id"] == world["contact"].pk] == [["client", "partner"]]
    assert ids["client"].count(world["contact"].pk) == 1


def test_approval_reuses_company_and_contact_and_opens_the_partner_section(world):
    company, contact, app = world["company"], world["contact"], world["app"]
    with_scan(app)
    app.status = PartnerApplicationStatus.CANDIDATE_AGREED
    app.candidate_agreed_at = timezone.now()
    app.save()
    contacts_before, companies_before = Contact.objects.count(), Company.objects.count()
    portal = _portal(contact)

    response = world["clients"]["supply"].post(
        f"{APPS}{app.pk}/approve/",
        {"contract_number": "PD-KONTR-1", "contract_date": "2026-11-26", "company_id": company.pk},
        format="json",
    )
    assert response.status_code == 200, response.content
    # ни второй компании, ни второго контакта
    assert Contact.objects.count() == contacts_before and Company.objects.count() == companies_before
    app.refresh_from_db()
    assert app.company_id == company.pk and app.applicant_contact_id == contact.pk
    rel = CompanyRelationship.objects.get(company=company, role=RelationshipRole.PARTNER)
    # человек уже входил в кабинет — партнёрский раздел открыт сразу, «первого входа» ждать не нужно
    assert rel.status == RelationshipStatus.ACTIVE and rel.activated_at is not None
    me = portal.get("/api/portal/v1/me").json()
    assert me["roles"] == ["client", "partner"] and "my_products" in me["modules"]
    assert [(s["role"], s["state"]) for s in card(world).json()["role_states"]] == [
        ("client", "active"),
        ("partner", "active"),
    ]


def test_approval_finds_the_same_person_by_phone(world):
    """Контакт по письму получил другую почту: тот же человек по телефону не заводится вторым."""
    company, contact, app = world["company"], world["contact"], world["app"]
    contact.email = "other@letter-sender.example"
    contact.save()
    with_scan(app)
    app.status = PartnerApplicationStatus.CANDIDATE_AGREED
    app.candidate_agreed_at = timezone.now()
    app.save()
    before = Contact.objects.filter(company=company).count()
    response = world["clients"]["supply"].post(
        f"{APPS}{app.pk}/approve/", {"contract_number": "PD-KONTR-2", "company_id": company.pk}, format="json"
    )
    assert response.status_code == 200, response.content
    assert Contact.objects.filter(company=company).count() == before
    app.refresh_from_db()
    assert app.applicant_contact_id == contact.pk


def test_contract_sent_to_an_existing_company_keeps_the_candidate_entry(world):
    """Компания уже была, отношения нет: отправка договора даёт вход кандидата (иначе без клиентской роли — тупик)."""
    company = world["company"]
    company_roles.remove_client_role(company, actor=world["users"]["director"])
    CompanyRelationship.objects.filter(company=company).delete()  # как до исправления: входа нет
    response = world["clients"]["director"].post(
        f"{APPS}{world['app'].pk}/send-contract/", {"company_id": company.pk}, format="json"
    )
    assert response.status_code == 200, response.content
    rel = CompanyRelationship.objects.get(company=company, role=RelationshipRole.PARTNER)
    assert rel.status == RelationshipStatus.INVITED and rel.modules == []


def test_organization_gets_the_client_role_in_one_action_and_the_cabinet_opens(world):
    """Компания, заведённая письмом или мастером «организацией», без роли: «+ Клиент» открывает ей кабинет клиента."""
    org = Company.objects.create(name="ООО Демо-Организация", inn="300000888")
    org.types.add(CompanyType.objects.get_or_create(code="ORGANIZATION", defaults={"name": "Организация"})[0])
    contact = Contact.objects.create(company=org, name="Демо Орг", email="org@demo-org.example", can_act=True)
    supply = world["clients"]["supply"]
    assert supply.get(f"{ORG}{org.pk}/").json()["role_states"] == []
    assert _portal(contact).get("/api/portal/v1/me").status_code == 401  # кабинет закрыт

    response = supply.post(f"{ORG}{org.pk}/roles/", {"role": "client", "on": True}, format="json")
    assert response.status_code == 200, response.content
    assert [s["role"] for s in response.json()["role_states"]] == ["client"]
    assert _portal(contact).get("/api/portal/v1/me").json()["roles"] == ["client"]
    # снять так нельзя — для этого «Не клиент»
    refused = supply.post(f"{ORG}{org.pk}/roles/", {"role": "client", "on": False}, format="json")
    assert refused.status_code == 400
