"""Tests for ERP MCP Server (CRM Agent Integration, CONTRACTS §5, M3-ERP-03).

Тестирует эндпоинт /mcp/erp и все 7 инструментов:
1. Валидация подписи HMAC-SHA256 заголовка X-Agent-Context
2. Протокол JSON-RPC 2.0 (initialize, notifications/initialized, ping, tools/list)
3. Защита режимов (prospect vs customer)
4. Cross-tenant изоляция (чужой клиент — пустой результат)
5. Все 7 инструментов:
   - list_client_deals
   - get_deal_status
   - get_delivery_status
   - list_client_documents
   - get_document_link
   - search_catalog (prospect без цен/наличия, customer с ценами)
   - create_request (создание заявки Deal + PortalRequestLine, вебхук request.created)
"""

import json
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocumentStatus
from integration.mcp.context import (
    AgentContextError,
    _b64encode,
    _sign,
    issue_agent_context,
    mark_used,
    verify_agent_context,
)
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from parties.models import Company, CompanyType, Contact
from portal.models import PortalRequestLine
from rest_framework import status
from rest_framework.test import APIClient
from sales.models import Fulfillment, FulfillmentStatus, Quote, QuoteStatus

from catalog.models import Category, Product, ProductStatus
from catalog.published import CATALOG_ITEM_KEYS
from crm.models import Deal, DealStage, GeneratedDocument
from master_data.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

MCP_SECRET = "test-erp-mcp-secret-key"


@pytest.fixture(autouse=True)
def setup_mcp_settings(settings):
    settings.ERP_MCP_CONTEXT_KEY = MCP_SECRET
    settings.ERP_BASE_URL = "http://erp.localhost"
    settings.ERP_VERSION = "0.1.0"
    settings.ERP_WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def test_data():
    """Создает две изолированные компании с контактами, сделками и документами."""
    client_type = CompanyType.objects.filter(code="CLIENT").first()
    if not client_type:
        client_type = CompanyType.objects.create(code="CLIENT", name="Клиент")

    # Компания А
    comp_a = Company.objects.create(name="ООО Альфа", inn="123456789", is_registered=True)
    comp_a.types.add(client_type)
    contact_a = Contact.objects.create(
        company=comp_a,
        name="Алиса",
        phone="+998901111111",
        email="alisa@alfa.uz",
        is_primary=True,
    )

    # Компания Б
    comp_b = Company.objects.create(name="ООО Бета", inn="987654321", is_registered=True)
    comp_b.types.add(client_type)
    contact_b = Contact.objects.create(
        company=comp_b,
        name="Борис",
        phone="+998902222222",
        email="boris@beta.uz",
        is_primary=True,
    )

    stage_req = DealStage.objects.filter(code="request").first()
    if not stage_req:
        stage_req = DealStage.objects.create(code="request", name="Запрос")

    stage_won = DealStage.objects.filter(code="won").first()
    if not stage_won:
        stage_won = DealStage.objects.create(code="won", name="Выиграна")

    # Сделка А
    deal_a = Deal.objects.create(
        company=comp_a,
        contact=contact_a,
        stage=stage_req,
        title="Сделка Альфа 1",
    )

    # Поставка для сделки А
    status_in_transit, _ = FulfillmentStatus.objects.get_or_create(code="in_transit", defaults={"name": "В пути"})
    fulf_a = Fulfillment.objects.create(
        deal=deal_a,
        status=status_in_transit,
        expected_delivery_date=timezone.now().date() + timezone.timedelta(days=5),
        tracking_number="TRK-12345",
    )

    # Сделка Б
    deal_b = Deal.objects.create(
        company=comp_b,
        contact=contact_b,
        stage=stage_won,
        title="Сделка Бета 1",
    )

    # Документы
    kind_contract = DocumentTemplateKind.objects.filter(code="contract").first()
    if not kind_contract:
        kind_contract = DocumentTemplateKind.objects.create(code="contract", name="Договор")

    tpl_contract = DocumentTemplate.objects.create(
        name="Типовой договор",
        kind=kind_contract,
    )
    status_issued = GeneratedDocumentStatus.objects.filter(code="issued").first()
    if not status_issued:
        status_issued = GeneratedDocumentStatus.objects.create(code="issued", name="Выставлен")

    doc_a = GeneratedDocument.objects.create(
        company=comp_a,
        deal=deal_a,
        template=tpl_contract,
        status=status_issued,
        number="CTR-ALFA-01",
        title="Договор поставки Альфа",
    )
    doc_b = GeneratedDocument.objects.create(
        company=comp_b,
        deal=deal_b,
        template=tpl_contract,
        status=status_issued,
        number="CTR-BETA-01",
        title="Договор поставки Бета",
    )

    # Маппинг CRM <-> ERP
    CrmClientMapping.objects.create(crm_client_id=10, company=comp_a)
    CrmClientMapping.objects.create(crm_client_id=20, company=comp_b)

    # Каталог
    cat = Category.objects.create(name="Рельсы и стрелочные переводы")
    uom, _ = UnitOfMeasure.objects.get_or_create(code="t", defaults={"name": "т"})
    curr, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    st_pub, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})

    prod = Product.objects.create(
        sku="RAIL-P65",
        name="Рельс Р-65 ГОСТ 51685-2000",
        description="Рельс железнодорожный термоупрочненный",
        category=cat,
        uom=uom,
        status=st_pub,
        list_price=Decimal("12500000.00"),
        list_price_currency=curr,
        price_visibility="cabinet",
    )

    return {
        "comp_a": comp_a,
        "comp_b": comp_b,
        "contact_a": contact_a,
        "deal_a": deal_a,
        "fulf_a": fulf_a,
        "deal_b": deal_b,
        "doc_a": doc_a,
        "doc_b": doc_b,
        "prod": prod,
    }


