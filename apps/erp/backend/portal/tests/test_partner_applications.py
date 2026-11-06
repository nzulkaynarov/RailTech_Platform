"""Tests for partner application endpoints (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD-1).

Covers:
  - Public onboarding funnel: POST /api/portal/v1/auth/partner-application
    - Success (201) with Honeypot empty, consent=True
    - Consent required (400 CONSENT_REQUIRED)
    - Honeypot trap (400 HONEYPOT_DETECTED)
    - Validation error (422 VALIDATION_ERROR) on invalid email, missing required fields
  - In-cabinet client partner application:
    - GET /api/portal/v1/company/partner-application (200: already_partner, has_application, application)
    - POST /api/portal/v1/company/partner-application (201: creates application linked to company & applicant contact)
    - Conflict (409 APPLICATION_EXISTS) on duplicate pending application
    - Conflict (409 ALREADY_PARTNER) when company already has active PARTNER role
    - Permission denied (403 FORBIDDEN) when contact cannot act (can_act=False)
    - Validation error (422 VALIDATION_ERROR) on empty/short categories_description
"""

import pytest
from parties.models import (
    CompanyRelationship,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    RelationshipRole,
    RelationshipStatus,
)

pytestmark = pytest.mark.django_db

PUBLIC_URL = "/api/portal/v1/auth/partner-application"
COMPANY_URL = "/api/portal/v1/company/partner-application"


