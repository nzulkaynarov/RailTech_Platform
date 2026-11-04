"""PART-1: блок «Доступ в кабинет» карточки поставщика — контакты, приглашение, приостановка (ERP, `/api/v1/catalog/supplier-access/`).

Чтение — любой сотрудник бэк-офиса, изменения — `supply.manage` (то право, которым правят поставщиков). Мир — `catalog.tests.desk_world`.
"""

import re

import pytest
from django.core import mail
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipStatus
from portal.tests.conftest import LOCMEM_BACKEND

from catalog.tests.desk_world import build_world
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.fixture
def world():
    return build_world()


def url(world, suffix=""):
    return f"/api/v1/catalog/supplier-access/{world['supplier'].pk}/{suffix}"


def call(world, who, method, suffix="", body=None):
    return getattr(world["clients"][who], method)(url(world, suffix), body, format="json")


CONTACT = {
    "name": "Dilshod Supplier",
    "email": "Dilshod@Supplier-North.example.uz",
    "phone": "+998901112233",
    "language": "uz",
}


def add_contact(world, **extra):
    response = call(world, "supply", "post", "contacts/", {**CONTACT, **extra})
    assert response.status_code == 201, response.content
    return response.json()


class TestRead:
    def test_every_staff_role_reads_state(self, world):
        for who in world["clients"]:
            response = call(world, who, "get")
            assert response.status_code == 200, who
            body = response.json()
            assert body["relationship"] is None and body["contacts"] == []
            assert body["can_manage"] is (who in ("supply", "engineer", "director")), who

    def test_unknown_or_own_company_is_404(self, world):
        client = world["clients"]["supply"]
        assert client.get("/api/v1/catalog/supplier-access/999999/").status_code == 404
        assert client.get(f"/api/v1/catalog/supplier-access/{world['own'].pk}/").status_code == 404

    def test_anonymous_is_401(self, world):
        from rest_framework.test import APIClient

        assert APIClient().get(url(world)).status_code == 401


class TestWriteIsGatedBySupplyManage:
    @pytest.mark.parametrize("who", ["manager", "accountant", "viewer"])
    def test_staff_without_supply_manage_gets_403_on_every_mutation(self, world, who):
        contact = Contact.objects.create(company=world["supplier"], name="X", email="x@s.example.uz")
        for method, suffix, body in (
            ("post", "contacts/", CONTACT),
            ("patch", f"contacts/{contact.pk}/", {"name": "Y"}),
            ("post", "invite/", {"contact_id": contact.pk}),
            ("patch", "relationship/", {"modules": []}),
            ("post", "suspend/", None),
        ):
            response = call(world, who, method, suffix, body)
            assert response.status_code == 403, (who, suffix)
        assert not CompanyRelationship.objects.exists() and mail.outbox == []


