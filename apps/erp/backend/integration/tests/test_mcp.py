"""Тесты erp-mcp на официальном SDK (CRM Agent Integration, CONTRACTS §5, M3-ERP-03, FIX-12, FIX-36).

Сервер — приложение `mcp` SDK + вратарь контекста (`integration/mcp`), запускается в процессе теста без сети;
вызовы идут клиентом SDK (`mcp.Client` + `streamable_http_client`, как в CRM) и сырым JSON-RPC там, где проверяется
HTTP-контракт (401/400/429, ошибка протокола). Схемы инструментов сверяются с `packages/contracts/mcp-tools.json`.

1. Контракт: инструменты сервера = mcp-tools.json, дубля схем в коде нет
2. Подпись и claims X-Agent-Context, одноразовость jti, prospect без компании
3. Протокол: initialize, list_tools, неизвестный метод — ошибка протокола
4. Инструменты (7), режимы, cross-tenant изоляция
5. Ошибки: общий код, без текста исключения
6. Аргументы по input_schema (400), лимит частоты (429)
"""

import json
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.cache import cache
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocumentStatus
from integration.mcp import contract as mcp_contract
from integration.mcp import tools as mcp_tools
from integration.mcp.context import AgentContextError, issue_agent_context, mark_used, verify_agent_context
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from integration.tests.mcp_support import (
    MCP_SECRET,
    RAW_HEADERS,
    forge_context,
    make_context_token,
    payload,
    raw_get,
    raw_modern_rpc,
    raw_rpc,
    sdk_call,
    sdk_handshake,
    sdk_list_tools,
    tcp_server,
)
from parties.models import Company, CompanyType, Contact
from portal.models import PortalRequestLine
from rest_framework.throttling import SimpleRateThrottle
from sales.models import Fulfillment, FulfillmentStatus, Quote, QuoteItem, QuoteStatus

from catalog.models import Category, Product, ProductStatus
from catalog.published import CATALOG_ITEM_KEYS
from crm.constants import DealStageCode, FulfillmentStatusCode, QuoteStatusCode
from crm.models import Deal, DealStage, GeneratedDocument
from master_data.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

INVALID_CONTEXT = {"detail": "INVALID_AGENT_CONTEXT"}
MCP_DIR = Path(mcp_tools.__file__).parent


@pytest.fixture(autouse=True)
def setup_mcp_settings(settings):
    settings.ERP_MCP_CONTEXT_KEY = MCP_SECRET
    settings.ERP_BASE_URL = "http://erp.localhost"
    settings.ERP_VERSION = "0.1.0"
    settings.ERP_WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def clean_throttle_and_jti_cache():
    """Лимиты и «виденные» jti живут в Redis между тестами; каждый тест начинает с чистого листа."""
    cache.clear()
    yield
    cache.clear()


def customer(test_data, who: str = "comp_a", **kwargs) -> str:
    return make_context_token(erp_company_id=test_data[who].id, **kwargs)


def prospect(crm_client_id: int = 15) -> str:
    return make_context_token(crm_client_id=crm_client_id, erp_company_id=None, mode="prospect")


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

    # Настоящие стадии FSM (FIX-30): прежние коды `request` и `won` в ERP не существуют
    stage_req = DealStage.objects.get(code=DealStageCode.DRAFT)
    stage_won = DealStage.objects.get(code=DealStageCode.CLOSED_WON)

    # Сделка А
    deal_a = Deal.objects.create(
        company=comp_a,
        contact=contact_a,
        stage=stage_req,
        title="Сделка Альфа 1",
    )

    # Поставка для сделки А
    status_in_transit = FulfillmentStatus.objects.get(code=FulfillmentStatusCode.IN_TRANSIT)
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


def _quote(deal, version: int, status_code: str) -> Quote:
    status_row, _ = QuoteStatus.objects.get_or_create(code=status_code, defaults={"name": status_code})
    return Quote.objects.create(deal=deal, version=version, status=status_row)


