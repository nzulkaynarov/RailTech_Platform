"""PART-CRM: приглашённый партнёр становится клиентом CRM (`partner.client_requested` → `crm.partner.client_resolved`).

* приглашение публикует запрос в той же транзакции; откат приглашения — нет события; сопоставленной компании запрос не нужен;
* ответ `linked` ставит сопоставление, тип CLIENT, сопоставляет контакты, публикует отложенные заявки партнёра — один раз;
* ответ `conflict` ничего не перепривязывает, запоминает состояние и уведомляет ответственного;
* повтор ответа ничего не задваивает; `/me` партнёра после сопоставления — роли client и partner;
* состояние для блока «Доступ в кабинет» (`crm_client`).
Мир — `catalog.tests.desk_world`, сессия портала — `portal.tests.conftest`.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.db import transaction
from integration.models import CrmClientMapping, CrmContactMapping, CrmUserMapping, DeferredRequestEvent, PartnerCrmLink
from integration.services import partner_client
from integration.tests import bus_support
from parties.models import Company, CompanyRelationship, CompanyType, Contact
from portal.tests.conftest import LOCMEM_BACKEND

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

PORTAL = "/api/portal/v1"


@pytest.fixture(autouse=True)
def _env(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()
    bus_support.reset()


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def supplier(world):
    company = world["supplier"]
    company.inn = "301234567"
    company.legal_address = "Ташкент, ул. Образцовая, 1"
    company.website = "https://supplier-north.example.uz"
    company.save()
    return company


@pytest.fixture
def contact(supplier):
    return Contact.objects.create(
        company=supplier,
        name="Dilshod Supplier",
        email="dilshod@supplier-north.example.uz",
        phone="+998901112233",
        language="uz",
        can_act=True,
    )


def invite(world, contact, who="supply"):
    return world["clients"][who].post(
        f"/api/v1/catalog/supplier-access/{contact.company_id}/invite/", {"contact_id": contact.pk}, format="json"
    )


def resolved(company, contact=None, *, status="linked", crm_client_id=77, **extra):
    data = {"erp_company_id": company.pk, "status": status, "crm_client_id": crm_client_id, "actor": {"type": "system"}}
    if contact is not None and status == "linked":
        data["contacts"] = [{"erp_contact_id": contact.pk, "crm_contact_id": 901}]
    data.update(extra)
    return data


# ── Запрос ────────────────────────────────────────────────────────────────────────────────────────────────────────────


class TestRequest:
    def test_invite_publishes_the_request_with_company_contacts_and_inviter(self, world, supplier, contact):
        staff = world["users"]["supply"] if "users" in world else None
        if staff is not None:
            CrmUserMapping.objects.create(crm_user_id=7, user=staff)

        assert invite(world, contact).status_code == 200

        event = bus_support.only("partner.client_requested")
        bus_support.assert_matches_contract(event)
        data = event["data"]
        assert data["erp_company_id"] == supplier.pk
        assert data["company"] == {
            "name": supplier.name,
            "inn": "301234567",
            "registration_number": None,
            "country": None,
            "address": "Ташкент, ул. Образцовая, 1",
            "website": "https://supplier-north.example.uz",
            "language": supplier.language,
        }
        assert data["contacts"] == [
            {
                "erp_contact_id": contact.pk,
                "full_name": "Dilshod Supplier",
                "email": "dilshod@supplier-north.example.uz",
                "phone": "+998901112233",
                "language": "uz",
            }
        ]
        assert data["actor"]["type"] == "staff"
        if staff is not None:
            assert data["invited_by_crm_user_id"] == 7
        link = PartnerCrmLink.objects.get(company=supplier)
        assert link.status == "requested"
        assert partner_client.crm_client_state(supplier) == {"status": "requested", "crm_client_id": None}
        # окружение события: ни токенов, ни ссылок входа
        assert "token" not in str(event).lower()

    def test_foreign_company_goes_with_country_and_registration_number(self, world, supplier, contact):
        from core.models import Country

        country = Country.objects.get_or_create(code="CN", defaults={"name": "Китай", "alpha2": "CN"})[0]
        supplier.inn = None
        supplier.registration_number = "91310000MA1K"
        supplier.country = country
        supplier.save()

        assert invite(world, contact).status_code == 200

        company = bus_support.only("partner.client_requested")["data"]["company"]
        assert company["inn"] is None
        assert company["registration_number"] == "91310000MA1K" and company["country"] == "CN"

    def test_repeat_invite_without_mapping_publishes_again(self, world, supplier, contact):
        assert invite(world, contact).status_code == 200
        assert invite(world, contact).status_code == 200
        assert len(bus_support.published("partner.client_requested")) == 2
        assert PartnerCrmLink.objects.filter(company=supplier).count() == 1

    def test_no_request_for_a_company_that_is_already_a_crm_client(self, world, supplier, contact):
        CrmClientMapping.objects.create(crm_client_id=55, company=supplier)
        assert invite(world, contact).status_code == 200
        assert bus_support.published("partner.client_requested") == []
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 55}

    def test_rolled_back_invite_leaves_no_event_and_no_state(self, world, supplier, contact, monkeypatch):
        monkeypatch.setattr("portal.services.invitation.send_templated_email", lambda *a, **k: 1 / 0)
        response = invite(world, contact)
        assert response.status_code >= 400
        assert bus_support.published("partner.client_requested") == []
        assert not PartnerCrmLink.objects.exists() and not CompanyRelationship.objects.exists()

    def test_event_dies_with_the_surrounding_transaction(self, supplier, contact):
        class Boom(Exception):
            pass

        with pytest.raises(Boom), transaction.atomic():
            assert partner_client.request_client_in_crm(supplier) is not None
            raise Boom
        assert bus_support.published("partner.client_requested") == []

    def test_contacts_without_a_usable_email_are_not_sent(self, supplier, contact):
        Contact.objects.create(company=supplier, name="Без адреса", email="")
        Contact.objects.create(
            company=supplier, name="Архивный", email="old@s.example.uz", archived_at="2026-01-01T00:00Z"
        )
        with transaction.atomic():
            partner_client.request_client_in_crm(supplier)
        emails = [c["email"] for c in bus_support.only("partner.client_requested")["data"]["contacts"]]
        assert emails == ["dilshod@supplier-north.example.uz"]

    def test_company_without_any_contact_with_email_asks_nothing(self, supplier):
        with transaction.atomic():
            assert partner_client.request_client_in_crm(supplier) is None
        assert bus_support.published() == [] and not PartnerCrmLink.objects.exists()


# ── Ответ: linked ─────────────────────────────────────────────────────────────────────────────────────────────────────


class TestLinked:
    @pytest.fixture(autouse=True)
    def _asked(self, supplier):
        """Ответ `linked` принимается только на запрос: связь в «запрошено» (инвариант PART-CRM)."""
        PartnerCrmLink.objects.create(company=supplier, status="requested")

    def test_mapping_client_type_and_contact_mapping(self, supplier, contact):
        outcome = partner_client.apply_client_resolved(resolved(supplier, contact, matched_by="inn"))

        assert outcome.applied
        assert CrmClientMapping.objects.get(company=supplier).crm_client_id == 77
        assert supplier.types.filter(code="CLIENT").exists()
        assert CrmContactMapping.objects.get(contact=contact).crm_contact_id == 901
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 77}
        assert not PartnerCrmLink.objects.filter(company=supplier).exists()

    def test_repeat_changes_nothing(self, supplier, contact):
        from crm.models import ActivityLog

        partner_client.apply_client_resolved(resolved(supplier, contact))
        partner_client.apply_client_resolved(resolved(supplier, contact))

        assert CrmClientMapping.objects.filter(company=supplier).count() == 1
        assert CrmContactMapping.objects.filter(contact=contact).count() == 1
        assert supplier.types.filter(code="CLIENT").count() == 1
        assert ActivityLog.objects.filter(event_code="partner.crm_linked", company_id=supplier.pk).count() == 1

    def test_company_mapped_to_another_crm_client_is_not_rebound_and_crm_is_told(self, supplier, contact):
        CrmClientMapping.objects.create(crm_client_id=55, company=supplier)

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))

        assert CrmClientMapping.objects.get(company=supplier).crm_client_id == 55
        event = bus_support.only("partner.client_rejected")
        bus_support.assert_matches_contract(event)
        assert event["data"]["crm_client_id"] == 77
        assert event["data"]["reason"] == "company_mapped_to_other_client"

    def test_crm_client_held_by_another_company_is_a_conflict_not_a_rebind(self, supplier, contact):
        other = Company.objects.create(name="Другая", inn="300000111")
        CrmClientMapping.objects.create(crm_client_id=77, company=other)

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))

        assert CrmClientMapping.objects.get(crm_client_id=77).company_id == other.pk
        assert not CrmClientMapping.objects.filter(company=supplier).exists()
        assert partner_client.crm_client_state(supplier) == {"status": "conflict", "crm_client_id": 77}
        # CRM снимет `erp_company_id` со своего клиента: ERP отвечает ей событием, а не молчит
        event = bus_support.only("partner.client_rejected")
        bus_support.assert_matches_contract(event)
        assert event["data"] == {
            "erp_company_id": supplier.pk,
            "crm_client_id": 77,
            "reason": "client_mapped_to_other_company",
            "other_erp_company_id": other.pk,
            "actor": {"type": "system"},
        }

    def test_unknown_company_is_skipped(self):
        outcome = partner_client.apply_client_resolved(
            {"erp_company_id": 987654, "status": "linked", "crm_client_id": 1, "actor": {"type": "system"}}
        )
        assert outcome.status == partner_client.SKIPPED_UNKNOWN_COMPANY

    def test_existing_client_company_keeps_its_types(self, supplier, contact):
        client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]
        supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0]
        supplier.types.add(client_type, supplier_type)
        partner_client.apply_client_resolved(resolved(supplier, contact))
        assert supplier.types.filter(code="SUPPLIER").exists() and supplier.types.filter(code="CLIENT").count() == 1


# ── Ответ: conflict ───────────────────────────────────────────────────────────────────────────────────────────────────


class TestPendingConfirmation:
    """CRM нашла похожего клиента без сопоставления и ждёт менеджера: ничего не привязывается (решение архитектора по #397)."""

    def pending(self, supplier, crm_client_id=88):
        return {
            "erp_company_id": supplier.pk,
            "status": "pending_confirmation",
            "crm_client_id": crm_client_id,
            "matched_by": "inn",
            "actor": {"type": "system"},
        }

    def test_no_mapping_no_client_type_no_contact_mapping(self, supplier, contact):
        outcome = partner_client.apply_client_resolved(self.pending(supplier))

        assert outcome.applied
        assert not CrmClientMapping.objects.exists()
        assert not supplier.types.filter(code="CLIENT").exists()
        assert not CrmContactMapping.objects.exists()
        assert partner_client.crm_client_state(supplier) == {"status": "pending_confirmation", "crm_client_id": 88}

    def test_requests_stay_deferred_until_the_manager_decides(self, supplier, contact):
        from django.conf import settings as dj_settings
        from portal.tests.conftest import PortalAPIClient, make_portal_session

        CompanyRelationship.objects.create(
            company=supplier, role="partner", status="active", modules=["my_products", "catalog_requests"]
        )
        session = make_portal_session(contact, supplier, "magic_link")
        api = PortalAPIClient()
        api.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
        api.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
        assert (
            api.post(f"{PORTAL}/requests", {"summary": "Кабель", "lines": [{"text": "К"}]}, format="json").status_code
            == 201
        )

        partner_client.apply_client_resolved(self.pending(supplier))
        assert bus_support.published("request.created") == []
        assert DeferredRequestEvent.objects.get().published_at is None

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=88))  # менеджер подтвердил
        assert len(bus_support.published("request.created")) == 1
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 88}

    def test_repeat_does_not_duplicate_the_journal(self, supplier, contact):
        from crm.models import ActivityLog

        partner_client.apply_client_resolved(self.pending(supplier))
        partner_client.apply_client_resolved(self.pending(supplier))
        assert ActivityLog.objects.filter(event_code="partner.crm_pending", company_id=supplier.pk).count() == 1

    def test_late_pending_after_mapping_is_ignored(self, supplier):
        CrmClientMapping.objects.create(crm_client_id=55, company=supplier)
        outcome = partner_client.apply_client_resolved(self.pending(supplier))
        assert outcome.status == partner_client.SKIPPED_OTHER_CLIENT
        assert not PartnerCrmLink.objects.exists()