class TestContacts:
    def test_add_normalises_email_and_lists(self, world):
        created = add_contact(world)
        assert created["email"] == "dilshod@supplier-north.example.uz" and created["language"] == "uz"
        listed = call(world, "supply", "get").json()["contacts"]
        assert [c["id"] for c in listed] == [created["id"]]
        contact = Contact.objects.get(pk=created["id"])
        assert (
            contact.can_act is True and contact.company_id == world["supplier"].pk
        )  # право действовать — по умолчанию
        assert created["can_act"] is True

    def test_email_is_required_and_language_is_validated(self, world):
        assert call(world, "supply", "post", "contacts/", {"name": "A"}).status_code == 400
        assert call(world, "supply", "post", "contacts/", {**CONTACT, "language": "de"}).status_code == 400
        assert call(world, "supply", "post", "contacts/", {**CONTACT, "email": "no"}).status_code == 400

    def test_duplicate_email_in_company_is_409(self, world):
        add_contact(world)
        response = call(world, "supply", "post", "contacts/", {**CONTACT, "name": "Other"})
        assert response.status_code == 409 and response.json() == {"detail": "CONTACT_EXISTS"}

    def test_patch_changes_fields_and_keeps_company(self, world):
        created = add_contact(world)
        response = call(
            world, "supply", "patch", f"contacts/{created['id']}/", {"name": "Dilshod K.", "language": "en"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Dilshod K." and response.json()["language"] == "en"

    def test_can_act_switch_per_contact_changes_what_the_partner_may_do(self, world):
        from portal.tests.conftest import PortalAPIClient

        created = add_contact(world, can_act=False)
        assert created["can_act"] is False
        call(world, "supply", "post", "invite/", {"contact_id": created["id"]})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        portal = PortalAPIClient()
        portal.post("/api/portal/v1/auth/code", {"email": created["email"], "code": code}, format="json")
        body = {"summary": "Нужен кабель", "lines": [{"text": "Кабель"}]}
        assert portal.post("/api/portal/v1/requests", body, format="json").status_code == 403

        on = call(world, "supply", "patch", f"contacts/{created['id']}/", {"can_act": True})
        assert on.status_code == 200 and on.json()["can_act"] is True
        assert portal.post("/api/portal/v1/requests", body, format="json").status_code == 201

    def test_patch_foreign_contact_is_404(self, world):
        other = Company.objects.create(name="Other Co", inn="300000999")
        foreign = Contact.objects.create(company=other, name="F", email="f@other.example.uz")
        assert call(world, "supply", "patch", f"contacts/{foreign.pk}/", {"name": "Z"}).status_code == 404
        foreign.refresh_from_db()
        assert foreign.name == "F"

    def test_changes_are_journaled(self, world):
        add_contact(world)
        assert ActivityLog.objects.filter(entity_type="supplier_access").exists()


class TestInvite:
    def test_invite_creates_relationship_and_sends_code_in_contact_language(self, world):
        contact_id = add_contact(world)["id"]
        response = call(world, "supply", "post", "invite/", {"contact_id": contact_id})

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["relationship"]["status"] == "invited" and body["relationship"]["role"] == "partner"
        assert body["relationship"]["invited_by"]["id"] == world["users"]["supply"].pk
        assert body["relationship"]["responsible"]["id"] == world["users"]["supply"].pk
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["dilshod@supplier-north.example.uz"]
        assert re.search(r"\b\d{6}\b", message.body) and "mahsulotlaringiz" in message.body  # uz, текст партнёра

    def test_invite_response_never_carries_the_login_link_or_code(self, world):
        contact_id = add_contact(world)["id"]
        response = call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        assert code not in response.content.decode() and "auth/magic" not in response.content.decode()

    def test_end_to_end_partner_logs_in_with_the_emailed_code(self, world):
        from portal.tests.conftest import PortalAPIClient

        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)

        portal = PortalAPIClient()
        login = portal.post(
            "/api/portal/v1/auth/code", {"email": "dilshod@supplier-north.example.uz", "code": code}, format="json"
        )
        assert login.status_code == 200, login.content
        me = portal.get("/api/portal/v1/me").json()
        assert me["roles"] == ["partner"] and me["modules"] == ["my_products", "catalog_requests", "profile"]
        assert CompanyRelationship.objects.get(company=world["supplier"]).status == RelationshipStatus.ACTIVE
        assert portal.get("/api/portal/v1/catalog").status_code == 200  # «Каталог и заявки» включён по умолчанию
        assert portal.get("/api/portal/v1/quotes").status_code == 403

    def test_reinvite_keeps_responsible_and_does_not_duplicate(self, world):
        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        call(world, "director", "post", "invite/", {"contact_id": contact_id})
        relationship = CompanyRelationship.objects.get(company=world["supplier"])
        assert CompanyRelationship.objects.count() == 1
        assert relationship.responsible_id == world["users"]["supply"].pk
        assert relationship.invited_by_id == world["users"]["director"].pk
        assert len(mail.outbox) == 2

    def test_failed_mail_leaves_no_relationship(self, world, monkeypatch):
        contact_id = add_contact(world)["id"]
        monkeypatch.setattr("portal.services.invitation.send_templated_email", lambda *a, **k: 1 / 0)
        response = call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        assert response.status_code == 400 and response.json() == {"detail": "EMAIL_DELIVERY_FAILED"}
        assert not CompanyRelationship.objects.exists()

    def test_contact_of_another_company_cannot_be_invited_through_this_card(self, world):
        other = Company.objects.create(name="Other Co", inn="300000999")
        foreign = Contact.objects.create(company=other, name="F", email="f@other.example.uz")
        response = call(world, "supply", "post", "invite/", {"contact_id": foreign.pk})
        assert response.status_code == 404 and not CompanyRelationship.objects.exists() and mail.outbox == []

    def test_address_shared_with_a_client_company_is_refused(self, world):
        """Ссылка входа по общему адресу открыла бы чужую компанию — приглашение не уходит."""
        client = Company.objects.create(name="OOO Client", inn="300000888")
        client.types.add(CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0])
        Contact.objects.create(company=client, name="Same", email=CONTACT["email"].lower())
        contact_id = add_contact(world)["id"]
        response = call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        assert response.status_code == 409 and response.json() == {"detail": "CONTACT_EMAIL_AMBIGUOUS"}
        assert not CompanyRelationship.objects.exists() and mail.outbox == []

    def test_archived_contact_cannot_be_invited(self, world):
        from django.utils import timezone

        contact_id = add_contact(world)["id"]
        Contact.objects.filter(pk=contact_id).update(archived_at=timezone.now())
        assert call(world, "supply", "post", "invite/", {"contact_id": contact_id}).status_code == 404