def make_context_token(
    crm_client_id: int = 10,
    erp_company_id: int | None = 1,
    mode: str = "customer",
    language: str = "ru",
    ttl_s: int = 60,
    secret: str = MCP_SECRET,
    now: float | None = None,
    jti: str | None = None,
) -> str:
    return issue_agent_context(
        key=secret,
        crm_client_id=crm_client_id,
        erp_company_id=erp_company_id,
        mode=mode,
        language=language,
        ttl_s=ttl_s,
        now=now,
        jti=jti,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Валидация подписи X-Agent-Context
# ─────────────────────────────────────────────────────────────────────────────


def test_context_issue_and_verify():
    token = make_context_token(crm_client_id=42, erp_company_id=7, mode="customer", language="uz")
    ctx = verify_agent_context(token, MCP_SECRET)
    assert ctx.crm_client_id == 42
    assert ctx.erp_company_id == 7
    assert ctx.mode == "customer"
    assert ctx.language == "uz"


def test_context_prospect_mode():
    token = make_context_token(crm_client_id=10, erp_company_id=None, mode="prospect")
    ctx = verify_agent_context(token, MCP_SECRET)
    assert ctx.crm_client_id == 10
    assert ctx.erp_company_id is None
    assert ctx.mode == "prospect"


def test_context_invalid_signature():
    token = make_context_token()
    with pytest.raises(AgentContextError, match="invalid signature"):
        verify_agent_context(token, "wrong-secret-key")


def test_context_missing_or_malformed():
    with pytest.raises(AgentContextError, match="missing agent context"):
        verify_agent_context(None, MCP_SECRET)
    with pytest.raises(AgentContextError, match="malformed agent context"):
        verify_agent_context("not-a-valid-token", MCP_SECRET)


def test_context_expired():
    t_past = time.time() - 100
    token = make_context_token(ttl_s=10, now=t_past)
    with pytest.raises(AgentContextError, match="expired agent context"):
        verify_agent_context(token, MCP_SECRET)


# ─────────────────────────────────────────────────────────────────────────────
# 2. HTTP Аутентификация на /mcp/erp
# ─────────────────────────────────────────────────────────────────────────────


def test_http_endpoint_rejects_missing_context(client):
    resp = client.get("/mcp/erp")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == {"detail": "INVALID_AGENT_CONTEXT"}

    resp = client.post("/mcp/erp", data={"jsonrpc": "2.0", "id": 1, "method": "ping"}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == {"detail": "INVALID_AGENT_CONTEXT"}


def test_http_endpoint_rejects_invalid_signature(client):
    token = make_context_token(secret="wrong-key")
    resp = client.get("/mcp/erp", HTTP_X_AGENT_CONTEXT=token)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_http_endpoint_accepts_valid_context(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    resp = client.get("/mcp/erp", HTTP_X_AGENT_CONTEXT=token)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["server"] == "erp-mcp"
    assert resp.data["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Протокол JSON-RPC: initialize, notifications, ping, tools/list
# ─────────────────────────────────────────────────────────────────────────────


def test_jsonrpc_initialize(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "crm-agent", "version": "1.0"},
        },
    }
    resp = client.post("/mcp/erp", data=payload, format="json", HTTP_X_AGENT_CONTEXT=token)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["id"] == 1
    assert resp.data["result"]["protocolVersion"] == "2024-11-05"
    assert resp.data["result"]["serverInfo"]["name"] == "erp-mcp"


def test_jsonrpc_notifications_and_ping(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)

    # notification (no id)
    resp = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "method": "notifications/initialized"},
        format="json",
        HTTP_X_AGENT_CONTEXT=token,
    )
    assert resp.status_code == status.HTTP_200_OK

    # ping
    resp = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        format="json",
        HTTP_X_AGENT_CONTEXT=token,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["result"] == {}