class TestConflict:
    def conflict(self, supplier, **extra):
        return resolved(supplier, status="conflict", crm_client_id=88, conflict_erp_company_id=999, **extra)

    def test_state_is_remembered_and_nothing_is_rebound(self, supplier, contact):
        outcome = partner_client.apply_client_resolved(self.conflict(supplier))

        assert outcome.applied
        link = PartnerCrmLink.objects.get(company=supplier)
        assert (link.status, link.crm_client_id, link.conflict_company_id) == ("conflict", 88, 999)
        assert not CrmClientMapping.objects.filter(company=supplier).exists()
        assert not supplier.types.filter(code="CLIENT").exists()
        assert partner_client.crm_client_state(supplier) == {"status": "conflict", "crm_client_id": 88}

    def test_responsible_is_notified_once(self, world, supplier, contact):
        from notifications.models import Notification

        assert invite(world, contact).status_code == 200
        relationship = CompanyRelationship.objects.get(company=supplier)
        assert relationship.responsible_id is not None

        partner_client.apply_client_resolved(self.conflict(supplier))
        partner_client.apply_client_resolved(self.conflict(supplier))

        notes = Notification.objects.filter(user=relationship.responsible, event_code="partner.crm_conflict")
        assert notes.count() == 1
        assert "объедин" not in notes[0].message.lower(), "шаги — исправить ИНН и пригласить ещё раз, а не «объединить»"
        assert "ИНН" in notes[0].message

    def test_stale_conflict_after_mapping_is_ignored(self, supplier):
        CrmClientMapping.objects.create(crm_client_id=55, company=supplier)
        outcome = partner_client.apply_client_resolved(self.conflict(supplier))
        assert outcome.status == partner_client.SKIPPED_OTHER_CLIENT
        assert not PartnerCrmLink.objects.exists()

    def test_reinvite_after_conflict_asks_again_and_a_later_link_resolves_it(self, world, supplier, contact):
        assert invite(world, contact).status_code == 200
        partner_client.apply_client_resolved(self.conflict(supplier))
        assert invite(world, contact).status_code == 200
        assert len(bus_support.published("partner.client_requested")) == 2
        assert partner_client.crm_client_state(supplier)["status"] == "requested"

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 77}