def _contract() -> dict:
    return json.loads(mcp_contract.contract_path().read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Контракт: инструменты сервера = packages/contracts/mcp-tools.json
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_TOOLS = [
    "list_client_deals",
    "get_deal_status",
    "get_delivery_status",
    "list_client_documents",
    "get_document_link",
    "search_catalog",
    "create_request",
]


def test_server_tools_are_exactly_the_contract_tools(test_data):
    """Имя, описание и схема аргументов каждого инструмента сервера — из mcp-tools.json, в том же порядке."""
    contract_tools = _contract()["tools"]
    listed = sdk_list_tools(customer(test_data)).tools

    assert [t.name for t in listed] == [t["name"] for t in contract_tools] == EXPECTED_TOOLS
    for served, declared in zip(listed, contract_tools):
        assert served.description == declared["description"]
        assert served.input_schema == declared["input_schema"]


def test_every_contract_tool_has_a_handler_and_nothing_extra():
    assert set(mcp_tools.HANDLERS) == {t["name"] for t in _contract()["tools"]}
    mcp_tools.assert_handlers_match_contract([t["name"] for t in _contract()["tools"]])
    with pytest.raises(RuntimeError, match="расходятся"):
        mcp_tools.assert_handlers_match_contract([*EXPECTED_TOOLS, "ghost_tool"])
    with pytest.raises(RuntimeError, match="расходятся"):
        mcp_tools.assert_handlers_match_contract(EXPECTED_TOOLS[:-1])


def test_tools_declare_no_client_identifiers(test_data):
    for tool in sdk_list_tools(customer(test_data)).tools:
        props = tool.input_schema.get("properties", {})
        assert not set(props) & {"crm_client_id", "erp_company_id", "client_id", "company_id"}


def test_code_has_no_copy_of_the_tool_schemas():
    """Схемы живут только в контракте: в модулях erp-mcp нет ни описаний полей, ни реестра метаданных."""
    for path in MCP_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "additionalProperties" not in source.replace("additionalProperties: false", ""), path.name
        assert "TOOLS_METADATA" not in source, path.name
        assert not re.search(r"""["']inputSchema["']""", source), path.name


def test_contract_missing_is_an_error_not_an_empty_server(settings, tmp_path):
    settings.ERP_MCP_TOOLS_PATH = str(tmp_path / "nope.json")
    mcp_contract.load_contract.cache_clear()
    try:
        with pytest.raises(mcp_contract.ContractError, match="файла нет"):
            mcp_contract.load_contract()
    finally:
        settings.ERP_MCP_TOOLS_PATH = ""
        mcp_contract.load_contract.cache_clear()


def test_broken_contract_is_rejected(settings, tmp_path):
    broken = tmp_path / "mcp-tools.json"
    broken.write_text(json.dumps({"version": "1", "path": "/mcp/erp", "tools": []}), encoding="utf-8")
    settings.ERP_MCP_TOOLS_PATH = str(broken)
    mcp_contract.load_contract.cache_clear()
    try:
        with pytest.raises(mcp_contract.ContractError, match="ни одного инструмента"):
            mcp_contract.load_contract()
    finally:
        settings.ERP_MCP_TOOLS_PATH = ""
        mcp_contract.load_contract.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Подпись и claims X-Agent-Context
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


def test_prospect_with_company_is_rejected():
    """Лид ещё не клиент: контекст prospect с компанией — подделка или ошибка выпускающей стороны."""
    with pytest.raises(AgentContextError, match="prospect"):
        verify_agent_context(forge_context(mode="prospect", erp_company_id=7), MCP_SECRET)
    with pytest.raises(ValueError, match="prospect"):
        issue_agent_context(MCP_SECRET, crm_client_id=1, mode="prospect", erp_company_id=7)


def test_prospect_with_company_gets_401_over_http(test_data):
    token = forge_context(mode="prospect", erp_company_id=test_data["comp_a"].id)
    resp = raw_rpc(token, "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


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


def test_missing_context_is_401_on_post_and_get():
    for response in (raw_get(None), raw_rpc(None, "ping")):
        assert response.status_code == 401
        assert response.json() == INVALID_CONTEXT


def test_invalid_signature_is_401():
    assert raw_rpc(make_context_token(secret="wrong-key"), "tools/list").status_code == 401
    assert raw_rpc("garbage", "tools/list").status_code == 401


def test_empty_server_key_closes_the_server(settings, test_data):
    """Ключ не задан — сервер закрыт, а не принимает подпись пустым ключом (FIX-03)."""
    settings.ERP_MCP_CONTEXT_KEY = ""
    forged = issue_agent_context("", crm_client_id=1, mode="prospect")
    resp = raw_rpc(forged, "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


def test_context_without_iat_is_rejected():
    token = forge_context(iat=None)
    with pytest.raises(AgentContextError, match="iat"):
        verify_agent_context(token, MCP_SECRET)
    resp = raw_rpc(token, "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


def test_context_without_exp_is_rejected():
    resp = raw_rpc(forge_context(exp=None), "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


def test_context_with_exp_115_days_ahead_is_rejected():
    now = int(time.time())
    token = forge_context(iat=now, exp=now + 115 * 86400)
    with pytest.raises(AgentContextError):
        verify_agent_context(token, MCP_SECRET)
    resp = raw_rpc(token, "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


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
def test_context_requires_uuid4_jti(jti):
    token = forge_context(jti=jti)
    with pytest.raises(AgentContextError, match="jti"):
        verify_agent_context(token, MCP_SECRET)
    assert raw_rpc(token, "tools/list").status_code == 401


def test_bool_is_not_an_int_for_company_id(test_data):
    """`True` проходил как компания 1 (bool — подкласс int)."""
    token = forge_context(erp_company_id=True)
    with pytest.raises(AgentContextError):
        verify_agent_context(token, MCP_SECRET)
    resp = raw_rpc(token, "tools/call", {"name": "list_client_deals", "arguments": {}})
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


def test_bool_is_not_an_int_for_client_id():
    resp = raw_rpc(forge_context(crm_client_id=True), "tools/list")
    assert resp.status_code == 401
    assert resp.json() == INVALID_CONTEXT


@pytest.mark.parametrize(
    "overrides",
    [
        {"crm_client_id": "10"},
        {"crm_client_id": None},
        {"erp_company_id": "1"},
        {"erp_company_id": None},  # customer без компании
        {"mode": "prospect"},  # prospect с компанией
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


def test_replayed_jti_is_rejected_on_tool_call(test_data):
    token = customer(test_data)
    assert payload(sdk_call(token, "list_client_deals")) is not None
    replay = raw_rpc(token, "tools/call", {"name": "list_client_deals", "arguments": {}})
    assert replay.status_code == 401
    assert replay.json() == INVALID_CONTEXT


def test_same_header_serves_the_handshake_before_the_tool_call(test_data):
    """Клиент SDK шлёт один заголовок на initialize, tools/list и tools/call: гасится только tools/call."""
    token = customer(test_data)
    assert raw_rpc(token, "ping").status_code == 200
    assert raw_rpc(token, "tools/list").status_code == 200
    assert payload(sdk_call(token, "list_client_deals")) is not None


def test_mark_used_is_one_shot(test_data):
    ctx = verify_agent_context(customer(test_data), MCP_SECRET)
    mark_used(ctx)
    with pytest.raises(AgentContextError, match="replay"):
        mark_used(ctx)


def test_failed_signature_does_not_burn_a_jti(test_data):
    jti = str(uuid.uuid4())
    bad = customer(test_data, secret="wrong-key", jti=jti)
    assert raw_rpc(bad, "tools/call", {"name": "list_client_deals", "arguments": {}}).status_code == 401
    good = customer(test_data, jti=jti)
    assert payload(sdk_call(good, "list_client_deals")) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Протокол через клиент SDK: initialize, list_tools, ошибки протокола
# ─────────────────────────────────────────────────────────────────────────────


def test_sdk_client_initialize_and_list_tools(test_data):
    """mcp.Client + streamable_http_client: рукопожатие и список инструментов контракта."""
    name, version, names = sdk_handshake(customer(test_data))
    assert name == "erp-mcp"
    assert version == _contract()["version"]
    assert names == EXPECTED_TOOLS


def test_server_works_over_tcp_under_uvicorn(test_data):
    """Не только в процессе теста: настоящий uvicorn, клиент SDK по TCP, вратарь и Host-проверка SDK."""
    import httpx2
    from asgiref.sync import async_to_sync
    from integration.mcp.context import HEADER_NAME
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def call(url, token, tool):
        async with httpx2.AsyncClient(headers={HEADER_NAME: token}, timeout=15) as http:
            async with Client(streamable_http_client(url, http_client=http)) as client:
                return await client.call_tool(tool, {})

    with tcp_server() as url:
        # prospect не видит инструменты клиента: отказ по режиму, до базы дело не доходит
        denied = async_to_sync(call)(url, prospect(), "list_client_deals")
        assert denied.is_error
        assert denied.structured_content["error"] == "TOOL_NOT_AVAILABLE_IN_MODE"

        # без контекста — 401 на самом транспорте
        anonymous = httpx2.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=RAW_HEADERS)
        assert anonymous.status_code == 401
        assert anonymous.json() == INVALID_CONTEXT


def test_unknown_method_is_a_protocol_error_not_200(test_data):
    """Неизвестный метод — ошибка протокола (JSON-RPC -32601), а не результат; в протоколе 2026-07-28 — ещё и HTTP 404."""
    modern = raw_modern_rpc(customer(test_data), "unknown_function")
    assert modern.status_code == 404
    assert modern.json()["error"]["code"] == -32601
    assert "result" not in modern.json()

    legacy = raw_rpc(customer(test_data), "unknown_function")  # протокол без конверта `_meta`: статус решает SDK
    assert legacy.json()["error"]["code"] in (-32601, -32602)
    assert "result" not in legacy.json()


def test_unknown_tool_is_an_error_result(test_data):
    result = sdk_call(customer(test_data), "drop_all_tables")
    assert result.is_error
    assert result.structured_content["error"] == "TOOL_NOT_FOUND"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Инструменты: list_client_deals & get_deal_status (Cross-tenant изоляция)
# ─────────────────────────────────────────────────────────────────────────────


def test_list_client_deals_cross_tenant_isolation(test_data):
    deals_a = payload(sdk_call(customer(test_data), "list_client_deals"))
    assert len(deals_a) == 1
    assert deals_a[0]["erp_deal_id"] == test_data["deal_a"].id
    assert deals_a[0]["number"] == f"D-{test_data['deal_a'].id}"

    deals_b = payload(sdk_call(customer(test_data, "comp_b"), "list_client_deals"))
    assert [d["erp_deal_id"] for d in deals_b] == [test_data["deal_b"].id]


def test_customer_tools_are_not_available_to_prospect(test_data):
    for tool, arguments in (
        ("list_client_deals", {}),
        ("get_deal_status", {"erp_deal_id": test_data["deal_a"].id}),
        ("get_delivery_status", {"erp_deal_id": test_data["deal_a"].id}),
        ("list_client_documents", {}),
        ("get_document_link", {"erp_document_id": test_data["doc_a"].id}),
        ("create_request", {"summary": "x", "lines": [{"text": "рельс"}]}),
    ):
        result = sdk_call(prospect(), tool, arguments)
        assert result.is_error, tool
        assert result.structured_content["error"] == "TOOL_NOT_AVAILABLE_IN_MODE", tool


def test_get_deal_status_cross_tenant_isolation(test_data):
    deal_data = payload(sdk_call(customer(test_data), "get_deal_status", {"erp_deal_id": test_data["deal_a"].id}))
    assert deal_data["erp_deal_id"] == test_data["deal_a"].id
    assert deal_data["title"] == "Сделка Альфа 1"

    # Чужая сделка компании Б -> пустой результат (None)
    foreign = sdk_call(customer(test_data), "get_deal_status", {"erp_deal_id": test_data["deal_b"].id})
    assert payload(foreign) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Инструмент: get_delivery_status
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def order_a(test_data):
    """Заказ клиента А: одно подтверждённое КП с одной позицией — из него строятся строки поставки (FIX-22)."""
    order = Quote.objects.create(
        deal=test_data["deal_a"],
        version=90,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.APPROVED),
        total_incl_vat=Decimal("100"),
    )
    QuoteItem.objects.create(
        quote=order,
        display_type="ITEM",
        imported_raw_name="Рельс Р65",
        quantity=3,
        unit="т",
        frozen_base_price=Decimal("100"),
        position=1,
    )
    return order


def test_get_delivery_status(test_data, order_a):
    lines = payload(sdk_call(customer(test_data), "get_delivery_status", {"erp_deal_id": test_data["deal_a"].id}))
    assert len(lines) == 1
    assert lines[0]["title"] == "Рельс Р65"  # строка заказа клиента, а не название сделки
    assert lines[0]["tracking"] == "TRK-12345"
    assert lines[0]["status"] == "in_transit"
    assert lines[0]["eta"] == test_data["fulf_a"].expected_delivery_date.isoformat()

    # Чужая сделка -> пустой массив []
    foreign = sdk_call(customer(test_data), "get_delivery_status", {"erp_deal_id": test_data["deal_b"].id})
    assert payload(foreign) == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Инструменты: list_client_documents & get_document_link
# ─────────────────────────────────────────────────────────────────────────────


def test_list_client_documents_and_link(test_data):
    docs = payload(sdk_call(customer(test_data), "list_client_documents", {"kind": "contract"}))
    assert len(docs) == 1
    assert docs[0]["erp_document_id"] == test_data["doc_a"].id
    assert docs[0]["number"] == "CTR-ALFA-01"

    link = payload(sdk_call(customer(test_data), "get_document_link", {"erp_document_id": test_data["doc_a"].id}))
    assert link is not None
    assert "token=link_" in link["url"]  # заглушка до FIX-32
    assert link["file_name"].endswith(".pdf")

    # Чужой документ компании Б -> пустой результат (None)
    foreign = sdk_call(customer(test_data), "get_document_link", {"erp_document_id": test_data["doc_b"].id})
    assert payload(foreign) is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Инструмент: search_catalog (prospect vs customer)
# ─────────────────────────────────────────────────────────────────────────────


def test_search_catalog_prospect_vs_customer(test_data):
    # 1. prospect: название, единица, описание, НО БЕЗ ЦЕН И НАЛИЧИЯ (DECISIONS 2026-10-13)
    items_p = payload(sdk_call(prospect(), "search_catalog", {"query": "Рельс", "top_k": 3}))
    assert len(items_p) == 1
    p_item = items_p[0]
    assert p_item["id"] == test_data["prod"].id
    assert p_item["name"] == "Рельс Р-65 ГОСТ 51685-2000"
    assert "price" not in p_item
    assert "availability" not in p_item
    assert "lead_time_days" not in p_item

    # 2. customer: видит цену и наличие
    items_c = payload(sdk_call(customer(test_data), "search_catalog", {"query": "Рельс"}))
    assert len(items_c) == 1
    assert items_c[0]["id"] == test_data["prod"].id
    assert items_c[0]["price"]["amount"] == "12500000.00"


def test_search_catalog_returns_only_published_projection_keys(test_data):
    for token in (prospect(), customer(test_data)):
        items = payload(sdk_call(token, "search_catalog", {"query": "Рельс"}))
        assert len(items) == 1
        assert "sku" not in items[0]
        assert "erp_product_id" not in items[0]
        assert set(items[0]) <= CATALOG_ITEM_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# 8. Инструмент: create_request (одна заявка, одно событие request.created)
# ─────────────────────────────────────────────────────────────────────────────


def test_create_request_creates_deal_and_emits_one_webhook(test_data):
    req_payload = {
        "summary": "Срочная потребность в партии рельсов",
        "lines": [
            {"text": "Рельс Р-65 ГОСТ 51685", "quantity": "50", "unit": "т"},
            {"text": "Накладка 1Р65", "quantity": "100", "unit": "шт"},
        ],
    }
    CrmClientMapping.objects.filter(company=test_data["comp_a"]).update(crm_client_id=10)

    data = payload(sdk_call(customer(test_data, crm_client_id=10), "create_request", req_payload))
    deal_id = data["erp_request_id"]
    assert data["number"] == f"D-{deal_id}"
    assert data["status"] == "request"

    deal = Deal.objects.get(pk=deal_id)
    assert deal.company == test_data["comp_a"]
    assert deal.contact == test_data["contact_a"]
    assert deal.notes == "Срочная потребность в партии рельсов"
    assert deal.stage.code == DealStageCode.DRAFT

    req_lines = PortalRequestLine.objects.filter(deal=deal).order_by("sort_order")
    assert req_lines.count() == 2
    assert req_lines[0].text == "Рельс Р-65 ГОСТ 51685"
    assert req_lines[0].quantity == Decimal("50")
    assert req_lines[0].unit == "т"
    assert req_lines[1].text == "Накладка 1Р65"

    # request.created — ровно один (раньше сигнал и явный вызов давали два)
    created = [
        e
        for e in IntegrationWebhookEvent.objects.filter(event_type="request.created")
        if e.payload.get("deal", {}).get("erp_deal_id") == deal_id
    ]
    assert len(created) == 1
    envelope = created[0].payload
    assert envelope["payload"]["source"] == "crm"
    assert envelope["payload"]["summary"] == "Срочная потребность в партии рельсов"
    assert envelope["erp_company_id"] == test_data["comp_a"].id
    assert envelope["crm_client_id"] == 10
    assert envelope["actor"]["type"] == "client"


def test_create_request_takes_crm_client_from_the_signed_context(test_data):
    """Идентификатор клиента CRM — из подписанного контекста, а не из сопоставления компании."""
    data = payload(
        sdk_call(
            customer(test_data, crm_client_id=777),
            "create_request",
            {"summary": "нужен рельс", "lines": [{"text": "рельс"}]},
        )
    )
    event = IntegrationWebhookEvent.objects.get(
        event_type="request.created", payload__deal__erp_deal_id=data["erp_request_id"]
    )
    assert event.payload["crm_client_id"] == 777


# ─────────────────────────────────────────────────────────────────────────────
# 9. Ошибки инструментов: общий код, текст исключения модели не уходит
# ─────────────────────────────────────────────────────────────────────────────


def test_tool_crash_returns_generic_code_without_exception_text(test_data, monkeypatch):
    def boom(context, arguments):
        raise RuntimeError("secret-internal-detail: password=hunter2 table=crm_deal")

    monkeypatch.setitem(mcp_tools.HANDLERS, "list_client_deals", boom)
    result = sdk_call(customer(test_data), "list_client_deals")

    assert result.is_error
    assert result.structured_content == {"error": "INTERNAL_ERROR"}
    dumped = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "secret-internal-detail" not in dumped
    assert "hunter2" not in dumped
    assert "RuntimeError" not in dumped


def test_tool_execution_error_uses_its_own_code(test_data, monkeypatch):
    def refuse(context, arguments):
        raise mcp_tools.ToolExecutionError("erp_deal_id integer required")

    monkeypatch.setitem(mcp_tools.HANDLERS, "list_client_deals", refuse)
    result = sdk_call(customer(test_data), "list_client_deals")
    assert result.is_error
    assert result.structured_content["error"] == "TOOL_EXECUTION_ERROR"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Клиентская проекция (S-10)
# ─────────────────────────────────────────────────────────────────────────────


def test_client_does_not_see_draft_and_approval_quotes(test_data):
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

    quotes = payload(sdk_call(customer(test_data), "get_deal_status", {"erp_deal_id": deal.id}))["quotes"]

    assert {q["erp_quote_id"]: q["status"] for q in quotes} == visible
    assert not {q["erp_quote_id"] for q in quotes} & {d.id for d in drafts}


def test_amount_ignores_draft_quotes_and_follows_the_last_sent_one(test_data):
    """Хвост FIX-12: `amount` — сумма последнего КП, видимого клиенту; черновик и КП на согласовании в неё не попадают."""
    deal = test_data["deal_a"]

    def amounts():
        listed = payload(sdk_call(customer(test_data), "list_client_deals"))
        detail = payload(sdk_call(customer(test_data), "get_deal_status", {"erp_deal_id": deal.id}))
        return [d["amount"] for d in listed if d["erp_deal_id"] == deal.id], detail["amount"]

    draft = _quote(deal, 1, "DRAFT")
    draft.total_incl_vat = Decimal("999999")
    draft.save()
    assert amounts() == ([None], None)  # клиенту КП не отправлялось — суммы нет, а не сумма черновика

    sent = _quote(deal, 2, "SENT")
    sent.total_incl_vat = Decimal("1200")
    sent.public_access_token = "tok-sent-fake"  # клиент видит КП только с публичной ссылкой
    sent.save()
    newer_draft = _quote(deal, 3, "PENDING_APPROVAL")
    newer_draft.total_incl_vat = Decimal("5")
    newer_draft.save()
    listed, detail = amounts()
    assert listed == ["1200.00"] and detail == "1200.00"


def test_deal_status_has_delivery_from_the_order_line(test_data, order_a):
    data = payload(sdk_call(customer(test_data), "get_deal_status", {"erp_deal_id": test_data["deal_a"].id}))
    deliveries = data["deliveries"]
    assert len(deliveries) == 1  # раньше deal.fulfillments не существовало — список был пуст
    assert deliveries[0]["quantity"] == "3"  # из строки подтверждённого заказа, не выдумано
    assert deliveries[0]["unit"] == "т"
    assert deliveries[0]["tracking"] == "TRK-12345"


def test_delivery_status_takes_quantity_from_the_order_line_only(test_data, order_a):
    line = payload(sdk_call(customer(test_data), "get_delivery_status", {"erp_deal_id": test_data["deal_a"].id}))[0]
    assert line["quantity"] == "3"
    assert line["unit"] == "т"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Аргументы по input_schema из контракта (400 INVALID_ARGUMENTS)
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
def test_invalid_arguments_are_rejected_with_400(test_data, name, arguments):
    resp = raw_rpc(customer(test_data), "tools/call", {"name": name, "arguments": arguments})
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "INVALID_ARGUMENTS"
    assert body["error"]["message"] == "INVALID_ARGUMENTS"
    assert body["id"] == 1
    assert "x" * 50 not in json.dumps(body)  # значения аргументов в ответ не возвращаются


def test_invalid_arguments_do_not_create_a_request(test_data):
    before = Deal.objects.count()
    resp = raw_rpc(
        customer(test_data),
        "tools/call",
        {
            "name": "create_request",
            "arguments": {"summary": "нужен рельс", "lines": [{"text": "рельс", "company_id": 2}]},
        },
    )
    assert resp.status_code == 400
    assert Deal.objects.count() == before


# ─────────────────────────────────────────────────────────────────────────────
# 12. Лимит частоты на компанию (S-9)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mcp_rate(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "mcp", "3/minute")


def test_rate_limit_per_company_returns_429(test_data, mcp_rate):
    comp_a = test_data["comp_a"].id
    for _ in range(3):
        assert raw_rpc(make_context_token(erp_company_id=comp_a), "ping").status_code == 200
    limited = raw_rpc(make_context_token(erp_company_id=comp_a), "ping")
    assert limited.status_code == 429
    assert limited.json() == {"detail": "TOO_MANY_REQUESTS"}
    assert int(limited.headers["Retry-After"]) >= 1

    # Другая компания с того же адреса не страдает (общий анонимный лимит по IP на erp-mcp не действует).
    assert raw_rpc(make_context_token(erp_company_id=test_data["comp_b"].id), "ping").status_code == 200


def test_rate_limit_does_not_use_the_shared_anonymous_limit(test_data):
    statuses = {raw_rpc(customer(test_data), "ping").status_code for _ in range(25)}
    assert statuses == {200}  # анонимный лимит 20/мин здесь не действует


def test_prospects_are_limited_per_crm_client(mcp_rate):
    for _ in range(3):
        assert raw_rpc(prospect(15), "ping").status_code == 200
    assert raw_rpc(prospect(15), "ping").status_code == 429
    assert raw_rpc(prospect(16), "ping").status_code == 200


def test_invalid_context_requests_are_limited_by_ip(mcp_rate):
    codes = [raw_rpc("garbage", "ping").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