def test_jsonrpc_tools_list_matches_contract(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    resp = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        format="json",
        HTTP_X_AGENT_CONTEXT=token,
    )
    assert resp.status_code == status.HTTP_200_OK
    tools = resp.data["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    expected = [
        "list_client_deals",
        "get_deal_status",
        "get_delivery_status",
        "list_client_documents",
        "get_document_link",
        "search_catalog",
        "create_request",
    ]
    assert tool_names == expected

    # Проверка схемы: ни один инструмент не должен содержать client_id / company_id в inputSchema
    for t in tools:
        props = t["inputSchema"].get("properties", {})
        for prop in props:
            assert prop not in ("crm_client_id", "erp_company_id", "client_id", "company_id")


def test_jsonrpc_unknown_method(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    resp = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 99, "method": "unknown_function"},
        format="json",
        HTTP_X_AGENT_CONTEXT=token,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["error"]["code"] == -32601


# ─────────────────────────────────────────────────────────────────────────────
# 4. Инструменты: list_client_deals & get_deal_status (Cross-tenant изоляция)
# ─────────────────────────────────────────────────────────────────────────────


def test_list_client_deals_cross_tenant_isolation(client, test_data):
    # Агент компании А запрашивает сделки
    ctx_a = dict(erp_company_id=test_data["comp_a"].id, mode="customer")
    resp_a = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_client_deals"}},
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp_a.status_code == status.HTTP_200_OK
    res_a = resp_a.data["result"]
    assert not res_a["isError"]
    deals_a = res_a["structuredContent"]["result"]
    assert len(deals_a) == 1
    assert deals_a[0]["erp_deal_id"] == test_data["deal_a"].id
    assert deals_a[0]["number"] == f"D-{test_data['deal_a'].id}"

    # В режиме prospect инструмент недоступен
    ctx_prospect = dict(erp_company_id=None, mode="prospect")
    resp_p = client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_client_deals"}},
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_prospect),
    )
    assert resp_p.status_code == status.HTTP_200_OK
    assert resp_p.data["result"]["isError"] is True