# ── Заявки партнёра до сопоставления ─────────────────────────────────────────────────────────────────────────────────


class TestDeferredRequests:
    @pytest.fixture(autouse=True)
    def _asked(self, supplier):
        """Ответ `linked` принимается только на запрос: связь в «запрошено» (инвариант PART-CRM)."""
        PartnerCrmLink.objects.create(company=supplier, status="requested")

    @pytest.fixture
    def partner_api(self, supplier, contact):
        from django.conf import settings as dj_settings
        from portal.tests.conftest import PortalAPIClient, make_portal_session

        CompanyRelationship.objects.create(
            company=supplier, role="partner", status="active", modules=["my_products", "catalog_requests"]
        )
        session = make_portal_session(contact, supplier, "magic_link")
        client = PortalAPIClient()
        client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
        client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
        return client

    def create_request(self, api, text="Нужен кабель"):
        response = api.post(f"{PORTAL}/requests", {"summary": text, "lines": [{"text": "Кабель"}]}, format="json")
        assert response.status_code == 201, response.content
        return response

    def test_request_before_mapping_is_deferred_then_published_once(self, partner_api, supplier, contact):
        self.create_request(partner_api)
        assert bus_support.published("request.created") == []
        row = DeferredRequestEvent.objects.get()
        assert row.published_at is None

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))

        event = bus_support.only("request.created")
        bus_support.assert_matches_contract(event)
        assert event["data"]["crm_client_id"] == 77 and event["data"]["erp_company_id"] == supplier.pk
        assert event["data"]["payload"]["source"] == "cabinet"
        assert event["data"]["payload"]["summary"] == "Нужен кабель"
        row.refresh_from_db()
        assert row.published_at is not None

        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))
        assert len(bus_support.published("request.created")) == 1, "повтор ответа не публикует заявку второй раз"

    def test_request_after_mapping_goes_immediately_and_is_not_deferred(self, partner_api, supplier, contact):
        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))
        self.create_request(partner_api)
        assert len(bus_support.published("request.created")) == 1
        assert not DeferredRequestEvent.objects.exists()

    def test_the_unrouted_notice_stays_for_the_period_before_mapping(self, partner_api, supplier):
        from notifications.models import Notification

        self.create_request(partner_api)
        assert Notification.objects.filter(event_code="portal.partner_request_unrouted").exists()

    def test_request_of_a_company_without_the_partner_relationship_is_not_deferred(self, supplier, contact):
        """Отложенные события — только у партнёров: клиента без сопоставления по-прежнему заводит передача из CRM."""
        from django.conf import settings as dj_settings
        from portal.tests.conftest import PortalAPIClient, make_portal_session

        client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]
        supplier.types.add(client_type)  # клиент без отношения partner и без сопоставления CRM
        assert not CompanyRelationship.objects.filter(company=supplier).exists()
        session = make_portal_session(contact, supplier, "magic_link")
        api = PortalAPIClient()
        api.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
        api.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)

        self.create_request(api)

        assert not DeferredRequestEvent.objects.exists()
        assert bus_support.published("request.created") == []

    def _handoff_of_foreign_client(self, supplier, settings, crm_client_id=4001):
        from integration.tests.test_handoff import SERVICE_TOKEN, handoff, payload
        from rest_framework.test import APIClient

        settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
        return handoff(
            api,
            payload(crm_client_id=crm_client_id, inn=supplier.inn, create_request=False, email="x@other.example.uz"),
        )

    def cabinet_events(self):
        return [e for e in bus_support.published("request.created") if e["data"]["payload"]["source"] == "cabinet"]

    def test_a_handoff_of_a_foreign_client_with_the_partners_inn_creates_no_mapping_and_leaks_nothing(
        self, partner_api, supplier, contact, settings, world
    ):
        """Партнёр указал ИНН чужого клиента CRM, и передача этого клиента нашла компанию по ИНН.

        Инвариант: у партнёра сопоставление — только после подтверждённой связи. Передача его не создаёт (409
        `PARTNER_VERIFICATION_REQUIRED`), заявки партнёра у чужого клиента не появляются, в том числе новые.
        """
        from notifications.models import Notification

        relationship = CompanyRelationship.objects.get(company=supplier)
        staff = world["users"]["supply"]
        relationship.responsible = staff
        relationship.save(update_fields=["responsible"])
        self.create_request(partner_api)
        assert DeferredRequestEvent.objects.get().published_at is None

        response = self._handoff_of_foreign_client(supplier, settings)

        assert response.status_code == 409 and response.json() == {"detail": "PARTNER_VERIFICATION_REQUIRED"}
        assert not CrmClientMapping.objects.exists(), "сопоставление партнёра не создано"
        assert not supplier.types.filter(code="CLIENT").exists()
        assert partner_client.crm_client_state(supplier) == {"status": "held", "crm_client_id": 4001}
        assert Notification.objects.filter(user=staff, event_code="partner.crm_unverified").count() == 1
        # повтор передачи (ручной повтор в CRM): тот же ответ, без второго уведомления
        assert self._handoff_of_foreign_client(supplier, settings).status_code == 409
        assert Notification.objects.filter(user=staff, event_code="partner.crm_unverified").count() == 1
        # заявка партнёра после передачи, до повторного приглашения: сопоставления нет — отложена, чужому клиенту не уходит
        self.create_request(partner_api, "Новая заявка после передачи")
        assert self.cabinet_events() == []
        assert DeferredRequestEvent.objects.filter(published_at__isnull=True).count() == 2

    def test_a_late_linked_after_the_handoff_hold_releases_nothing(self, partner_api, supplier, contact, settings):
        """Передача удержана; поздний `linked` на старый запрос (отправлен до передачи) ничего не создаёт и не выпускает."""
        from crm.models import ActivityLog

        PartnerCrmLink.objects.filter(company=supplier).delete()
        PartnerCrmLink.objects.create(company=supplier, status="requested")
        self.create_request(partner_api)
        assert self._handoff_of_foreign_client(supplier, settings).status_code == 409

        outcome = partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=4001))

        assert outcome.status == partner_client.SKIPPED_NO_REQUEST
        assert not CrmClientMapping.objects.exists() and not CrmContactMapping.objects.exists()
        assert not supplier.types.filter(code="CLIENT").exists()
        assert self.cabinet_events() == []
        assert DeferredRequestEvent.objects.get().published_at is None
        assert partner_client.crm_client_state(supplier)["status"] == "held"
        assert ActivityLog.objects.filter(event_code="partner.crm_linked_ignored", company_id=supplier.pk).count() == 1

    def test_reinvite_after_the_hold_goes_to_crm_and_only_a_confirmed_link_releases_the_requests(
        self, partner_api, supplier, contact, settings, world
    ):
        self.create_request(partner_api)
        assert self._handoff_of_foreign_client(supplier, settings).status_code == 409

        assert invite(world, contact).status_code == 200  # сотрудник сверил ИНН: запрос уходит в CRM
        assert bus_support.only("partner.client_requested")["data"]["erp_company_id"] == supplier.pk
        assert partner_client.crm_client_state(supplier)["status"] == "requested"
        assert self.cabinet_events() == []
        # CRM нашла клиента по ИНН и просит подтверждение менеджера: по-прежнему ничего не выпущено
        partner_client.apply_client_resolved(
            {
                "erp_company_id": supplier.pk,
                "status": "pending_confirmation",
                "crm_client_id": 4001,
                "actor": {"type": "system"},
            }
        )
        assert partner_client.crm_client_state(supplier)["status"] == "pending_confirmation"
        assert self.cabinet_events() == [] and not CrmClientMapping.objects.exists()
        # менеджер CRM подтвердил: `linked`
        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=4001))
        released = self.cabinet_events()
        assert len(released) == 1 and released[0]["data"]["crm_client_id"] == 4001
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 4001}

    def test_a_handoff_of_a_company_without_the_partner_relationship_holds_nothing(self, supplier, settings):
        from integration.tests.test_handoff import SERVICE_TOKEN, handoff, payload
        from rest_framework.test import APIClient

        PartnerCrmLink.objects.all().delete()  # фикстура класса создала связь, у клиента без отношения её нет
        settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")

        assert handoff(api, payload(crm_client_id=4002, inn=supplier.inn, create_request=False)).status_code == 201

        assert not PartnerCrmLink.objects.exists()
        assert partner_client.crm_client_state(supplier) == {"status": "linked", "crm_client_id": 4002}


