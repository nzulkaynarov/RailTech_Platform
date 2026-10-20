"""Integration на id документа портала (FIX-38, QUESTIONS Q-FIX32-1, вариант 2): сквозные тесты на мире документов портала.

`erp_document_id` в integration — идентификатор документа портала (`portal.services.documents.encode_document_id`).
Мир — тот же, что у сторожа `GET /documents` портала (`portal/tests/documents_world.py`): КП, договоры, счета, акты и
накладные во всех статусах, выпущенные `GeneratedDocument`, скан акта, черновики, внутренние документы и чужая компания.

Что держат тесты:

1. список документов сделки в integration и `GET /documents?deal_id=` портала — одни и те же id, виды и номера;
2. каждый id из списка и из `last_document` открывается ссылкой и отдаёт файл (PDF готов — 200, нет — 202 + рендер);
3. скрытое порталом (черновик, отменённый, внутренний, чужая компания, без сопоставления с CRM) — 404 на ссылке;
4. токен несёт источник, а отозванное за десять минут не открывается — для каждого вида документа;
5. MCP `list_client_documents` / `get_document_link` — те же документы и правила, журнал знает канал «бот».
"""

from __future__ import annotations

import datetime
import json

import pytest
from django.core import signing
from django.core.cache import cache
from integration.mcp import tools as mcp_tools
from integration.mcp.context import AgentContext
from integration.models import CrmClientMapping
from integration.services import documents_link
from integration.tests.contract_support import PREFIX, check_response, component
from parties.models import Company
from portal.services.documents import SLOT_BY_SOURCE, client_documents, decode_document_id
from portal.tests.conftest import (  # noqa: F401  (фикстуры мира портала)
    client_company,
    client_contact,
    client_session,
    client_type,
    other_company,
    other_contact,
    portal_client,
    seller_company,
)
from portal.tests.contract_world import contract_world  # noqa: F401
from portal.tests.documents_world import PDF
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from crm.constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import (
    Act,
    ActivityLog,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

pytestmark = pytest.mark.django_db

TOKEN = "test-service-token"  # conftest._seam_secrets
CRM_CLIENT = 7001
CONTEXT = json.dumps({"crm_client_id": CRM_CLIENT, "crm_user_id": 55, "channel": "crm"})
PUBLIC = "/api/v1/public/doc-links"
PORTAL = "/api/portal/v1"


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch):
    settings.FRONTEND_URL = "http://erp.localhost"
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "100000/minute")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "public_document", "100000/minute")  # документов в мире > 30
    cache.clear()