def test_get_deal_status_cross_tenant_isolation(client, test_data):
    ctx_a = dict(erp_company_id=test_data["comp_a"].id, mode="customer")

    # Своя сделка -> данные есть
    resp = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_deal_status", "arguments": {"erp_deal_id": test_data["deal_a"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp.status_code == status.HTTP_200_OK
    res = resp.data["result"]
    assert not res["isError"]
    deal_data = res["structuredContent"]["result"]
    assert deal_data["erp_deal_id"] == test_data["deal_a"].id
    assert deal_data["title"] == "Сделка Альфа 1"

    # Чужая сделка компании Б -> пустой результат (None)
    resp_foreign = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_deal_status", "arguments": {"erp_deal_id": test_data["deal_b"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp_foreign.status_code == status.HTTP_200_OK
    assert resp_foreign.data["result"]["structuredContent"]["result"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Инструмент: get_delivery_status
# ─────────────────────────────────────────────────────────────────────────────


def test_get_delivery_status(client, test_data):
    ctx_a = dict(erp_company_id=test_data["comp_a"].id, mode="customer")

    # Своя сделка с поставкой
    resp = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_delivery_status", "arguments": {"erp_deal_id": test_data["deal_a"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp.status_code == status.HTTP_200_OK
    lines = resp.data["result"]["structuredContent"]["result"]
    assert len(lines) == 1
    assert lines[0]["title"] == test_data["deal_a"].title
    assert lines[0]["tracking"] == "TRK-12345"
    assert lines[0]["status"] == "in_transit"
    assert lines[0]["eta"] == test_data["fulf_a"].expected_delivery_date.isoformat()

    # Чужая сделка -> пустой массив []
    resp_foreign = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_delivery_status", "arguments": {"erp_deal_id": test_data["deal_b"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp_foreign.status_code == status.HTTP_200_OK
    assert resp_foreign.data["result"]["structuredContent"]["result"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Инструменты: list_client_documents & get_document_link
# ─────────────────────────────────────────────────────────────────────────────


def test_list_client_documents_and_link(client, test_data):
    ctx_a = dict(erp_company_id=test_data["comp_a"].id, mode="customer")

    # Список документов компании А
    resp = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_client_documents", "arguments": {"kind": "contract"}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp.status_code == status.HTTP_200_OK
    docs = resp.data["result"]["structuredContent"]["result"]
    assert len(docs) == 1
    assert docs[0]["erp_document_id"] == test_data["doc_a"].id
    assert docs[0]["number"] == "CTR-ALFA-01"

    # Получение ссылки на свой документ
    resp_link = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_document_link", "arguments": {"erp_document_id": test_data["doc_a"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp_link.status_code == status.HTTP_200_OK
    link_data = resp_link.data["result"]["structuredContent"]["result"]
    assert link_data is not None
    assert "token=link_" in link_data["url"]
    assert link_data["file_name"].endswith(".pdf")

    # Чужой документ компании Б -> пустой результат (None)
    resp_foreign = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_document_link", "arguments": {"erp_document_id": test_data["doc_b"].id}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp_foreign.status_code == status.HTTP_200_OK
    assert resp_foreign.data["result"]["structuredContent"]["result"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Инструмент: search_catalog (prospect vs customer)
# ─────────────────────────────────────────────────────────────────────────────


def test_search_catalog_prospect_vs_customer(client, test_data):
    # 1. Режим prospect: название, единица, описание, НО БЕЗ ЦЕН И НАЛИЧИЯ (DECISIONS 2026-10-13)
    ctx_prospect = dict(crm_client_id=15, erp_company_id=None, mode="prospect")
    resp_p = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_catalog", "arguments": {"query": "Рельс", "top_k": 3}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_prospect),
    )
    assert resp_p.status_code == status.HTTP_200_OK
    items_p = resp_p.data["result"]["structuredContent"]["result"]
    assert len(items_p) == 1
    p_item = items_p[0]
    assert p_item["id"] == test_data["prod"].id
    assert p_item["name"] == "Рельс Р-65 ГОСТ 51685-2000"
    # Строго: нет полей price, availability, lead_time_days!
    assert "price" not in p_item
    assert "availability" not in p_item
    assert "lead_time_days" not in p_item

    # 2. Режим customer: видит цену и наличие
    ctx_cust = dict(erp_company_id=test_data["comp_a"].id, mode="customer")
    resp_c = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_catalog", "arguments": {"query": "Рельс"}},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_cust),
    )
    assert resp_c.status_code == status.HTTP_200_OK
    items_c = resp_c.data["result"]["structuredContent"]["result"]
    assert len(items_c) == 1
    c_item = items_c[0]
    assert c_item["id"] == test_data["prod"].id
    assert "price" in c_item
    assert c_item["price"]["amount"] == "12500000.00"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Инструмент: create_request (создание заявки + вебхук)
# ─────────────────────────────────────────────────────────────────────────────


def test_create_request_creates_deal_and_emits_webhook(client, test_data):
    ctx_a = dict(erp_company_id=test_data["comp_a"].id, mode="customer")
    req_payload = {
        "summary": "Срочная потребность в партии рельсов",
        "lines": [
            {"text": "Рельс Р-65 ГОСТ 51685", "quantity": "50", "unit": "т"},
            {"text": "Накладка 1Р65", "quantity": "100", "unit": "шт"},
        ],
    }

    resp = client.post(
        "/mcp/erp",
        data={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "create_request", "arguments": req_payload},
        },
        format="json",
        HTTP_X_AGENT_CONTEXT=make_context_token(**ctx_a),
    )
    assert resp.status_code == status.HTTP_200_OK
    res = resp.data["result"]
    assert not res["isError"]
    data = res["structuredContent"]["result"]
    assert "erp_request_id" in data
    deal_id = data["erp_request_id"]
    assert data["number"] == f"D-{deal_id}"
    assert data["status"] == "request"

    # Проверка в БД
    deal = Deal.objects.get(pk=deal_id)
    assert deal.company == test_data["comp_a"]
    assert deal.contact == test_data["contact_a"]
    assert deal.notes == "Срочная потребность в партии рельсов"

    req_lines = PortalRequestLine.objects.filter(deal=deal).order_by("sort_order")
    assert req_lines.count() == 2
    assert req_lines[0].text == "Рельс Р-65 ГОСТ 51685"
    assert req_lines[0].quantity == Decimal("50")
    assert req_lines[0].unit == "т"
    assert req_lines[1].text == "Накладка 1Р65"

    # Проверка создания вебхука request.created
    webhook = IntegrationWebhookEvent.objects.filter(event_type="request.created").order_by("-created_at").first()
    assert webhook is not None
    assert webhook.payload["event"] == "request.created"
    assert webhook.payload["payload"]["source"] == "crm"
    assert webhook.payload["erp_company_id"] == test_data["comp_a"].id
    assert webhook.payload["actor"]["type"] == "client"