# ── Роли сессии ───────────────────────────────────────────────────────────────────────────────────────────────────────


class TestRoles:
    @pytest.fixture(autouse=True)
    def _asked(self, supplier):
        """Ответ `linked` принимается только на запрос: связь в «запрошено» (инвариант PART-CRM)."""
        PartnerCrmLink.objects.create(company=supplier, status="requested")

    def test_me_of_a_linked_partner_has_client_and_partner(self, supplier, contact):
        from django.conf import settings as dj_settings
        from portal.tests.conftest import PortalAPIClient, make_portal_session

        CompanyRelationship.objects.create(
            company=supplier, role="partner", status="active", modules=["my_products", "catalog_requests"]
        )
        session = make_portal_session(contact, supplier, "magic_link")
        api = PortalAPIClient()
        api.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
        api.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)

        before = api.get(f"{PORTAL}/me").json()
        assert before["roles"] == ["partner"]

        partner_client.apply_client_resolved(resolved(supplier, contact))

        after = api.get(f"{PORTAL}/me").json()
        assert after["roles"] == ["client", "partner"]
        assert {"quotes", "invoices", "my_products", "catalog_requests", "profile"} <= set(after["modules"])


# ── Состояние в блоке «Доступ в кабинет» ─────────────────────────────────────────────────────────────────────────────


