"""Тесты очереди заявок кандидатов в партнёры и договорного шлюза (PART-ONBOARD-2).

`/api/v1/catalog/partner-applications/` и реквизиты договора в `/api/v1/catalog/supplier-access/`.
"""

import pytest
from django.core import mail
from parties.models import (
    Company,
    CompanyRelationship,
    Contact,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    PartnerKind,
    RelationshipRole,
    RelationshipStatus,
)
from portal.tests.conftest import LOCMEM_BACKEND

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.fixture
def world():
    return build_world()


def _make_app(**kwargs) -> PartnerApplication:
    defaults = {
        "source": PartnerApplicationSource.PUBLIC,
        "company_name": "ООО Завод Металл",
        "inn": "7701234567",
        "contact_name": "Иван Металлов",
        "email": "metal@example.com",
        "phone": "+998901234567",
        "language": "ru",
        "kind": PartnerKind.MANUFACTURER,
        "categories_description": "Рельсы, стрелочные переводы, крепеж",
        "status": PartnerApplicationStatus.SUBMITTED,
    }
    defaults.update(kwargs)
    return PartnerApplication.objects.create(**defaults)


class TestPartnerApplicationsRead:
    def test_staff_can_list_and_count_pending(self, world):
        _make_app(status=PartnerApplicationStatus.SUBMITTED)
        _make_app(status=PartnerApplicationStatus.SUBMITTED, company_name="Второй", inn="7709999999")
        _make_app(status=PartnerApplicationStatus.CONTRACT_SENT, company_name="Третий", inn="7708888888")

        client = world["clients"]["supply"]
        response = client.get("/api/v1/catalog/partner-applications/")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 3
        assert data["pending_count"] == 2

    def test_status_filter(self, world):
        _make_app(status=PartnerApplicationStatus.SUBMITTED)
        _make_app(status=PartnerApplicationStatus.CONTRACT_SENT, company_name="Второй", inn="7709999999")

        client = world["clients"]["manager"]
        response = client.get("/api/v1/catalog/partner-applications/?status=contract_sent")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "contract_sent"
        assert data["pending_count"] == 1

    def test_retrieve_detail_with_matching_company(self, world):
        company = world["supplier"]
        app = _make_app(inn=company.inn or "999888777")
        if not company.inn:
            company.inn = "999888777"
            company.save()
            app.inn = "999888777"
            app.save()

        client = world["clients"]["supply"]
        response = client.get(f"/api/v1/catalog/partner-applications/{app.pk}/")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == app.pk
        assert data["matching_company_id"] == company.pk
        assert data["matching_company_name"] == company.name


class TestPartnerApplicationsAccessControl:
    def test_anonymous_is_401(self):
        from rest_framework.test import APIClient

        assert APIClient().get("/api/v1/catalog/partner-applications/").status_code == 401

    @pytest.mark.parametrize("who", ["manager", "accountant", "viewer"])
    def test_mutations_require_supply_manage(self, world, who):
        app = _make_app()
        client = world["clients"][who]

        for method, suffix, body in (
            ("post", "send-contract/", {"contract_number": "D-1"}),
            ("post", "approve/", {"contract_number": "D-1"}),
            ("post", "reject/", {"rejected_reason": "Не наш профиль"}),
        ):
            resp = getattr(client, method)(
                f"/api/v1/catalog/partner-applications/{app.pk}/{suffix}", body, format="json"
            )
            assert resp.status_code == 403, (who, suffix)