# ─────────────────────────────────────────────────────────────────────────────
# 9. FIX-12: строгий X-Agent-Context (S-8)
# ─────────────────────────────────────────────────────────────────────────────

INVALID_CONTEXT = {"detail": "INVALID_AGENT_CONTEXT"}


def forge_context(secret: str = MCP_SECRET, **overrides) -> str:
    """Подписанный контекст с произвольными claims: ключ со значением `None` в overrides удаляет claim."""
    now = int(time.time())
    claims = {
        "crm_client_id": 10,
        "erp_company_id": 1,
        "mode": "customer",
        "language": "ru",
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    for key, value in overrides.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    payload = _b64encode(json.dumps(claims).encode("utf-8"))
    return f"{payload}.{_sign(payload, secret.encode('utf-8'))}"


def rpc(client, token: str, method: str = "tools/call", **params):
    return client.post(
        "/mcp/erp",
        data={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        format="json",
        HTTP_X_AGENT_CONTEXT=token,
    )


def tool_result(resp):
    assert resp.status_code == status.HTTP_200_OK, resp.data
    assert not resp.data["result"]["isError"], resp.data
    return resp.data["result"]["structuredContent"]["result"]


def test_context_without_iat_is_rejected(client):
    token = forge_context(iat=None)
    with pytest.raises(AgentContextError, match="iat"):
        verify_agent_context(token, MCP_SECRET)
    resp = rpc(client, token, "tools/list")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == INVALID_CONTEXT


def test_context_without_exp_is_rejected(client):
    resp = rpc(client, forge_context(exp=None), "tools/list")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == INVALID_CONTEXT


def test_context_with_exp_115_days_ahead_is_rejected(client):
    now = int(time.time())
    token = forge_context(iat=now, exp=now + 115 * 86400)
    with pytest.raises(AgentContextError):
        verify_agent_context(token, MCP_SECRET)
    resp = rpc(client, token, "tools/list")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == INVALID_CONTEXT


def test_context_lifetime_over_60_seconds_is_rejected():
    now = int(time.time())
    with pytest.raises(AgentContextError):
        verify_agent_context(forge_context(iat=now - 30, exp=now + 31), MCP_SECRET)  # 61 с жизни
    verify_agent_context(forge_context(iat=now - 30, exp=now + 30), MCP_SECRET)  # ровно 60 с — можно


def test_context_exp_not_after_iat_is_rejected():
    now = int(time.time())
    with pytest.raises(AgentContextError):
        verify_agent_context(forge_context(iat=now, exp=now), MCP_SECRET)


def test_context_issued_in_future_is_rejected():
    now = int(time.time())
    with pytest.raises(AgentContextError, match="future"):
        verify_agent_context(forge_context(iat=now + 120, exp=now + 150), MCP_SECRET)


def test_context_float_timestamps_are_rejected():
    now = time.time()
    with pytest.raises(AgentContextError):
        verify_agent_context(forge_context(iat=now, exp=now + 60), MCP_SECRET)


@pytest.mark.parametrize("jti", [None, "", "not-a-uuid", 12345, str(uuid.uuid1())])
def test_context_requires_uuid4_jti(client, jti):
    token = forge_context(jti=jti) if jti is not None else forge_context(jti=None)
    with pytest.raises(AgentContextError, match="jti"):
        verify_agent_context(token, MCP_SECRET)
    assert rpc(client, token, "tools/list").status_code == status.HTTP_401_UNAUTHORIZED


def test_bool_is_not_an_int_for_company_id(client, test_data):
    """`True` проходил как компания 1 (bool — подкласс int)."""
    token = forge_context(erp_company_id=True)
    with pytest.raises(AgentContextError):
        verify_agent_context(token, MCP_SECRET)
    resp = rpc(client, token, name="list_client_deals")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == INVALID_CONTEXT


def test_bool_is_not_an_int_for_client_id(client):
    resp = rpc(client, forge_context(crm_client_id=True), "tools/list")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.data == INVALID_CONTEXT


@pytest.mark.parametrize(
    "overrides",
    [
        {"crm_client_id": "10"},
        {"crm_client_id": None},
        {"erp_company_id": "1"},
        {"erp_company_id": None},  # customer без компании
        {"mode": "CUSTOMER"},
        {"mode": "admin"},
        {"language": "de"},
        {"language": None},
        {"trace_id": 5},
    ],
)
def test_context_claims_are_strictly_typed(overrides):
    with pytest.raises(AgentContextError):
        verify_agent_context(forge_context(**overrides), MCP_SECRET)


def test_replayed_jti_is_rejected_on_tool_call(client, test_data):
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    first = rpc(client, token, name="list_client_deals")
    assert tool_result(first)
    replay = rpc(client, token, name="list_client_deals")
    assert replay.status_code == status.HTTP_401_UNAUTHORIZED
    assert replay.data == INVALID_CONTEXT


def test_same_header_serves_the_handshake_before_the_tool_call(client, test_data):
    """MCP-клиент шлёт один заголовок на initialize, notifications/initialized и tools/call."""
    token = make_context_token(erp_company_id=test_data["comp_a"].id)
    assert rpc(client, token, "initialize").status_code == status.HTTP_200_OK
    assert rpc(client, token, "notifications/initialized").status_code == status.HTTP_200_OK
    assert rpc(client, token, "tools/list").status_code == status.HTTP_200_OK
    assert tool_result(rpc(client, token, name="list_client_deals"))


def test_mark_used_is_one_shot(test_data):
    ctx = verify_agent_context(make_context_token(erp_company_id=test_data["comp_a"].id), MCP_SECRET)
    mark_used(ctx)
    with pytest.raises(AgentContextError, match="replay"):
        mark_used(ctx)


def test_failed_signature_does_not_burn_a_jti(client, test_data):
    jti = str(uuid.uuid4())
    bad = make_context_token(erp_company_id=test_data["comp_a"].id, secret="wrong-key", jti=jti)
    assert rpc(client, bad, name="list_client_deals").status_code == status.HTTP_401_UNAUTHORIZED
    good = make_context_token(erp_company_id=test_data["comp_a"].id, jti=jti)
    assert tool_result(rpc(client, good, name="list_client_deals")) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 10. FIX-12: клиентская проекция (S-10)
# ─────────────────────────────────────────────────────────────────────────────


def _quote(deal, version: int, status_code: str) -> Quote:
    status_row, _ = QuoteStatus.objects.get_or_create(code=status_code, defaults={"name": status_code})
    return Quote.objects.create(deal=deal, version=version, status=status_row)


def test_client_does_not_see_draft_and_approval_quotes(client, test_data):
    deal = test_data["deal_a"]
    drafts = [
        _quote(deal, 1, "DRAFT"),
        _quote(deal, 2, "PENDING_TRADE_REVIEW"),
        _quote(deal, 3, "PENDING_APPROVAL"),
        _quote(deal, 4, "READY_TO_SEND"),
    ]
    visible = {
        _quote(deal, 5, "SENT").id: "sent",
        _quote(deal, 6, "APPROVED").id: "accepted",
        _quote(deal, 7, "REJECTED").id: "rejected",
    }

    resp = rpc(
        client,
        make_context_token(erp_company_id=test_data["comp_a"].id),
        name="get_deal_status",
        arguments={"erp_deal_id": deal.id},
    )
    quotes = tool_result(resp)["quotes"]

    assert {q["erp_quote_id"]: q["status"] for q in quotes} == visible
    assert not {q["erp_quote_id"] for q in quotes} & {d.id for d in drafts}


def test_deal_status_has_delivery_without_invented_quantity(client, test_data):
    resp = rpc(
        client,
        make_context_token(erp_company_id=test_data["comp_a"].id),
        name="get_deal_status",
        arguments={"erp_deal_id": test_data["deal_a"].id},
    )
    deliveries = tool_result(resp)["deliveries"]
    assert len(deliveries) == 1  # раньше deal.fulfillments не существовало — список был пуст
    assert deliveries[0]["quantity"] is None
    assert deliveries[0]["unit"] is None
    assert deliveries[0]["tracking"] == "TRK-12345"


def test_delivery_status_does_not_invent_quantity(client, test_data):
    resp = rpc(
        client,
        make_context_token(erp_company_id=test_data["comp_a"].id),
        name="get_delivery_status",
        arguments={"erp_deal_id": test_data["deal_a"].id},
    )
    line = tool_result(resp)[0]
    assert line["quantity"] is None
    assert line["unit"] is None


def test_search_catalog_returns_only_published_projection_keys(client, test_data):
    for ctx in (
        dict(crm_client_id=15, erp_company_id=None, mode="prospect"),
        dict(erp_company_id=test_data["comp_a"].id, mode="customer"),
    ):
        items = tool_result(rpc(client, make_context_token(**ctx), name="search_catalog", arguments={"query": "Рельс"}))
        assert len(items) == 1
        assert "sku" not in items[0]
        assert "erp_product_id" not in items[0]
        assert set(items[0]) <= CATALOG_ITEM_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# 11. FIX-12: аргументы по input_schema (400 INVALID_ARGUMENTS)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("get_deal_status", {}),
        ("get_deal_status", {"erp_deal_id": "1"}),
        ("get_deal_status", {"erp_deal_id": True}),
        ("get_deal_status", {"erp_deal_id": 1, "erp_company_id": 2}),  # чужой идентификатор аргументом
        ("get_delivery_status", {"erp_deal_id": None}),
        ("list_client_deals", {"company_id": 1}),
        ("list_client_documents", {"kind": "passport"}),
        ("list_client_documents", {"date_from": "вчера"}),
        ("get_document_link", {"erp_document_id": "x"}),
        ("search_catalog", {}),
        ("search_catalog", {"query": ""}),
        ("search_catalog", {"query": "x" * 201}),
        ("search_catalog", {"query": "рельс", "top_k": 100}),
        ("create_request", {"summary": "нужен рельс"}),
        ("create_request", {"summary": "нужен рельс", "lines": [{"quantity": "1"}]}),
    ],
)
def test_invalid_arguments_are_rejected_with_400(client, test_data, name, arguments):
    resp = rpc(client, make_context_token(erp_company_id=test_data["comp_a"].id), name=name, arguments=arguments)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.data["detail"] == "INVALID_ARGUMENTS"
    assert resp.data["error"]["message"] == "INVALID_ARGUMENTS"