class TestDeskState:
    def test_block_shows_none_requested_linked_conflict(self, world, supplier, contact):
        def state():
            return (
                world["clients"]["supply"].get(f"/api/v1/catalog/supplier-access/{supplier.pk}/").json()["crm_client"]
            )

        assert state() == {"status": "none", "crm_client_id": None}
        assert invite(world, contact).status_code == 200
        assert state() == {"status": "requested", "crm_client_id": None}
        partner_client.apply_client_resolved(
            {
                "erp_company_id": supplier.pk,
                "status": "pending_confirmation",
                "crm_client_id": 90,
                "actor": {"type": "system"},
            }
        )
        assert state() == {"status": "pending_confirmation", "crm_client_id": 90}
        partner_client.apply_client_resolved(resolved(supplier, status="conflict", crm_client_id=88))
        assert state() == {"status": "conflict", "crm_client_id": 88}
        assert invite(world, contact).status_code == 200  # «Пригласить ещё раз» — новый запрос
        partner_client.apply_client_resolved(resolved(supplier, contact, crm_client_id=77))
        assert state() == {"status": "linked", "crm_client_id": 77}


# ── Шина ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


class TestBusHandler:
    @pytest.fixture(autouse=True)
    def _asked(self, supplier):
        """Ответ `linked` принимается только на запрос: связь в «запрошено» (инвариант PART-CRM)."""
        PartnerCrmLink.objects.create(company=supplier, status="requested")

    def test_the_answer_event_goes_through_the_registered_handler(self, supplier, contact):
        from types import SimpleNamespace

        from integration import bus_handlers
        from rt_bus import default_registry

        assert default_registry.match("uz.railtech.crm.partner.client_resolved.v1")
        bus_handlers.on_partner_client_resolved(SimpleNamespace(data=resolved(supplier, contact)))
        assert CrmClientMapping.objects.filter(company=supplier, crm_client_id=77).exists()
