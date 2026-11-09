"""FX-6 (волна 19): у каждой компании с активными контактами есть активный администратор.

Пункты: (а) пути создания контакта (сотрудник, передача CRM, заявка партнёра, список контактов поставщика) сами
называют администратора; (б) отключённого коллегу можно пригласить снова; (в) единственный администратор не снимает с
себя `can_act`; (г) архивация администратора контактом из CRM не оставляет компанию без администратора; (д) миграция
`0022` чинит компании без администратора и не выбирает архивный контакт. Гонка — в `test_company_admin_race.py`.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.core import mail
from django.utils import timezone
from integration.tests.test_handoff import SERVICE_TOKEN, URL, handoff, payload  # noqa: F401
from parties.models import Company, CompanyType, Contact, PartnerApplication, active_contact_q
from portal.tests.conftest import LOCMEM_BACKEND
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def active_admins(company):
    return Contact.objects.filter(active_contact_q(), company=company, is_admin=True)


@pytest.fixture(autouse=True)
def locmem(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox = []
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})


# ── (а) пути создания контакта ───────────────────────────────────────────────────────────────────


def test_handoff_of_new_company_makes_primary_contact_admin():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    assert handoff(api, payload()).status_code == 201
    company = Company.objects.get(inn="123456789")
    admins = active_admins(company)
    assert admins.count() == 1 and admins.get().is_primary


def test_handoff_into_existing_company_does_not_make_new_contact_admin(client_company, client_contact):
    # компания найдена по ИНН: новый непроверенный контакт администратором не становится
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    client_company.inn = "123456789"
    client_company.save(update_fields=["inn"])
    assert handoff(api, payload()).status_code == 201
    newcomer = Contact.objects.get(company=client_company, email="ivan@client.uz")
    assert newcomer.is_admin is False
    assert list(active_admins(client_company)) == [client_contact]


def test_desk_create_contact_in_company_without_admin_makes_it_admin(client_company):
    from portal.desk.service import create_contact

    from accounts.models import CustomUser

    user = CustomUser.objects.create_user(email="staff@example.uz", username="staff", password="x")
    contact = create_contact(client_company, {"name": "Supplier Person", "email": "sp@example.uz"}, user)
    assert contact.is_admin is True
    second = create_contact(client_company, {"name": "Second Person", "email": "sp2@example.uz"}, user)
    assert second.is_admin is False
    assert active_admins(client_company).count() == 1


def test_applicant_contact_of_partner_application_is_admin(client_company):
    from portal.desk.service_partner_applications import _applicant_contact

    app = PartnerApplication(
        company_name="Partner",
        contact_name="Applicant",
        email="applicant@example.uz",
        phone="",
    )
    contact = _applicant_contact(app, client_company, None)
    assert contact.is_admin is True


def test_offline_client_creation_makes_first_contact_admin(db):
    from accounts.models import CompanyMember, CustomUser, WorkspaceRole
    from accounts.services.clients import create_offline_client

    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    seller_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]
    own = Company.objects.create(name="Own Co", inn="R200")
    own.types.add(seller_type)
    seller = CustomUser.objects.create_user(email="rs@example.uz", username="rs", password="x", is_active=True)
    CompanyMember.objects.create(
        user=seller,
        company=own,
        role=owner_role,
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    result, error = create_offline_client(
        seller=seller,
        company_name="Offline Buyer",
        contact_name="Buyer Person",
        email="buyer@example.uz",
    )
    assert error is None
    assert result["contact"].is_admin is True
    assert active_admins(result["company"]).count() == 1


# ── (б) отключённого коллегу можно пригласить снова ──────────────────────────────────────────────


def test_deactivated_colleague_can_be_invited_again(portal_client, client_company, client_contact):
    colleague = Contact.objects.create(
        company=client_company,
        name="Timur Colleague",
        email="timur@example.uz",
        phone="+998901112233",
    )
    assert portal_client.post(f"/api/portal/v1/team/{colleague.pk}/deactivate").status_code == 200
    response = portal_client.post(
        "/api/portal/v1/team/invite",
        {
            "name": "Timur Colleague",
            "email": "timur@example.uz",
            "phone": "+998901112233",
            "channels": ["email"],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    colleague.refresh_from_db()
    assert colleague.is_archived  # след остаётся, приглашённый — новая активная запись
    assert Contact.objects.filter(active_contact_q(), company=client_company, email="timur@example.uz").count() == 1


def test_active_duplicate_is_still_refused(portal_client, client_company, client_contact):
    response = portal_client.post(
        "/api/portal/v1/team/invite",
        {"name": "Dup", "email": client_contact.email, "channels": ["email"]},
        format="json",
    )
    assert response.status_code == 422 and response.json() == {"detail": "TEAM_MEMBER_EXISTS"}


# ── (в) единственный администратор и can_act ─────────────────────────────────────────────────────


def test_sole_admin_cannot_drop_own_can_act(portal_client, client_company, client_contact):
    response = portal_client.patch(f"/api/portal/v1/team/{client_contact.pk}", {"can_act": False}, format="json")
    assert response.status_code == 422, response.content
    assert response.json() == {"detail": "LAST_ADMIN_CANNOT_BE_REMOVED"}
    client_contact.refresh_from_db()
    assert client_contact.can_act is True


def test_admin_may_drop_can_act_when_another_admin_exists(portal_client, client_company, client_contact):
    other = Contact.objects.create(
        company=client_company,
        name="Second Admin",
        email="admin2@example.uz",
        is_admin=True,
        can_act=True,
    )
    response = portal_client.patch(f"/api/portal/v1/team/{other.pk}", {"can_act": False}, format="json")
    assert response.status_code == 200
    other.refresh_from_db()
    assert other.can_act is False


# ── (г) архивация администратора контактом из CRM ────────────────────────────────────────────────


def test_archiving_sole_admin_promotes_another_active_contact(client_company, client_contact):
    from integration.services.crm_projections import archive_contact

    colleague = Contact.objects.create(company=client_company, name="Colleague", email="c@example.uz")
    archive_contact(client_contact, timezone.now())
    admins = active_admins(client_company)
    assert list(admins) == [colleague]
    client_contact.refresh_from_db()
    assert client_contact.is_admin is False


# ── (д) миграция 0022 ────────────────────────────────────────────────────────────────────────────


def _migration():
    return importlib.import_module("parties.migrations.0022_company_admin_backfill")


def test_migration_gives_adminless_company_an_active_admin(client_company):
    archived = Contact.objects.create(
        company=client_company,
        name="Archived First",
        email="a@example.uz",
        archived_at=timezone.now(),
    )
    active = Contact.objects.create(company=client_company, name="Active Later", email="b@example.uz")
    _migration().backfill_admins(django_apps, None)
    archived.refresh_from_db()
    active.refresh_from_db()
    assert archived.is_admin is False, "архивный контакт администратором не назначается"
    assert active.is_admin is True


def test_migration_prefers_primary_and_leaves_companies_with_admin_alone(client_company, client_contact):
    other = Company.objects.create(name="Second Co", inn="111222333")
    Contact.objects.create(company=other, name="Not Primary", email="np@example.uz")
    primary = Contact.objects.create(company=other, name="Primary", email="p@example.uz", is_primary=True)
    _migration().backfill_admins(django_apps, None)
    primary.refresh_from_db()
    assert primary.is_admin is True
    assert active_admins(other).count() == 1
    assert list(active_admins(client_company)) == [client_contact]


def test_migration_replaces_archived_admin(client_company):
    gone = Contact.objects.create(
        company=client_company,
        name="Gone Admin",
        email="g@example.uz",
        is_admin=True,
        archived_at=timezone.now(),
    )
    alive = Contact.objects.create(company=client_company, name="Alive", email="al@example.uz")
    _migration().backfill_admins(django_apps, None)
    alive.refresh_from_db()
    assert alive.is_admin is True
    gone.refresh_from_db()
    assert gone.is_admin is False
