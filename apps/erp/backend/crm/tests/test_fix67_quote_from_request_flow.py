"""FIX-67: весь путь «заявка из CRM без строк → КП вручную → клиенту» на чистой базе (справочники — из миграций).

Прод показал, что из заявки нельзя сделать КП вообще. Сценарий владельца целиком, через HTTP и без подмен
доменных сервисов:

1. передача клиента из CRM (`POST /api/integration/v1/clients/handoff`) с потребностью словами — без перечня позиций;
2. сотрудник бэк-офиса открывает заявку: строк нет, текст виден, «Взять в работу и подготовить» отказывает
   (`NO_REQUEST_LINES`) и НЕ меняет заявку;
3. «Взять в работу» → стадии → «Создать КП» (пустой черновик) → строка свободным текстом;
4. товар заводится через форму каталога (без выбора владельца) и добавляется строкой КП;
5. КП уходит на согласование (единственный согласующий — сам автор, согласуется автоматически) и клиенту.

Платных вызовов нет: ИИ выключен.
"""

import uuid

import pytest
from django.core import mail
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.constants import Permission
from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product
from crm.models import ActivityLog, Deal, Quote, QuoteItem

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-service-token"  # conftest._seam_secrets
NEED = "Нужны рельсы Р65 около 500 тонн и накладки к ним, поставка в Ташкент до конца ноября"


@pytest.fixture(autouse=True)
def _no_paid_ai(settings):
    settings.AI_IMPORT_ENABLED = False
    settings.CABINET_URL = "http://cabinet.localhost"


@pytest.fixture
def own_company(db):
    """Своя компания и её сотрудник со всеми правами бэк-офиса (как «Руководитель»)."""
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент", "sort_order": 10})
    company = Company.objects.create(name="FIX67 Своя компания", inn="967000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    role = CompanyRole.objects.create(
        company=company, name="FIX67 Руководитель", permissions=[p.value for p in Permission]
    )
    user = CustomUser.objects.create_user(email="fix67-staff@example.test", username="fix67-staff", password="pw")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0],
        company_roles=[role],
        is_active=True,
        is_primary=True,
    )
    return {"company": company, "user": user}


@pytest.fixture
def staff(own_company):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(own_company['user']).access_token}")
    return client


def _handoff() -> dict:
    """Передача клиента из CRM: потребность — словами, перечня позиций нет."""
    crm = APIClient()
    crm.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    response = crm.post(
        "/api/integration/v1/clients/handoff",
        {
            "crm_client_id": 6701,
            "crm_lead_id": 6601,
            "company": {"name": "FIX67 ООО Клиент", "inn": "967000777", "segment": "enterprise", "language": "ru"},
            "contacts": [
                {
                    "crm_contact_id": 67011,
                    "name": "Иван Клиентов",
                    "phone": "+998901234567",
                    "email": "fix67-client@example.test",
                    "language": "ru",
                    "is_primary": True,
                    "preferred_channel": "email",
                }
            ],
            "need": {"summary": NEED, "product_interest": [], "attachments": []},
            "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
            "consent": {"given_at": "2026-10-01T09:30:00+05:00", "version": "2026-09"},
            "create_request": True,
            "invite": {"channels": ["email"]},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.content
    return response.json()


def test_request_from_crm_without_lines_becomes_a_quote_sent_to_the_client(own_company, staff):
    handed_off = _handoff()
    deal = Deal.objects.get(pk=handed_off["erp_request_id"])
    detail_url = f"/api/v1/crm/deals/{deal.pk}/"

    # 2. Заявка словами: строк нет, текст виден, «подготовить» отказывает и ничего не меняет.
    detail = staff.get(detail_url).json()
    assert detail["request_lines_count"] == 0
    assert detail["request_text"] == NEED
    journal_before = ActivityLog.objects.filter(deal=deal).count()
    refused = staff.post(f"{detail_url}take-and-prepare/", {}, format="json")
    assert refused.status_code == 400 and refused.json() == {"detail": "NO_REQUEST_LINES"}
    deal.refresh_from_db()
    assert deal.assigned_to_id is None and deal.stage.code == "DRAFT"
    assert ActivityLog.objects.filter(deal=deal).count() == journal_before

    # 3. «Взять в работу» → к подбору → к расчёту.
    assert staff.post(f"{detail_url}claim/", {}, format="json").status_code == 200
    for stage in ("SOURCING", "CALCULATING"):
        response = staff.post(f"{detail_url}change-stage/", {"stage_code": stage}, format="json")
        assert response.status_code == 200, response.content

    # «Создать КП»: пустой черновик, без строк (строк у заявки нет).
    created = staff.post("/api/v1/crm/quotes/", {"deal": deal.pk}, format="json")
    assert created.status_code == 201, created.content
    quote = Quote.objects.get(pk=created.json()["id"])
    assert quote.status.code == "DRAFT" and quote.items.count() == 0

    # Строка свободным текстом.
    free_line = staff.post(
        "/api/v1/crm/quote-items/",
        {
            "quote": quote.pk,
            "imported_raw_name": "FIX67 Накладка 4-дырная",
            "quantity": 40,
            "unit": "шт.",
            "frozen_base_price": "1000.00",
            "frozen_currency": "UZS",
            "margin_percent": "30.00",
        },
        format="json",
    )
    assert free_line.status_code == 201, free_line.content

    # 4. Товар через форму каталога: владельца форма не называет — карточка своей компании.
    product_response = staff.post(
        "/api/v1/catalog/products/", {"name": "FIX67 Рельс Р65 (форма)", "unit": ""}, format="json"
    )
    assert product_response.status_code == 201, product_response.content
    product = Product.objects.get(pk=product_response.json()["id"])
    assert product.owner_company_id == own_company["company"].pk
    product_line = staff.post(
        "/api/v1/crm/quote-items/",
        {
            "quote": quote.pk,
            "product": product.pk,
            "quantity": 500,
            "unit": "т",
            "frozen_base_price": "9000.00",
            "frozen_currency": "UZS",
            "margin_percent": "30.00",
        },
        format="json",
    )
    assert product_line.status_code == 201, product_line.content
    assert QuoteItem.objects.filter(quote=quote).count() == 2

    # 5. На согласование (визировать некому, кроме автора) → директору в EDS (EDS-03) → одобрено → клиенту.
    submitted = staff.post(f"/api/v1/crm/quotes/{quote.pk}/submit-for-review/", {}, format="json")
    assert submitted.status_code == 200, submitted.content
    quote.refresh_from_db()
    assert quote.status.code == "PENDING_APPROVAL", f"ожидали КП у директора в EDS, статус {quote.status.code}"
    from integration.tests.eds_support import approve_in_eds

    assert approve_in_eds(quote) == "applied"
    quote.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND"

    mail.outbox.clear()
    sent = staff.post(f"/api/v1/crm/quotes/{quote.pk}/send-to-client/", {}, format="json")
    assert sent.status_code == 200, sent.content
    quote.refresh_from_db()
    assert quote.status.code == "SENT" and quote.frozen_at is not None and quote.public_access_token
    deal.refresh_from_db()
    assert deal.stage.code == "QUOTE_SENT"
