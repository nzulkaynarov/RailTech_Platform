"""Comprehensive contract tests for ERP Integration API (CRM → ERP, CONTRACTS §2, M3-ERP-01).

Tests all 12 endpoints from packages/contracts/openapi/erp-integration.yaml:
1. POST /clients/handoff
2. PUT /contacts/{crm_contact_id}
3. GET /companies/{erp_company_id}/summary
4. GET /companies/{erp_company_id}/deals
5. GET /deals/{erp_deal_id}
6. GET /deals/{erp_deal_id}/documents
7. GET /documents/{erp_document_id}/link
8. GET /catalog/search
9. POST /users/provision
10. DELETE /users/{crm_user_id}/sessions
11. GET /ai-usage
12. GET /health
"""

import uuid
from decimal import Decimal

import pytest
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocumentStatus
from integration.models import CrmClientMapping, CrmContactMapping
from parties.models import Company, CompanyType, Contact
from rest_framework.test import APIClient

from accounts.models import CustomUser
from crm.models import Deal, DealStage, GeneratedDocument

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"


@pytest.fixture(autouse=True)
def setup_integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN, "secondary-rotation-token"]
    settings.CABINET_URL = "http://cabinet.localhost"
    settings.ERP_BASE_URL = "http://erp.localhost"
    settings.ERP_VERSION = "0.1.0"


@pytest.fixture
def auth_client():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


@pytest.fixture
def unauth_client():
    return APIClient()


# ─── 1. Authentication & Exception Format ──────────────────────────────────────


def test_missing_token_returns_401_unauthorized(unauth_client):
    resp = unauth_client.get("/api/integration/v1/health")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "UNAUTHORIZED"}


def test_invalid_token_returns_401_unauthorized():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer wrong-token")
    resp = client.get("/api/integration/v1/health")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "UNAUTHORIZED"}