class TestSuspend:
    def test_suspend_closes_entry_and_kills_session_then_invite_returns(self, world):
        from portal.tests.conftest import PortalAPIClient

        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        portal = PortalAPIClient()
        portal.post(
            "/api/portal/v1/auth/code", {"email": "dilshod@supplier-north.example.uz", "code": code}, format="json"
        )
        assert portal.get("/api/portal/v1/me").status_code == 200

        response = call(world, "supply", "post", "suspend/")
        assert response.status_code == 200 and response.json()["relationship"]["status"] == "suspended"
        assert portal.get("/api/portal/v1/me").status_code == 401  # живая сессия погасла
        portal.post("/api/portal/v1/auth/magic-link", {"email": "dilshod@supplier-north.example.uz"}, format="json")
        assert len(mail.outbox) == 1  # ссылки входа приостановленному не шлют

        # «Пригласить» возвращает доступ: бывавший в кабинете остаётся активным
        again = call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        assert (
            again.json()["relationship"]["status"] == "active" and again.json()["relationship"]["suspended_at"] is None
        )

    def test_suspend_without_relationship_is_404(self, world):
        assert call(world, "supply", "post", "suspend/").status_code == 404

    def test_suspend_is_idempotent(self, world):
        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        first = call(world, "supply", "post", "suspend/").json()["relationship"]["suspended_at"]
        assert call(world, "supply", "post", "suspend/").json()["relationship"]["suspended_at"] == first

    def test_history_records_status_changes(self, world):
        from parties.models import CompanyRelationship as Model

        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        call(world, "supply", "post", "suspend/")
        events = Model.pgh_event_model if hasattr(Model, "pgh_event_model") else None
        assert events is not None
        assert list(events.objects.order_by("pgh_id").values_list("status", flat=True)) == ["invited", "suspended"]