def test_public_partner_application_success(anon_portal_client):
    """Публичная подача заявки поставщиком: 201 Created, создаётся PartnerApplication со статусом submitted."""
    payload = {
        "company_name": "ООО 'Железнодорожные Детали'",
        "inn": "123456789",
        "kind": "supplier",
        "categories_description": "Поставка стрелочных переводов и рельсовых скреплений",
        "contact_name": "Иван Смирнов",
        "email": "ivan@rzd-details.uz",
        "phone": "+998901112233",
        "language": "ru",
        "consent": True,
        "website": "",  # honeypot empty
    }
    resp = anon_portal_client.post(PUBLIC_URL, payload, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "submitted"

    app = PartnerApplication.objects.get(pk=data["id"])
    assert app.source == PartnerApplicationSource.PUBLIC
    assert app.company_name == "ООО 'Железнодорожные Детали'"
    assert app.inn == "123456789"
    assert app.kind == "supplier"
    assert app.status == PartnerApplicationStatus.SUBMITTED
    assert app.email == "ivan@rzd-details.uz"
    assert app.consent is True


def test_public_partner_application_consent_required(anon_portal_client):
    """Без явного согласия (consent=False) возвращается 400 CONSENT_REQUIRED."""
    payload = {
        "company_name": "ООО Тест",
        "categories_description": "Поставка подшипников для подвижного состава",
        "contact_name": "Петр",
        "email": "petr@example.uz",
        "consent": False,
        "website": "",
    }
    resp = anon_portal_client.post(PUBLIC_URL, payload, format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CONSENT_REQUIRED"
    assert not PartnerApplication.objects.exists()


def test_public_partner_application_honeypot_detected(anon_portal_client):
    """Если бот заполнил скрытое поле website, возвращается 400 HONEYPOT_DETECTED."""
    payload = {
        "company_name": "Bot Corp",
        "categories_description": "Spam and automated products description",
        "contact_name": "Spambot",
        "email": "spam@example.uz",
        "consent": True,
        "website": "https://spamsite.com",  # honeypot triggered
    }
    resp = anon_portal_client.post(PUBLIC_URL, payload, format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "HONEYPOT_DETECTED"
    assert not PartnerApplication.objects.exists()


def test_public_partner_application_validation_error(anon_portal_client):
    """Невалидный email или короткое описание категорий возвращает 422 VALIDATION_ERROR."""
    payload = {
        "company_name": "ООО Тест",
        "categories_description": "Коротко",  # < 10 chars
        "contact_name": "Петр",
        "email": "not-an-email",
        "consent": True,
        "website": "",
    }
    resp = anon_portal_client.post(PUBLIC_URL, payload, format="json")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "VALIDATION_ERROR"
    assert not PartnerApplication.objects.exists()


def test_company_partner_application_status_empty(portal_client):
    """Клиент без заявки: GET возвращает already_partner=false, has_application=false, application=null."""
    resp = portal_client.get(COMPANY_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["already_partner"] is False
    assert data["has_application"] is False
    assert data["application"] is None


def test_company_partner_application_unauthorized(anon_portal_client):
    """Неавторизованный запрос к /company/partner-application возвращает 401."""
    resp = anon_portal_client.get(COMPANY_URL)
    assert resp.status_code == 401


def test_company_partner_application_create_and_status(portal_client, client_company, client_contact):
    """Действующий клиент с can_act=True успешно подаёт заявку через кабинет: 201 Created."""
    payload = {
        "kind": "manufacturer",
        "categories_description": "Собственное производство высоковольтных изоляторов",
    }
    resp = portal_client.post(COMPANY_URL, payload, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["company_name"] == client_company.name
    assert data["kind"] == "manufacturer"
    assert data["status"] == "submitted"

    # Проверяем, что в базе запись привязана к клиенту
    app = PartnerApplication.objects.get(company=client_company)
    assert app.source == PartnerApplicationSource.CLIENT_CABINET
    assert app.applicant_contact == client_contact
    assert app.company_name == client_company.name
    assert app.inn == (client_company.inn or "")

    # Повторный GET возвращает has_application=true и детали заявки
    status_resp = portal_client.get(COMPANY_URL)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["already_partner"] is False
    assert status_data["has_application"] is True
    assert status_data["application"]["id"] == app.id
    assert status_data["application"]["status"] == "submitted"


def test_company_partner_application_duplicate_conflict(portal_client, client_company, client_contact):
    """Если заявка уже находится на рассмотрении, повторная подача возвращает 409 APPLICATION_EXISTS."""
    PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        applicant_contact=client_contact,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка запасных частей для электровозов",
        status=PartnerApplicationStatus.SUBMITTED,
        consent=True,
    )
    resp = portal_client.post(
        COMPANY_URL,
        {"kind": "supplier", "categories_description": "Вторая попытка подачи заявки"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "APPLICATION_EXISTS"


def test_company_partner_application_already_partner_conflict(portal_client, client_company):
    """Если у компании уже есть активная роль PARTNER, возвращается 409 ALREADY_PARTNER."""
    CompanyRelationship.objects.create(
        company=client_company,
        role=RelationshipRole.PARTNER,
        status=RelationshipStatus.ACTIVE,
    )
    resp = portal_client.post(
        COMPANY_URL,
        {"kind": "manufacturer", "categories_description": "Попытка подачи при имеющейся роли партнера"},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "ALREADY_PARTNER"

    # GET также показывает already_partner=true
    status_resp = portal_client.get(COMPANY_URL)
    assert status_resp.status_code == 200
    assert status_resp.json()["already_partner"] is True


def test_company_partner_application_readonly_forbidden(readonly_portal_client):
    """Контакт без права подписи (can_act=False) получает 403 FORBIDDEN при попытке подать заявку."""
    payload = {
        "kind": "supplier",
        "categories_description": "Попытка подачи заявки пользователем без прав подписи",
    }
    resp = readonly_portal_client.post(COMPANY_URL, payload, format="json")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "FORBIDDEN"


def test_company_partner_application_contract_pdf_success(portal_client, client_company, client_contact):
    """Кандидат может скачать проект договора (200 application/pdf)."""
    from django.core.files.base import ContentFile
    from portal.services.partner_contract import render_partner_contract_pdf

    app = PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        applicant_contact=client_contact,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка стрелочных переводов",
        status=PartnerApplicationStatus.CONTRACT_SENT,
        contract_number="PRT-TEST-2026-001",
        consent=True,
    )
    pdf_bytes = render_partner_contract_pdf(app, draft=True)
    app.contract_pdf.save("test_draft.pdf", ContentFile(pdf_bytes), save=True)

    resp = portal_client.get(f"{COMPANY_URL}/contract-pdf")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert "PRT-TEST-2026-001" in resp["Content-Disposition"]
    assert len(resp.content) > 0


def test_company_partner_application_contract_pdf_not_found(portal_client):
    """Если у компании нет заявки, возвращается 404 NOT_FOUND."""
    resp = portal_client.get(f"{COMPANY_URL}/contract-pdf")
    assert resp.status_code == 404


def test_company_partner_application_agree_success(portal_client, client_company, client_contact):
    """Кандидат согласовывает проект договора: статус становится candidate_agreed."""
    app = PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        applicant_contact=client_contact,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка стрелочных переводов",
        status=PartnerApplicationStatus.CONTRACT_SENT,
        contract_number="PRT-TEST-2026-002",
        consent=True,
    )

    resp = portal_client.post(
        f"{COMPANY_URL}/agree",
        {"notes": "Согласовано юристом, замечаний нет"},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "candidate_agreed"
    assert data["candidate_notes"] == "Согласовано юристом, замечаний нет"
    assert data["candidate_agreed_at"] is not None

    app.refresh_from_db()
    assert app.status == PartnerApplicationStatus.CANDIDATE_AGREED
    assert app.candidate_notes == "Согласовано юристом, замечаний нет"
    assert app.candidate_agreed_at is not None
    assert app.contract_pdf


def test_company_partner_application_agree_invalid_status(portal_client, client_company, client_contact):
    """Согласование отклоняется (400), если статус не contract_sent."""
    PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        applicant_contact=client_contact,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка стрелочных переводов",
        status=PartnerApplicationStatus.SUBMITTED,
        consent=True,
    )

    resp = portal_client.post(f"{COMPANY_URL}/agree", {"notes": ""}, format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "NOT_IN_CONTRACT_SENT_STATUS"


def test_company_partner_application_agree_readonly_forbidden(readonly_portal_client, client_company):
    """Контакт без права подписи (can_act=False) получает 403 FORBIDDEN при попытке согласовать договор."""
    PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка стрелочных переводов",
        status=PartnerApplicationStatus.CONTRACT_SENT,
        consent=True,
    )

    resp = readonly_portal_client.post(f"{COMPANY_URL}/agree", {"notes": ""}, format="json")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "FORBIDDEN"