def test_secondary_rotation_token_accepted():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer secondary-rotation-token")
    resp = client.get("/api/integration/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─── 2. Idempotency ────────────────────────────────────────────────────────────


def test_post_without_idempotency_key_fails(auth_client):
    payload = {"crm_client_id": 999}
    resp = auth_client.post("/api/integration/v1/clients/handoff", payload, format="json")
    assert resp.status_code == 422
    assert resp.json() == {"detail": "VALIDATION_ERROR"}


def test_post_with_invalid_uuid_idempotency_key_fails(auth_client):
    payload = {"crm_client_id": 999}
    resp = auth_client.post(
        "/api/integration/v1/clients/handoff",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "VALIDATION_ERROR"}


# ─── 3. Client Handoff (POST /clients/handoff) ─────────────────────────────────


def test_client_handoff_success_and_idempotency(auth_client):
    DealStage.objects.get_or_create(code="request", defaults={"name": "Заявка", "sort_order": 1})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})

    idempotency_key = str(uuid.uuid4())
    payload = {
        "crm_client_id": 1001,
        "crm_lead_id": 501,
        "company": {
            "name": "OOO Rail Client Test",
            "inn": "123456789",
            "segment": "enterprise",
            "language": "ru",
        },
        "contacts": [
            {
                "crm_contact_id": 2001,
                "name": "Иван Иванов",
                "phone": "+998901234567",
                "email": "ivan@client.uz",
                "telegram_user_id": 12345678,
                "language": "ru",
                "is_primary": True,
                "preferred_channel": "both",
            }
        ],
        "need": {
            "summary": "Поставка рельсов Р65 500 тонн",
            "product_interest": ["Рельс Р65", "Накладка 1Р65"],
            "attachments": [],
        },
        "owner": {
            "crm_user_id": 101,
            "name": "Менеджер Продаж",
        },
        "consent": {
            "given_at": timezone.now().isoformat(),
            "version": "v1.0",
        },
        "create_request": True,
        "invite": {
            "channels": ["email", "telegram"],
        },
    }

    # 1. Первый вызов — создание (201)
    resp = auth_client.post(
        "/api/integration/v1/clients/handoff",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "erp_company_id" in data
    assert data["erp_request_id"] is not None
    # FIX-14: в CRM уходит адрес кабинета без токена — рабочая ссылка входа есть только в письме клиента
    assert data["invite"]["cabinet_url"] == "http://cabinet.localhost"
    assert "/auth/magic/" not in resp.content.decode()
    assert data["invite"]["sent_via"] == ["email", "telegram"]

    company_id = data["erp_company_id"]
    company = Company.objects.get(id=company_id)
    assert company.name == "OOO Rail Client Test"
    assert company.inn == "123456789"
    assert company.crm_client_mapping.crm_client_id == 1001

    contact = Contact.objects.get(company=company, email="ivan@client.uz")
    assert contact.crm_contact_mapping.crm_contact_id == 2001
    assert contact.telegram_user_id == 12345678

    deal = Deal.objects.get(id=data["erp_request_id"])
    assert deal.company == company
    assert deal.contact == contact
    assert deal.portal_lines.count() == 2

    # 2. Повторный вызов с тем же Idempotency-Key и тем же телом — возврат закешированного ответа
    resp_cached = auth_client.post(
        "/api/integration/v1/clients/handoff",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp_cached.status_code == 201
    assert resp_cached.json() == data

    # 3. Повторный вызов с тем же Idempotency-Key, но другим телом — 409 IDEMPOTENCY_CONFLICT
    different_payload = dict(payload)
    different_payload["company"] = dict(payload["company"], name="Different Name")
    resp_conflict = auth_client.post(
        "/api/integration/v1/clients/handoff",
        different_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp_conflict.status_code == 409
    assert resp_conflict.json() == {"detail": "IDEMPOTENCY_CONFLICT"}

    # 4. Повторный вызов с новым Idempotency-Key, но существующим crm_client_id — 200 OK (бизнес-идемпотентность)
    new_idempotency_key = str(uuid.uuid4())
    resp_existing = auth_client.post(
        "/api/integration/v1/clients/handoff",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=new_idempotency_key,
    )
    assert resp_existing.status_code == 200
    assert resp_existing.json()["erp_company_id"] == company_id
    assert resp_existing.json()["erp_request_id"] == deal.id


# ─── 4. Contacts (PUT /contacts/{crm_contact_id}) ──────────────────────────────


def test_upsert_contact_updates_fields(auth_client):
    company = Company.objects.create(name="Contact Test Co", inn="999888777")
    contact = Contact.objects.create(
        company=company,
        name="Старое Имя",
        email="old@test.uz",
        phone="+998900000000",
        language="ru",
        is_primary=True,
    )
    CrmContactMapping.objects.create(crm_contact_id=5555, contact=contact)

    update_payload = {
        "crm_contact_id": 5555,
        "name": "Новое Имя",
        "phone": "+998911112233",
        "email": "new@test.uz",
        "telegram_user_id": 987654321,
        "language": "uz",
        "is_primary": True,
        "preferred_channel": "telegram",
    }

    resp = auth_client.put(
        "/api/integration/v1/contacts/5555",
        update_payload,
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Новое Имя"
    assert data["email"] == "new@test.uz"
    assert data["telegram_user_id"] == 987654321
    assert data["language"] == "uz"
    assert data["preferred_channel"] == "telegram"
    assert data["erp_contact_id"] == contact.id
    assert data["erp_company_id"] == company.id

    contact.refresh_from_db()
    assert contact.name == "Новое Имя"
    assert contact.telegram_user_id == 987654321


def test_upsert_contact_not_found(auth_client):
    update_payload = {
        "crm_contact_id": 999999,
        "name": "Неизвестный",
        "language": "ru",
        "is_primary": False,
        "preferred_channel": "email",
    }
    resp = auth_client.put("/api/integration/v1/contacts/999999", update_payload, format="json")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "NOT_FOUND"}


# ─── 5. Companies, Deals & Documents ──────────────────────────────────────────


def test_company_summary_and_deals(auth_client):
    company = Company.objects.create(name="Summary Test Co", inn="111222333")
    CrmClientMapping.objects.create(crm_client_id=7777, company=company)
    stage = DealStage.objects.create(code="quoting", name="Расчёт", sort_order=2)

    deal = Deal.objects.create(
        company=company,
        stage=stage,
        title="Сделка на поставку рельсов",
    )

    # 1. Summary
    resp_sum = auth_client.get(f"/api/integration/v1/companies/{company.id}/summary")
    assert resp_sum.status_code == 200
    s_data = resp_sum.json()
    assert s_data["erp_company_id"] == company.id
    assert s_data["crm_client_id"] == 7777
    assert s_data["name"] == "Summary Test Co"
    assert len(s_data["open_deals"]) == 1
    assert s_data["open_deals"][0]["erp_deal_id"] == deal.id
    assert s_data["open_deals"][0]["stage"] == "quoting"
    assert "receivables" in s_data

    # 2. Deals list
    resp_deals = auth_client.get(f"/api/integration/v1/companies/{company.id}/deals")
    assert resp_deals.status_code == 200
    deals_arr = resp_deals.json()
    assert len(deals_arr) == 1
    assert deals_arr[0]["erp_deal_id"] == deal.id

    # 3. Deal detail (client projection)
    resp_deal = auth_client.get(f"/api/integration/v1/deals/{deal.id}")
    assert resp_deal.status_code == 200
    d_data = resp_deal.json()
    assert d_data["erp_deal_id"] == deal.id
    assert d_data["erp_company_id"] == company.id
    assert d_data["crm_client_id"] == 7777
    assert "quotes" in d_data
    assert "contracts" in d_data
    assert "invoices" in d_data
    assert "deliveries" in d_data
    assert "acts" in d_data
    # Проверка изоляции бэк-офиса: никаких поставщиков и себестоимости
    assert "supplier" not in d_data
    assert "cost_price" not in d_data
    assert "margin" not in d_data


def test_deal_documents_and_signed_link(auth_client):
    company = Company.objects.create(name="Doc Co", inn="444555666")
    deal = Deal.objects.create(company=company, title="Doc Deal")

    kind_obj, _ = DocumentTemplateKind.objects.get_or_create(code="QUOTE", defaults={"name": "КП"})
    template_obj, _ = DocumentTemplate.objects.get_or_create(
        company=company,
        name="КП Шаблон",
        defaults={"kind": kind_obj},
    )
    status_obj, _ = GeneratedDocumentStatus.objects.get_or_create(code="GENERATED", defaults={"name": "Сформирован"})
    doc = GeneratedDocument.objects.create(
        company=company,
        deal=deal,
        template=template_obj,
        number="КП-00123",
        title="Коммерческое предложение",
        status=status_obj,
    )

    # 1. List documents
    resp_docs = auth_client.get(f"/api/integration/v1/deals/{deal.id}/documents")
    assert resp_docs.status_code == 200
    docs = resp_docs.json()
    assert len(docs) == 1
    assert docs[0]["erp_document_id"] == doc.id
    assert docs[0]["number"] == "КП-00123"

    # 2. Signed link with X-CRM-Context header
    resp_link = auth_client.get(
        f"/api/integration/v1/documents/{doc.id}/link",
        HTTP_X_CRM_CONTEXT='{"crm_client_id": 7777, "channel": "bot"}',
    )
    assert resp_link.status_code == 200
    link_data = resp_link.json()
    assert "url" in link_data
    assert "expires_at" in link_data
    assert link_data["content_type"] == "application/pdf"
    assert "КП-00123" in link_data["file_name"]


# ─── 6. Catalog Search ────────────────────────────────────────────────────────


def test_catalog_search_lead_and_client_modes(auth_client):
    from catalog.models import Category, Product, ProductStatus
    from master_data.models import Currency, UnitOfMeasure

    cat, _ = Category.objects.get_or_create(name="Рельсы")
    uom, _ = UnitOfMeasure.objects.get_or_create(code="T", defaults={"name": "т"})
    curr, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    st_pub, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})

    p = Product.objects.create(
        name="Рельс Р65 ГОСТ Р 51685-2013",
        category=cat,
        uom=uom,
        status=st_pub,
        list_price=Decimal("12500000.00"),
        list_price_currency=curr,
    )

    # 1. Lead mode: без цен и наличия
    resp_lead = auth_client.get("/api/integration/v1/catalog/search?q=Рельс&mode=lead")
    assert resp_lead.status_code == 200
    items_lead = resp_lead.json()
    assert len(items_lead) >= 1
    item = next(i for i in items_lead if i["erp_product_id"] == p.id)
    assert item["name"] == "Рельс Р65 ГОСТ Р 51685-2013"
    assert item["unit"] == "т"
    assert "price" not in item or item["price"] is None
    assert "availability" not in item or item["availability"] is None

    # 2. Client mode: с ценой и наличием
    resp_client = auth_client.get("/api/integration/v1/catalog/search?q=Рельс&mode=client")
    assert resp_client.status_code == 200
    items_client = resp_client.json()
    assert len(items_client) >= 1
    c_item = next(i for i in items_client if i["erp_product_id"] == p.id)
    assert "availability" in c_item

    # 3. Валидация: без query или mode -> 422
    resp_inv = auth_client.get("/api/integration/v1/catalog/search?q=")
    assert resp_inv.status_code == 422
    assert resp_inv.json() == {"detail": "VALIDATION_ERROR"}


# ─── 7. User Provisioning & Session Revocation ──────────────────────────────────


def test_user_provisioning_admin_and_backoffice(auth_client):
    # 1. Provision Admin
    admin_payload = {
        "crm_user_id": 8801,
        "email": "crm_admin@railtech.uz",
        "name": "Главный Администратор",
        "role": "admin",
        "permissions": ["quote.build", "contract.manage", "finance.invoice"],
        "is_active": True,
    }
    resp_admin = auth_client.post(
        "/api/integration/v1/users/provision",
        admin_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp_admin.status_code == 201
    assert resp_admin.json()["crm_user_id"] == 8801
    admin_user = CustomUser.objects.get(email="crm_admin@railtech.uz")
    assert admin_user.is_superuser is True
    assert admin_user.is_staff is True

    # 2. Provision Backoffice User
    bo_payload = {
        "crm_user_id": 8802,
        "email": "bo_manager@railtech.uz",
        "name": "Менеджер Бэк-офиса",
        "role": "backoffice",
        "permissions": ["quote.build", "quote.send"],
        "is_active": True,
    }
    resp_bo = auth_client.post(
        "/api/integration/v1/users/provision",
        bo_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp_bo.status_code == 201
    bo_user = CustomUser.objects.get(email="bo_manager@railtech.uz")
    assert bo_user.is_superuser is False
    assert bo_user.is_staff is False

    # 3. Revoke Sessions
    resp_rev = auth_client.delete("/api/integration/v1/users/8802/sessions")
    assert resp_rev.status_code == 204

    # 4. Revoke Sessions for unknown user -> 404
    resp_rev_404 = auth_client.delete("/api/integration/v1/users/999999/sessions")
    assert resp_rev_404.status_code == 404
    assert resp_rev_404.json() == {"detail": "NOT_FOUND"}


def _provision(auth_client, crm_user_id, email, role="backoffice"):
    return auth_client.post(
        "/api/integration/v1/users/provision",
        {
            "crm_user_id": crm_user_id,
            "email": email,
            "name": "Сотрудник",
            "role": role,
            "permissions": ["quote.build"],
            "is_active": True,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )


def test_provision_email_of_unmapped_erp_user_is_conflict_and_user_untouched(auth_client):
    """I-17: e-mail занят пользователем ERP без сопоставления → 409, пользователь не переписывается."""
    from integration.models import CrmUserMapping

    victim = CustomUser.objects.create(
        username="victim@railtech.uz", email="victim@railtech.uz", first_name="Жертва", is_superuser=False
    )

    resp = _provision(auth_client, 9001, "Victim@railtech.uz", role="admin")

    assert resp.status_code == 409
    assert resp.json() == {"detail": "EMAIL_CONFLICT"}
    victim.refresh_from_db()
    assert victim.is_superuser is False and victim.is_staff is False
    assert victim.first_name == "Жертва"
    assert not CrmUserMapping.objects.filter(crm_user_id=9001).exists()


def test_provision_email_of_user_with_other_crm_id_is_conflict(auth_client):
    from integration.models import CrmUserMapping

    assert _provision(auth_client, 9101, "owner@railtech.uz", role="admin").status_code == 201

    resp = _provision(auth_client, 9102, "owner@railtech.uz", role="backoffice")

    assert resp.status_code == 409
    assert resp.json() == {"detail": "EMAIL_CONFLICT"}
    owner = CustomUser.objects.get(email="owner@railtech.uz")
    assert owner.is_superuser is True
    assert CrmUserMapping.objects.get(user=owner).crm_user_id == 9101
    assert not CrmUserMapping.objects.filter(crm_user_id=9102).exists()


def test_provision_existing_mapping_with_new_email_taken_by_other_is_conflict(auth_client):
    assert _provision(auth_client, 9201, "first@railtech.uz").status_code == 201
    assert _provision(auth_client, 9202, "second@railtech.uz").status_code == 201

    resp = _provision(auth_client, 9201, "second@railtech.uz")

    assert resp.status_code == 409
    assert CustomUser.objects.get(email="first@railtech.uz").pk != CustomUser.objects.get(email="second@railtech.uz").pk


def test_provision_same_crm_user_is_updated_not_conflict(auth_client):
    assert _provision(auth_client, 9301, "same@railtech.uz", role="backoffice").status_code == 201

    resp = _provision(auth_client, 9301, "same@railtech.uz", role="admin")

    assert resp.status_code == 200
    assert CustomUser.objects.get(email="same@railtech.uz").is_superuser is True


# ─── 8. AI Usage & Health ──────────────────────────────────────────────────────


def test_ai_usage_and_health(auth_client):
    from ai.models import AICall

    AICall.objects.create(
        feature="match",
        model_alias="claude-3-5-sonnet",
        prompt_name="catalog_match",
        prompt_version="abc1234",
        status="ok",
        input_tokens=150,
        output_tokens=50,
        cost_usd=Decimal("0.001200"),
    )

    today = timezone.localdate().isoformat()
    resp_ai = auth_client.get(f"/api/integration/v1/ai-usage?date_from={today}&date_to={today}")
    assert resp_ai.status_code == 200
    ai_rows = resp_ai.json()
    assert len(ai_rows) >= 1
    assert ai_rows[0]["system"] == "erp"
    assert ai_rows[0]["feature"] == "match"
    assert "cost_usd" in ai_rows[0]

    # Health check
    resp_health = auth_client.get("/api/integration/v1/health")
    assert resp_health.status_code == 200
    h_data = resp_health.json()
    assert h_data["status"] == "ok"
    assert h_data["version"] == "0.1.0"
    assert h_data["migrations_applied"] is True
    assert h_data["queue_alive"] is True
    assert "checked_at" in h_data