class TestRights:
    """Права партнёра — модули на отношении: сотрудник включает и выключает их в Платформе, действует сразу."""

    def _logged_in_partner(self, world):
        from portal.tests.conftest import PortalAPIClient

        contact_id = add_contact(world)["id"]
        call(world, "supply", "post", "invite/", {"contact_id": contact_id})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        portal = PortalAPIClient()
        assert (
            portal.post(
                "/api/portal/v1/auth/code", {"email": "dilshod@supplier-north.example.uz", "code": code}, format="json"
            ).status_code
            == 200
        )
        return portal

    def test_defaults_state_and_template(self, world):
        state = call(world, "supply", "get").json()
        assert state["partner_modules"] == {
            "allowed": ["my_products", "catalog_requests"],
            "default": ["my_products", "catalog_requests"],
        }
        assert state["cabinet_roles"] == [] and state["cabinet_modules"] == []  # кабинет поставщику ещё не открывали
        add = call(world, "supply", "post", "invite/", {"contact_id": add_contact(world)["id"]}).json()
        assert (
            add["relationship"]["modules"] == ["my_products", "catalog_requests"] and add["relationship"]["kind"] == ""
        )
        assert add["cabinet_roles"] == ["partner"]
        assert add["cabinet_modules"] == ["my_products", "catalog_requests", "profile"]

    def test_invite_with_chosen_modules_and_kind(self, world):
        contact_id = add_contact(world)["id"]
        body = call(
            world,
            "supply",
            "post",
            "invite/",
            {"contact_id": contact_id, "modules": ["my_products"], "kind": "principal"},
        ).json()
        assert body["relationship"]["modules"] == ["my_products"] and body["relationship"]["kind"] == "principal"

    def test_toggle_applies_to_the_live_session_at_once(self, world):
        portal = self._logged_in_partner(world)
        assert portal.get("/api/portal/v1/catalog").status_code == 200

        off = call(world, "supply", "patch", "relationship/", {"modules": ["my_products"]})
        assert off.status_code == 200 and off.json()["relationship"]["modules"] == ["my_products"]
        assert portal.get("/api/portal/v1/catalog").status_code == 403
        assert portal.get("/api/portal/v1/requests").status_code == 403
        assert portal.get("/api/portal/v1/me").json()["modules"] == ["my_products", "profile"]

        call(world, "supply", "patch", "relationship/", {"modules": ["my_products", "catalog_requests"]})
        assert portal.get("/api/portal/v1/catalog").status_code == 200

    def test_module_outside_the_partner_template_is_refused(self, world):
        call(world, "supply", "post", "invite/", {"contact_id": add_contact(world)["id"]})
        for module in ("quotes", "invoices", "contracts", "unknown"):
            response = call(world, "supply", "patch", "relationship/", {"modules": [module]})
            assert response.status_code == 400, module
        relationship = CompanyRelationship.objects.get()
        assert relationship.modules == ["my_products", "catalog_requests"]
        invite = call(
            world,
            "supply",
            "post",
            "invite/",
            {"contact_id": add_contact(world, email="b@s.example.uz")["id"], "modules": ["quotes"]},
        )
        assert invite.status_code == 400

    def test_patch_without_relationship_is_404(self, world):
        assert call(world, "supply", "patch", "relationship/", {"modules": []}).status_code == 404

    def test_kind_is_a_label_only(self, world):
        call(world, "supply", "post", "invite/", {"contact_id": add_contact(world)["id"]})
        for kind in ("manufacturer", "supplier", "principal", "other", ""):
            response = call(world, "supply", "patch", "relationship/", {"kind": kind})
            assert response.status_code == 200 and response.json()["relationship"]["kind"] == kind
            assert response.json()["relationship"]["modules"] == ["my_products", "catalog_requests"]
        assert call(world, "supply", "patch", "relationship/", {"kind": "vendor"}).status_code == 400

    def test_who_and_when_is_in_history_and_journal(self, world):
        from parties.models import CompanyRelationship as Model

        call(world, "supply", "post", "invite/", {"contact_id": add_contact(world)["id"]})
        call(world, "director", "patch", "relationship/", {"modules": ["my_products"]})
        event = Model.pgh_event_model.objects.order_by("-pgh_id").first()
        assert event.modules == ["my_products"]
        # Автор правки в тестах — в журнале (контекст pghistory в тестовой базе заглушен, `conftest.django_db_setup`).
        log = ActivityLog.objects.filter(entity_type="supplier_access", action__icontains="Права").first()
        assert log is not None and log.user_id == world["users"]["director"].pk

    def test_suspended_partner_changes_nothing_for_entry(self, world):
        portal = self._logged_in_partner(world)
        call(world, "supply", "post", "suspend/")
        call(world, "supply", "patch", "relationship/", {"modules": ["my_products", "catalog_requests"]})
        assert portal.get("/api/portal/v1/me").status_code == 401