@pytest.fixture
def render_calls(monkeypatch):
    """Брокера в тестах нет: перехватываем постановку рендера (тип документа, pk записи)."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr("crm.tasks.render_document_pdf.delay", lambda doc_type, pk: calls.append((doc_type, pk)))
    return calls


@pytest.fixture
def crm():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return api


@pytest.fixture
def world(contract_world):  # noqa: F811
    CrmClientMapping.objects.create(crm_client_id=CRM_CLIENT, company=contract_world["company"])
    return contract_world


def link(crm, document_id, context=CONTEXT):
    extra = {"HTTP_X_CRM_CONTEXT": context} if context is not None else {}
    return crm.get(f"{PREFIX}/documents/{document_id}/link", **extra)


def open_link(response):
    token = response.json()["url"].rsplit(f"{PUBLIC}/", 1)[1].rstrip("/")
    return APIClient().get(f"{PUBLIC}/{token}/"), token


def deals_documents(crm, company):
    """Документы всех сделок компании по ответам integration: `{erp_document_id: item}`."""
    items = {}
    for deal in Deal.objects.filter(company=company):
        response = crm.get(f"{PREFIX}/deals/{deal.pk}/documents")
        assert response.status_code == 200
        for item in response.json():
            assert item["erp_document_id"] not in items, "один документ не может лежать в двух сделках"
            items[item["erp_document_id"]] = item
    return items


# ── 1. Один и тот же id у портала и integration ─────────────────────────────────────────────────────


def test_integration_ids_are_the_portal_ids_for_every_deal(crm, portal_client, world):  # noqa: F811
    portal = portal_client.get(f"{PORTAL}/documents").json()
    assert portal
    by_deal: dict = {}
    for item in portal:
        by_deal.setdefault(item["deal"]["id"] if item["deal"] else None, {})[item["id"]] = item
    assert len(by_deal) > 3, "в мире должны быть документы нескольких сделок"
    for deal in Deal.objects.filter(company=world["company"]):
        listed = crm.get(f"{PREFIX}/deals/{deal.pk}/documents").json()
        on_portal = by_deal.get(deal.pk, {})
        assert {i["erp_document_id"] for i in listed} == set(on_portal), f"сделка #{deal.pk}"
        filtered = portal_client.get(f"{PORTAL}/documents", {"deal_id": deal.pk}).json()
        assert {i["id"] for i in filtered} == set(on_portal)
        for item in listed:
            theirs = on_portal[item["erp_document_id"]]
            assert (item["kind"], item["number"], item["title"], item["date"]) == (
                theirs["kind"],
                theirs["number"],
                theirs["title"],
                theirs["date"],
            )
            assert item["erp_deal_id"] == deal.pk


def test_integration_lists_exactly_the_issued_documents_of_the_world(crm, world):
    listed = set(deals_documents(crm, world["company"]))
    deal_less = {world["documents"]["generated_no_deal"]}  # документ без сделки в списках сделок не лежит
    assert listed == set(world["documents"].values()) - deal_less
    assert not listed & set(world["hidden_documents"].values())


def test_every_kind_the_portal_issues_is_listed(crm, world):
    kinds = {item["kind"] for item in deals_documents(crm, world["company"]).values()}
    assert kinds == {"quote", "contract", "invoice", "act", "waybill"}


def test_ids_are_portal_ids_not_record_pks(crm, world):
    for document_id, item in deals_documents(crm, world["company"]).items():
        source, pk = decode_document_id(document_id)
        assert source in SLOT_BY_SOURCE and document_id == pk * 8 + SLOT_BY_SOURCE[source]


def test_items_match_the_contract_document_schema(crm, world):
    schema = component("Document")
    items = deals_documents(crm, world["company"]).values()
    assert items
    problems = [p for item in items for p in check_response(item, schema)]
    assert not problems, problems


def test_status_is_the_portal_status_of_the_source(crm, world):
    statuses = {item["number"]: item["status"] for item in deals_documents(crm, world["company"]).values()}
    assert statuses[world["contracts"]["signed"].number] == "signed"
    assert statuses[world["invoices"]["paid"].number] == "paid"
    assert statuses[world["acts"]["returned"].number] == "returned"
    assert statuses[world["acts"]["accepted"].number] == "accepted"


# ── 2. Каждый id из списков открывается ссылкой ─────────────────────────────────────────────────────


def test_every_listed_id_opens_by_link_and_returns_the_file(crm, world, render_calls):
    ready = set(world["ready_documents"].values())
    listed = deals_documents(crm, world["company"])
    assert listed and ready & set(listed)
    for document_id, item in listed.items():
        issued = link(crm, document_id)
        assert issued.status_code == 200, item
        body = issued.json()
        assert not check_response(body, component("DocumentLink")), item
        response, _ = open_link(issued)
        if document_id in ready:
            assert response.status_code == 200, item
            content = b"".join(response.streaming_content)
            assert content.startswith(b"%PDF") or content, item
            assert body["size_bytes"] == len(content)
            if item["number"] != world["scan_document"].number:
                assert content == PDF, item
        else:
            assert response.status_code == 202, item
            assert response.json() == {"detail": "DOCUMENT_PENDING"}
            assert response["Retry-After"] == "2"
            assert "size_bytes" not in body, "размер неизвестен, пока PDF не отрисован"


def test_not_ready_native_pdfs_are_rendered_by_their_own_task_types(crm, world, render_calls):
    for key, render_type, record in (
        ("contract_sent", "contract", world["contracts"]["sent"]),
        ("invoice_overdue", "invoice", world["invoices"]["overdue"]),
        ("act_issued", "act", world["acts"]["issued"]),
        ("quote_viewed", "quote", world["quotes"]["viewed"]),
    ):
        document_id = world["documents"][key]
        assert document_id not in set(world["ready_documents"].values()), key
        assert link(crm, document_id).status_code == 200
        assert (render_type, record.pk) in render_calls, key
    waybill = world["deliveries"]["in_transit"]
    assert link(crm, world["documents"]["waybill_in_transit"]).status_code == 200
    assert ("delivery_note", waybill.pk) in render_calls


def test_scan_of_a_signed_act_is_a_file_not_a_render(crm, world, render_calls):
    document_id = world["documents"]["act_scan"]
    issued = link(crm, document_id)
    assert issued.status_code == 200
    response, _ = open_link(issued)
    assert response.status_code == 200
    assert render_calls == [], "рисовать скан нечем: его файл общий с актом"


def test_last_document_is_the_newest_portal_document_and_opens(crm, portal_client, world, render_calls):  # noqa: F811
    summary = crm.get(f"{PREFIX}/companies/{world['company'].pk}/summary").json()
    last = summary["last_document"]
    newest = portal_client.get(f"{PORTAL}/documents").json()[0]
    assert last["erp_document_id"] == newest["id"]
    assert (last["kind"], last["number"], last["date"]) == (newest["kind"], newest["number"], newest["date"])
    assert not check_response(last, component("Document"))
    response, _ = open_link(link(crm, last["erp_document_id"]))
    assert response.status_code in (200, 202)


def test_link_token_carries_the_source_of_the_document(crm, world):
    for key, source in (
        ("quote_sent", "quote"),
        ("contract_signed", "contract"),
        ("invoice_paid", "invoice"),
        ("act_accepted", "act"),
        ("waybill_shipped", "waybill"),
        ("generated_contract", "generated"),
    ):
        document_id = world["documents"][key]
        token = link(crm, document_id).json()["url"].rsplit(f"{PUBLIC}/", 1)[1].rstrip("/")
        claims = signing.loads(token, salt=documents_link.LINK_SALT)
        assert (claims["k"], (claims["d"] * 8 + SLOT_BY_SOURCE[claims["k"]])) == (source, document_id), key


def test_link_headers_name_the_file_of_the_document(crm, world):
    body = link(crm, world["documents"]["contract_signed"]).json()
    assert body["file_name"] == "CT-GUARD-signed.pdf" and body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF)


# ── 3. Отказы: все 404 ──────────────────────────────────────────────────────────────────────────────


def test_hidden_documents_are_404_and_leave_no_trace(crm, world, render_calls):
    hidden = world["hidden_documents"]
    assert len(hidden) > 15
    for key, document_id in hidden.items():
        for context in (CONTEXT, None):
            response = link(crm, document_id, context)
            assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}, (key, context)
    assert render_calls == []
    assert not ActivityLog.objects.filter(event_code__startswith="document.link_").exists()


def test_draft_and_cancelled_are_absent_from_every_list(crm, world):
    listed = set(deals_documents(crm, world["company"]))
    for key in ("contract_draft", "contract_cancelled", "invoice_draft", "act_draft", "act_cancelled", "quote_draft"):
        assert world["hidden_documents"][key] not in listed, key
    summary_id = crm.get(f"{PREFIX}/companies/{world['company'].pk}/summary").json()["last_document"]["erp_document_id"]
    assert summary_id not in set(world["hidden_documents"].values())


def test_company_without_crm_mapping_gets_404_for_every_document(crm, world):
    CrmClientMapping.objects.filter(company=world["company"]).delete()
    for key, document_id in world["documents"].items():
        assert link(crm, document_id).status_code == 404, key
        assert link(crm, document_id, None).status_code == 404, key


def test_document_of_another_company_is_404_even_when_it_is_mapped(crm, world):
    """Чужая компания сопоставлена с клиентом CRM, но заголовок называет клиента 7001 — документ не отдаётся."""
    other = world["other"]["deal"].company
    CrmClientMapping.objects.create(crm_client_id=7002, company=other)
    other_id = world["hidden_documents"]["other_company_invoice"]
    assert link(crm, other_id, CONTEXT).status_code == 404
    assert link(crm, other_id, None).status_code == 200, "без заголовка проверяется только само сопоставление"
    own = link(crm, other_id, json.dumps({"crm_client_id": 7002, "channel": "crm"}))
    assert own.status_code == 200, "тот же документ — клиенту, которому он принадлежит"


@pytest.mark.parametrize("document_id", [0, 1, 6, 7, 13, -8, 10**15])
def test_numbers_nobody_issued_are_404(crm, world, document_id):
    assert link(crm, document_id).status_code == 404


def test_pk_of_a_record_is_not_a_document_id(crm, world):
    """Старый смысл `erp_document_id` (pk GeneratedDocument) больше не работает: число без слота — не документ клиента."""
    generated = world["documents"]["generated_contract"] // 8
    foreign_slot_ids = {
        generated * 8 + slot for slot in range(8) if generated * 8 + slot != world["documents"]["generated_contract"]
    }
    visible = set(world["documents"].values())
    for document_id in foreign_slot_ids - visible:
        assert link(crm, document_id).status_code == 404, document_id


# ── 4. Отозванное за десять минут не открывается — у каждого вида документа ───────────────────────


def _revoke(source: str, record):
    """Скрывает документ от клиента так, как это делает ERP: черновик, аннулирование, статус до отгрузки."""
    if source == "quote":
        Quote.objects.filter(pk=record.pk).update(status=QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT))
    elif source == "contract":
        Contract.objects.filter(pk=record.pk).update(
            status=ContractStatus.objects.get(code=ContractStatusCode.CANCELLED)
        )
    elif source == "invoice":
        Invoice.objects.filter(pk=record.pk).update(status=InvoiceStatus.objects.get(code=InvoiceStatusCode.DRAFT))
    elif source == "act":
        Act.objects.filter(pk=record.pk).update(status=ActStatus.objects.get(code=ActStatusCode.CANCELLED))
    elif source == "waybill":
        Fulfillment.objects.filter(pk=record.pk).update(
            status=FulfillmentStatus.objects.get(code=FulfillmentStatusCode.PENDING)
        )


@pytest.mark.parametrize(
    "key,source,record",
    [
        ("quote_sent", "quote", lambda w: w["quotes"]["sent"]),
        ("contract_signed", "contract", lambda w: w["contracts"]["signed"]),
        ("invoice_paid", "invoice", lambda w: w["invoices"]["paid"]),
        ("act_accepted", "act", lambda w: w["acts"]["accepted"]),
        ("waybill_shipped", "waybill", lambda w: w["deliveries"]["shipped"]),
    ],
)
def test_document_revoked_after_issue_does_not_open(crm, world, key, source, record):
    issued = link(crm, world["documents"][key])
    assert issued.status_code == 200
    assert open_link(issued)[0].status_code == 200
    _revoke(source, record(world))
    assert open_link(issued)[0].status_code == 404
    assert link(crm, world["documents"][key]).status_code == 404


def test_mapping_removed_after_issue_does_not_open_a_native_document(crm, world):
    issued = link(crm, world["documents"]["invoice_paid"])
    CrmClientMapping.objects.filter(company=world["company"]).delete()
    assert open_link(issued)[0].status_code == 404


def test_token_with_a_source_that_does_not_exist_is_404(crm, world):
    document_id = world["documents"]["invoice_paid"]
    claims = signing.loads(
        link(crm, document_id).json()["url"].rsplit(f"{PUBLIC}/", 1)[1].rstrip("/"), salt=documents_link.LINK_SALT
    )
    for source in ("laptop", "", None, 3):
        forged = signing.dumps({**claims, "k": source}, salt=documents_link.LINK_SALT, compress=True)
        assert APIClient().get(f"{PUBLIC}/{forged}/").status_code == 404, source
    swapped = signing.dumps({**claims, "k": "quote"}, salt=documents_link.LINK_SALT, compress=True)
    assert APIClient().get(f"{PUBLIC}/{swapped}/").status_code == 404, "pk счёта под видом КП — не тот документ"


def test_token_expires_in_ten_minutes_for_native_documents(crm, world, monkeypatch):
    issued = link(crm, world["documents"]["contract_signed"])
    real_now = documents_link.timezone.now()
    monkeypatch.setattr(documents_link.timezone, "now", lambda: real_now + datetime.timedelta(minutes=10, seconds=30))
    response, _ = open_link(issued)
    assert response.status_code == 410 and response.json() == {"detail": "DOCUMENT_LINK_EXPIRED"}


# ── Журнал ──────────────────────────────────────────────────────────────────────────────────────────


def test_journal_of_a_native_document_has_portal_id_and_source(crm, world):
    document_id = world["documents"]["invoice_paid"]
    invoice = world["invoices"]["paid"]
    issued = link(crm, document_id)
    response, _ = open_link(issued)
    assert response.status_code == 200

    log = ActivityLog.objects.get(event_code="document.link_issued")
    assert (log.entity_type, log.entity_id, log.deal_id, log.company_id) == (
        "invoice",
        invoice.pk,
        invoice.deal_id,
        world["company"].pk,
    )
    assert log.event_params == {
        "document_id": document_id,
        "source": "invoice",
        "kind": "invoice",
        "number": invoice.number,
        "crm_client_id": CRM_CLIENT,
        "crm_user_id": 55,
        "channel": "crm",
        "expires_at": issued.json()["expires_at"],
    }
    download = ActivityLog.objects.get(event_code="document.link_downloaded")
    assert download.event_params["document_id"] == document_id and download.entity_id == invoice.pk


def test_pending_native_document_is_not_logged_as_download(crm, world, render_calls):
    open_link(link(crm, world["documents"]["contract_sent"]))
    assert ActivityLog.objects.filter(event_code="document.link_issued").count() == 1
    assert not ActivityLog.objects.filter(event_code="document.link_downloaded").exists()


# ── 5. MCP: те же документы, тот же id ──────────────────────────────────────────────────────────────


def agent(company: Company, crm_client_id: int = CRM_CLIENT) -> AgentContext:
    return AgentContext(
        crm_client_id=crm_client_id,
        erp_company_id=company.pk,
        mode="customer",
        language="ru",
        iat=0,
        exp=0,
        jti="00000000-0000-4000-8000-000000000000",
    )


def test_list_client_documents_returns_what_the_portal_issues(crm, world):
    listed = mcp_tools.list_client_documents_tool(agent(world["company"]), {})
    ids = {item["erp_document_id"] for item in listed}
    assert ids == set(world["documents"].values()), "включая документ без сделки"
    assert not ids & set(world["hidden_documents"].values())
    assert {item["erp_document_id"]: item for item in listed}.keys() == {
        d.id for d in client_documents(world["company"])
    }
    assert not [p for item in listed for p in check_response(item, component("Document"))]
    no_deal = next(i for i in listed if i["erp_document_id"] == world["documents"]["generated_no_deal"])
    assert no_deal["erp_deal_id"] is None


def test_list_client_documents_filters_by_kind_and_dates(world):
    ctx = agent(world["company"])
    contracts = mcp_tools.list_client_documents_tool(ctx, {"kind": "contract"})
    assert contracts and {i["kind"] for i in contracts} == {"contract"}
    assert {i["erp_document_id"] for i in contracts} == {
        pk for key, pk in world["documents"].items() if key.startswith("contract_") or key == "generated_contract"
    }
    assert mcp_tools.list_client_documents_tool(ctx, {"kind": "receipt"}) == []
    assert mcp_tools.list_client_documents_tool(ctx, {"date_from": "2999-01-01"}) == []
    assert mcp_tools.list_client_documents_tool(ctx, {"date_to": "2000-01-01"}) == []
    everything = mcp_tools.list_client_documents_tool(ctx, {})
    today = datetime.date.today().isoformat()
    assert mcp_tools.list_client_documents_tool(ctx, {"date_from": "2000-01-01", "date_to": "2999-12-31"}) == everything
    assert len(mcp_tools.list_client_documents_tool(ctx, {"date_from": today, "date_to": today})) <= len(everything)
    assert (
        mcp_tools.list_client_documents_tool(ctx, {"date_from": "не дата"}) == everything
    ), "мусор фильтром не считается"


def test_list_client_documents_of_another_company_is_isolated(world):
    other = world["other"]["deal"].company
    ids = {i["erp_document_id"] for i in mcp_tools.list_client_documents_tool(agent(other, 7002), {})}
    assert ids and not ids & set(world["documents"].values())
    assert world["hidden_documents"]["other_company_invoice"] in ids


def test_get_document_link_covers_every_listed_native_kind_and_logs_the_bot_channel(crm, world, render_calls):
    ctx = agent(world["company"])
    for key in (
        "quote_sent",
        "contract_signed",
        "invoice_paid",
        "act_accepted",
        "waybill_shipped",
        "generated_contract",
    ):
        link_data = mcp_tools.get_document_link_tool(ctx, {"erp_document_id": world["documents"][key]})
        assert link_data is not None, key
        assert not check_response(link_data, component("DocumentLink")), key
        assert APIClient().get(link_data["url"].split("erp.localhost", 1)[1]).status_code == 200, key
    logs = list(ActivityLog.objects.filter(event_code="document.link_issued"))
    assert len(logs) == 6
    assert {(log.event_params["crm_client_id"], log.event_params["channel"]) for log in logs} == {(CRM_CLIENT, "bot")}
    assert not any("crm_context_raw" in log.event_params for log in logs)


def test_get_document_link_refuses_hidden_foreign_and_unmapped_documents(crm, world, render_calls):
    ctx = agent(world["company"])
    for key, document_id in world["hidden_documents"].items():
        assert mcp_tools.get_document_link_tool(ctx, {"erp_document_id": document_id}) is None, key
    other = world["other"]["deal"].company
    CrmClientMapping.objects.create(crm_client_id=7002, company=other)
    other_id = world["hidden_documents"]["other_company_invoice"]
    assert mcp_tools.get_document_link_tool(ctx, {"erp_document_id": other_id}) is None
    assert mcp_tools.get_document_link_tool(agent(other, 7002), {"erp_document_id": other_id}) is not None
    # агент называет не того клиента CRM, с которым сопоставлена компания: чужой документ неотличим от несуществующего
    assert (
        mcp_tools.get_document_link_tool(
            agent(world["company"], 7999), {"erp_document_id": world["documents"]["invoice_paid"]}
        )
        is None
    )
    assert not ActivityLog.objects.filter(event_code="document.link_issued", company_id=world["company"].pk).exists()


def test_get_document_link_tool_rejects_non_integer_id(world):
    with pytest.raises(mcp_tools.ToolExecutionError):
        mcp_tools.get_document_link_tool(agent(world["company"]), {"erp_document_id": "x"})
