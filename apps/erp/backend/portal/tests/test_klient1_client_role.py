"""КЛИЕНТ-1: любая заявка делает компанию клиентом через одну функцию ролей; «Может подтверждать» клиентского контакта.

Обход 2026-11-28: компания, заведённая мастером заявки из лида «организацией», оставалась без роли клиента — в Кабинет не
войти; единственный контакт был «только просмотр», принять КП нельзя.
"""

import pytest
from integration.models import CrmClientMapping
from integration.services.request_deal import create_request_deal
from integration.tests.test_handoff import handoff, payload
from parties.models import Company, CompanyType, Contact
from rest_framework.test import APIClient

from catalog.tests.desk_world import build_world
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

PEOPLE = "/api/v1/parties/people/"
SERVICE_TOKEN = "test-crm-to-erp-token"


@pytest.fixture(autouse=True)
def integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.CABINET_URL = "http://cabinet.localhost"
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})


@pytest.fixture
def api():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def _organization(name="ООО Оболочка"):
    company = Company.objects.create(name=name, inn="777000111")
    company.types.add(CompanyType.objects.get_or_create(code="ORGANIZATION", defaults={"name": "Организация"})[0])
    return company


def test_request_creation_makes_an_organization_a_client_once_with_journal():
    company = _organization()
    create_request_deal(company=company, summary="Нужны насосы")
    create_request_deal(company=company, summary="И ещё клапаны")

    codes = set(company.types.values_list("code", flat=True))
    assert codes == {"ORGANIZATION", "CLIENT"}, "тип добавляется к имеющемуся, организация остаётся"
    assert (
        ActivityLog.objects.filter(
            entity_type="company", entity_id=company.pk, event_code="admin.company.client_role_granted"
        ).count()
        == 1
    )


def test_handoff_to_a_blank_shell_is_not_found_by_inn_and_client_can_act(api):
    shell = _organization()
    response = handoff(api, payload(crm_client_id=4001, inn="777000111"))

    assert response.status_code == 201, response.content
    assert response.json()["invite"]["error"] != "COMPANY_LINKED_BY_INN"
    assert response.json()["erp_company_id"] == shell.pk
    assert shell.types.filter(code="CLIENT").exists()
    contact = Contact.objects.get(company=shell)
    assert contact.can_act is True, "первый контакт нового клиента из лида может подтверждать"
    assert CrmClientMapping.objects.get(company=shell).verified_at is not None


def test_handoff_to_a_company_with_contacts_stays_held_for_checking(api):
    existing = Company.objects.create(name="ООО Старая", inn="888000222")
    Contact.objects.create(company=existing, name="Старый", email="old@client.uz", can_act=True)
    response = handoff(api, payload(crm_client_id=4002, inn="888000222"))

    assert response.json()["invite"]["error"] == "COMPANY_LINKED_BY_INN"
    assert Contact.objects.get(company=existing, email="ivan@client.uz").can_act is False


def _age(company, days=400):
    from datetime import timedelta

    from django.utils import timezone

    Company.objects.filter(pk=company.pk).update(created_at=timezone.now() - timedelta(days=days))


def _bank_account(company):
    from parties.models import CompanyBankAccount

    from core.models import Currency

    currency, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    return CompanyBankAccount.objects.create(
        company=company, currency=currency, holder_name="ООО", account="20208000100000000001"
    )


def _supplier_order(company):
    from supply.models import SupplierOrder

    return SupplierOrder.objects.create(supplier=company, number="PO-HOSTILE-1", number_year=2026, number_seq=1)


def _price_request(company):
    from supply.models import PriceRequest

    return PriceRequest.objects.create(supplier=company)


def _portal_message(company):
    from portal.models import PortalMessage

    return PortalMessage.objects.create(company=company, direction="client", text="Здравствуйте")


@pytest.mark.parametrize(
    "make_data",
    [None, _bank_account, _supplier_order, _price_request, _portal_message],
    ids=["old_empty", "bank_account", "supplier_order", "price_request", "cabinet_message"],
)
def test_handoff_to_an_old_company_stays_held_even_without_contacts(api, make_data):
    """Враждебный вход: давняя компания без контактов (с данными или без) — не «завели только что»; ИНН из лида её не открывает."""
    old = Company.objects.create(name="ООО Давняя", inn="999000333")
    if make_data is not None:
        make_data(old)
    _age(old)
    response = handoff(api, payload(crm_client_id=4003, inn="999000333"))

    assert response.json()["invite"]["error"] == "COMPANY_LINKED_BY_INN"
    assert response.json()["invite"]["sent_via"] == []
    contact = Contact.objects.filter(company=old, email="ivan@client.uz").first()
    assert contact is None or contact.can_act is False


def test_handoff_to_a_fresh_company_with_data_stays_held(api):
    """Свежая, но уже с банковским счётом — не пустая: данные есть, значит, проверять есть что."""
    fresh = Company.objects.create(name="ООО Свежая", inn="999000444")
    _bank_account(fresh)
    response = handoff(api, payload(crm_client_id=4004, inn="999000444"))
    assert response.json()["invite"]["error"] == "COMPANY_LINKED_BY_INN"


@pytest.fixture
def world(settings):
    world = build_world()
    Contact.objects.create(company=world["supplier"], name="Рустам", phone="+998", is_primary=True, can_act=False)
    return world


def test_cabinet_right_switch_is_permissioned_and_audited(world):
    contact = Contact.objects.get(company=world["supplier"])
    url = f"{PEOPLE}{contact.pk}/cabinet-right/"

    assert world["clients"]["manager"].patch(url, {"can_act": True}, format="json").status_code == 403
    contact.refresh_from_db()
    assert contact.can_act is False

    ok = world["clients"]["supply"].patch(url, {"can_act": True}, format="json")
    assert ok.status_code == 200 and ok.json() == {"id": contact.pk, "can_act": True}
    contact.refresh_from_db()
    assert contact.can_act is True
    assert ActivityLog.objects.filter(event_code="admin.company.contact_right_changed").count() == 1

    world["clients"]["supply"].patch(url, {"can_act": True}, format="json")
    assert (
        ActivityLog.objects.filter(event_code="admin.company.contact_right_changed").count() == 1
    ), "повтор без записи"
    bad = world["clients"]["supply"].patch(url, {"can_act": "maybe"}, format="json")
    assert bad.status_code == 400


def test_card_people_carry_can_act(world):
    card = world["clients"]["supply"].get(f"/api/v1/parties/organizations/{world['supplier'].pk}/").json()
    assert card["people"][0]["can_act"] is False