def test_invalid_arguments_do_not_create_a_request(client, test_data):
    before = Deal.objects.count()
    resp = rpc(
        client,
        make_context_token(erp_company_id=test_data["comp_a"].id),
        name="create_request",
        arguments={"summary": "нужен рельс", "lines": [{"text": "рельс", "company_id": 2}]},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert Deal.objects.count() == before


def test_tool_input_schemas_match_the_contract():
    """`input_schema` в реестре инструментов = `packages/contracts/mcp-tools.json`.

    В контейнере тестов смонтирован только backend/ — тогда сверка пропускается.
    """
    from integration.mcp.tools import TOOLS_METADATA

    candidates = (parent / "packages" / "contracts" / "mcp-tools.json" for parent in Path(__file__).parents)
    contract_path = next((path for path in candidates if path.exists()), None)
    if contract_path is None:
        pytest.skip("packages/contracts не смонтирован")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert {t["name"]: t["input_schema"] for t in contract["tools"]} == {
        t["name"]: t["inputSchema"] for t in TOOLS_METADATA
    }


# ─────────────────────────────────────────────────────────────────────────────
# 12. FIX-12: лимит частоты на компанию (S-9)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mcp_rate(monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "mcp", "3/minute")


def test_rate_limit_per_company_returns_429(client, test_data, mcp_rate):
    comp_a = test_data["comp_a"].id
    for _ in range(3):
        assert rpc(client, make_context_token(erp_company_id=comp_a), "ping").status_code == status.HTTP_200_OK
    limited = rpc(client, make_context_token(erp_company_id=comp_a), "ping")
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Другая компания с того же IP не страдает (раньше общий анонимный лимит бил по всему трафику CRM).
    other = rpc(client, make_context_token(erp_company_id=test_data["comp_b"].id), "ping")
    assert other.status_code == status.HTTP_200_OK


def test_rate_limit_does_not_use_the_shared_anonymous_limit(client, test_data):
    token_args = dict(erp_company_id=test_data["comp_a"].id)
    statuses = {rpc(client, make_context_token(**token_args), "ping").status_code for _ in range(25)}
    assert statuses == {status.HTTP_200_OK}  # анонимный лимит 20/мин здесь уже не действует


def test_invalid_context_requests_are_limited_by_ip(client, mcp_rate):
    codes = [rpc(client, "garbage", "ping").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