class TestSendContract:
    def test_supply_can_send_contract(self, world):
        app = _make_app()
        client = world["clients"]["supply"]
        resp = client.post(
            f"/api/v1/catalog/partner-applications/{app.pk}/send-contract/",
            {"contract_number": "DOG-2026-001", "contract_date": "2026-11-06"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "contract_sent"
        assert data["contract_number"] == "DOG-2026-001"
        assert data["contract_date"] == "2026-11-06"
        assert data["reviewed_by"] is not None

        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.CONTRACT_SENT
        assert app.contract_number == "DOG-2026-001"


class TestRejectApplication:
    def test_reject_requires_reason(self, world):
        app = _make_app()
        client = world["clients"]["supply"]
        resp = client.post(f"/api/v1/catalog/partner-applications/{app.pk}/reject/", {}, format="json")
        assert resp.status_code == 400

    def test_reject_sets_status_and_reason(self, world):
        app = _make_app()
        client = world["clients"]["supply"]
        resp = client.post(
            f"/api/v1/catalog/partner-applications/{app.pk}/reject/",
            {"rejected_reason": "Несоответствие номенклатуры профилю платформы"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["rejected_reason"] == "Несоответствие номенклатуры профилю платформы"

        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.REJECTED


class TestApproveApplicationClientCabinet:
    def test_approve_client_cabinet_activates_partner_relationship(self, world):
        client_company = Company.objects.create(name="Клиент ООО", inn="1234567890", is_active=True)
        contact = Contact.objects.create(company=client_company, name="Заявитель", email="client@example.com")
        app = _make_app(
            source=PartnerApplicationSource.CLIENT_CABINET,
            company=client_company,
            applicant_contact=contact,
            company_name=client_company.name,
            inn=client_company.inn,
        )

        client = world["clients"]["supply"]
        resp = client.post(
            f"/api/v1/catalog/partner-applications/{app.pk}/approve/",
            {"contract_number": "PRT-CLIENT-01", "contract_date": "2026-11-06"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["contract_number"] == "PRT-CLIENT-01"

        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.APPROVED

        rel = CompanyRelationship.objects.get(company=client_company, role=RelationshipRole.PARTNER)
        assert rel.status == RelationshipStatus.ACTIVE
        assert rel.contract_number == "PRT-CLIENT-01"
        assert str(rel.contract_date) == "2026-11-06"
        assert "my_products" in rel.modules


class TestApproveApplicationPublic:
    def test_approve_public_creates_company_and_invites_partner(self, world):
        app = _make_app(
            source=PartnerApplicationSource.PUBLIC,
            company_name="Новый Завод Стрелка",
            inn="5001234567",
            contact_name="Петр Стрелочник",
            email="strelka@example.com",
            phone="+998901112233",
            kind=PartnerKind.MANUFACTURER,
        )

        client = world["clients"]["supply"]
        resp = client.post(
            f"/api/v1/catalog/partner-applications/{app.pk}/approve/",
            {"contract_number": "DOG-MANUF-99", "contract_date": "2026-11-06"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"

        app.refresh_from_db()
        assert app.status == PartnerApplicationStatus.APPROVED
        assert app.company is not None
        assert app.company.name == "Новый Завод Стрелка"
        assert app.company.inn == "5001234567"

        # Проверяем созданный контакт и отправку приглашения
        created_contact = Contact.objects.get(company=app.company, email="strelka@example.com")
        assert created_contact.name == "Петр Стрелочник"
        assert len(mail.outbox) == 1
        assert "strelka@example.com" in mail.outbox[0].to

        # Проверяем отношение
        rel = CompanyRelationship.objects.get(company=app.company, role=RelationshipRole.PARTNER)
        assert rel.status == RelationshipStatus.INVITED
        assert rel.contract_number == "DOG-MANUF-99"
        assert str(rel.contract_date) == "2026-11-06"
        assert rel.kind == PartnerKind.MANUFACTURER


class TestSupplierAccessContractFields:
    def test_contract_fields_in_supplier_access(self, world):
        supplier = world["supplier"]
        rel = CompanyRelationship.objects.create(
            company=supplier,
            role=RelationshipRole.PARTNER,
            status=RelationshipStatus.ACTIVE,
            contract_number="SUPP-CT-101",
            contract_date="2026-10-15",
        )

        client = world["clients"]["supply"]
        resp = client.get(f"/api/v1/catalog/supplier-access/{supplier.pk}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["relationship"]["contract_number"] == "SUPP-CT-101"
        assert data["relationship"]["contract_date"] == "2026-10-15"

        # Проверяем PATCH relationship с обновлением договора
        patch_resp = client.patch(
            f"/api/v1/catalog/supplier-access/{supplier.pk}/relationship/",
            {"contract_number": "SUPP-CT-202", "contract_date": "2026-11-01"},
            format="json",
        )
        assert patch_resp.status_code == 200
        patch_data = patch_resp.json()
        assert patch_data["relationship"]["contract_number"] == "SUPP-CT-202"
        assert patch_data["relationship"]["contract_date"] == "2026-11-01"

        rel.refresh_from_db()
        assert rel.contract_number == "SUPP-CT-202"
        assert str(rel.contract_date) == "2026-11-01"
