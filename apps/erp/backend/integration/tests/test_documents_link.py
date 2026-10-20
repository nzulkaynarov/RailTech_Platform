"""Подписанная ссылка на документ (FIX-32, находки S-4, I-6): `GET /documents/{id}/link` и публичный маршрут по токену.

Что держат тесты:

1. ссылка настоящая: URL на `FRONTEND_URL`, подписанный токен, срок 10 минут, ответ по контракту, файл скачивается;
2. id из `GET /deals/{id}/documents` и из `last_document` сводки всегда открывается ссылкой (сквозной тест);
3. отказы одинаковы (404): без сопоставления с клиентом CRM, черновик, отменённый и внутренний документ, чужой клиент;
4. токен: подделка и чужая соль — 404, срок вышел — 410, документ отозван за десять минут — 404, голый id не принимается;
5. журнал ERP: выдача и каждое скачивание — `ActivityLog` с `crm_*`-контекстом; отказы и 202 в журнал не попадают;
6. 202 + `Retry-After` пока PDF не готов; лимит частоты общий с публичными ссылками.
"""

from __future__ import annotations

import datetime
import json

import pytest
from django.core import signing
from django.core.files.base import ContentFile
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from integration.models import CrmClientMapping
from integration.services import documents_link
from integration.tests.contract_support import PREFIX, check_response, response_schema
from integration.tests.world import make_company, make_deal
from portal.services.documents import encode_document_id, find_client_document
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

TOKEN = "test-service-token"  # conftest._seam_secrets
PDF = b"%PDF-1.4 fake-fix32"
CONTEXT = json.dumps({"crm_client_id": 7001, "crm_user_id": 55, "channel": "bot"})
PUBLIC = "/api/v1/public/doc-links"


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch):
    settings.FRONTEND_URL = "http://erp.localhost"
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "100000/minute")


@pytest.fixture
def render_calls(monkeypatch):
    """Брокера в тестах нет: перехватываем постановку рендера."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr("crm.tasks.render_document_pdf.delay", lambda doc_type, pk: calls.append((doc_type, pk)))
    return calls


@pytest.fixture
def crm():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return api


@pytest.fixture
def public():
    return APIClient()  # без токена сервиса: право даёт только подпись ссылки


def make_document(company, deal, *, kind="CONTRACT", status="ISSUED", pdf=True, number=None) -> GeneratedDocument:
    kind_row, _ = DocumentTemplateKind.objects.get_or_create(code=kind, defaults={"name": kind})
    template, _ = DocumentTemplate.objects.get_or_create(
        company=company, name=f"Шаблон {kind}", defaults={"kind": kind_row}
    )
    status_row, _ = GeneratedDocumentStatus.objects.get_or_create(code=status, defaults={"name": status})
    count = GeneratedDocument.objects.count()
    document = GeneratedDocument.objects.create(
        company=company,
        deal=deal,
        template=template,
        status=status_row,
        number=number or f"DOC-FIX32-{count}",
        title=f"{kind} {count}",
    )
    if pdf:
        document.pdf_file.save(f"doc-{document.pk}.pdf", ContentFile(PDF), save=True)
    return document


@pytest.fixture
def world():
    company = make_company(crm_client_id=7001)
    deal = make_deal(company)
    return {"company": company, "deal": deal, "document": make_document(company, deal)}


def link_for(crm, document, context=CONTEXT):
    extra = {"HTTP_X_CRM_CONTEXT": context} if context is not None else {}
    return crm.get(f"{PREFIX}/documents/{document.pk}/link", **extra)


def token_of(url: str) -> str:
    return url.rsplit(f"{PUBLIC}/", 1)[1].rstrip("/")


def open_link(public, response, **extra):
    return public.get(f"{PUBLIC}/{token_of(response.json()['url'])}/", **extra)


# ── 1. Настоящая ссылка ─────────────────────────────────────────────────────────────────────────────


def test_link_is_signed_public_url_with_ten_minute_ttl(crm, world):
    before = timezone.now()
    response = link_for(crm, world["document"])
    assert response.status_code == 200
    body = response.json()
    assert not check_response(body, response_schema("/documents/{erp_document_id}/link"))
    assert body["url"].startswith(f"http://erp.localhost{PUBLIC}/") and body["url"].endswith("/")
    assert "token=link_" not in body["url"] and "/documents/" not in body["url"]
    expires = datetime.datetime.fromisoformat(body["expires_at"])
    assert datetime.timedelta(minutes=9, seconds=55) <= expires - before <= datetime.timedelta(minutes=10, seconds=5)
    assert body["content_type"] == "application/pdf"
    assert body["file_name"].endswith(".pdf")
    assert body["size_bytes"] == len(PDF), "размер настоящий, не выдуманный"


def test_link_streams_the_file(crm, public, world):
    response = open_link(public, link_for(crm, world["document"]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment")
    assert response["Cache-Control"] == "private, no-store"


def test_size_is_absent_while_the_pdf_is_not_rendered_and_render_is_queued(crm, world, render_calls):
    document = make_document(world["company"], world["deal"], pdf=False)
    body = link_for(crm, document).json()
    assert "size_bytes" not in body
    assert not check_response(body, response_schema("/documents/{erp_document_id}/link"))
    assert render_calls == [("generated", document.pk)]


def test_pdf_not_ready_is_202_with_retry_after_and_no_download_record(crm, public, world, render_calls):
    document = make_document(world["company"], world["deal"], pdf=False)
    issued = link_for(crm, document)
    response = open_link(public, issued)
    assert response.status_code == 202
    assert response.json() == {"detail": "DOCUMENT_PENDING"}
    assert response["Retry-After"] == "2"
    assert not ActivityLog.objects.filter(event_code="document.link_downloaded").exists()
    document.pdf_file.save("ready.pdf", ContentFile(PDF), save=True)  # рендер закончился — та же ссылка открывается
    assert open_link(public, issued).status_code == 200


def test_request_without_service_token_is_401(world):
    assert APIClient().get(f"{PREFIX}/documents/{world['document'].pk}/link").status_code == 401


# ── 2. Сквозные: id из списков открывается ──────────────────────────────────────────────────────────


def test_every_id_from_the_documents_list_opens(crm, public, world):
    deal = world["deal"]
    ids = {make_document(world["company"], deal, kind=kind).pk for kind in ("CONTRACT", "INVOICE", "ACT")}
    listed = crm.get(f"{PREFIX}/deals/{deal.pk}/documents").json()
    assert {item["erp_document_id"] for item in listed} == ids | {world["document"].pk}
    assert {item["kind"] for item in listed} == {"contract", "invoice", "act"}
    for item in listed:
        response = link_for(crm, GeneratedDocument(pk=item["erp_document_id"]))
        assert response.status_code == 200, item
        assert open_link(public, response).status_code == 200, item


def test_last_document_of_the_summary_opens(crm, public, world):
    summary = crm.get(f"{PREFIX}/companies/{world['company'].pk}/summary").json()
    document_id = summary["last_document"]["erp_document_id"]
    assert document_id == world["document"].pk
    assert open_link(public, link_for(crm, GeneratedDocument(pk=document_id))).status_code == 200


def test_list_and_summary_do_not_show_what_the_link_refuses(crm, world):
    company, deal = world["company"], world["deal"]
    hidden = [
        make_document(company, deal, status="DRAFT"),
        make_document(company, deal, status="CANCELLED"),
        make_document(company, deal, kind="LETTER"),
        make_document(company, deal, kind="REPORT"),
        make_document(company, deal, kind="CUSTOM"),
    ]
    listed = {item["erp_document_id"] for item in crm.get(f"{PREFIX}/deals/{deal.pk}/documents").json()}
    assert listed == {world["document"].pk}
    summary = crm.get(f"{PREFIX}/companies/{company.pk}/summary").json()
    assert summary["last_document"]["erp_document_id"] == world["document"].pk
    assert not any(d.pk in listed for d in hidden)


def test_listing_rule_is_the_portal_visibility_rule(world):
    """Список и ссылка считают «можно отдать клиенту» одинаково с порталом: расхождение — утечка или дыра."""
    company, deal = world["company"], world["deal"]
    for kind in ("CONTRACT", "INVOICE", "ACT", "LETTER", "REPORT", "CUSTOM"):
        for status in ("DRAFT", "ISSUED", "CANCELLED"):
            make_document(company, deal, kind=kind, status=status)
    linkable = set(documents_link.linkable_documents().values_list("pk", flat=True))
    for document in GeneratedDocument.objects.all():
        visible = find_client_document(company, encode_document_id("generated", document.pk)) is not None
        assert visible == (document.pk in linkable), (document.template.kind.code, document.status.code)


# ── 3. Отказы: все 404 ──────────────────────────────────────────────────────────────────────────────


def test_unknown_document_is_404(crm):
    response = crm.get(f"{PREFIX}/documents/999999/link")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_company_without_crm_mapping_is_404(crm, world):
    stranger = make_company("ООО Без сопоставления", crm_client_id=None)
    document = make_document(stranger, make_deal(stranger))
    assert not CrmClientMapping.objects.filter(company=stranger).exists()
    for context in (None, CONTEXT):
        response = link_for(crm, document, context)
        assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert not ActivityLog.objects.filter(event_code__startswith="document.link_").exists()


@pytest.mark.parametrize(
    "kind,status",
    [
        ("CONTRACT", "DRAFT"),
        ("INVOICE", "DRAFT"),
        ("ACT", "CANCELLED"),
        ("LETTER", "ISSUED"),
        ("REPORT", "ISSUED"),
        ("CUSTOM", "ISSUED"),
    ],
)
def test_draft_cancelled_and_internal_documents_are_404(crm, world, kind, status):
    document = make_document(world["company"], world["deal"], kind=kind, status=status)
    response = link_for(crm, document)
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert not ActivityLog.objects.filter(event_code__startswith="document.link_").exists()


def test_document_of_another_client_is_404(crm, world):
    """Заголовок называет клиента CRM, а документ чужой компании — неотличимо от несуществующего."""
    other = make_company("ООО Чужой", crm_client_id=7002)
    document = make_document(other, make_deal(other))
    assert link_for(crm, document, CONTEXT).status_code == 404  # CONTEXT — клиент 7001
    assert link_for(crm, document, json.dumps({"crm_client_id": 7002, "channel": "crm"})).status_code == 200


def test_garbage_context_does_not_break_issue_but_is_kept_in_the_journal(crm, world):
    response = link_for(crm, world["document"], context="not-json: erp-mcp:client=7001")
    assert response.status_code == 200
    log = ActivityLog.objects.get(event_code="document.link_issued")
    assert log.event_params["crm_client_id"] is None
    assert log.event_params["crm_context_raw"] == "not-json: erp-mcp:client=7001"


# ── 4. Токен ────────────────────────────────────────────────────────────────────────────────────────


def test_tampered_token_is_404(crm, public, world):
    token = token_of(link_for(crm, world["document"]).json()["url"])
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    for bad in (flipped, token[:-6], token + "x", "garbage", "a:b:c"):
        response = public.get(f"{PUBLIC}/{bad}/")
        assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}, bad
    assert not ActivityLog.objects.filter(event_code="document.link_downloaded").exists()


def test_token_signed_with_another_salt_is_404(public, world):
    payload = {"k": "generated", "d": world["document"].pk, "c": 7001, "exp": int(timezone.now().timestamp()) + 600}
    forged = signing.dumps(payload, salt="someone.else", compress=True)
    assert public.get(f"{PUBLIC}/{forged}/").status_code == 404


def test_token_with_changed_payload_cannot_be_forged_without_the_key(crm, public, world):
    """Подменить id в токене нельзя: подпись покрывает всё тело."""
    other = make_document(world["company"], world["deal"])
    token = token_of(link_for(crm, world["document"]).json()["url"])
    body = signing.loads(token, salt=documents_link.LINK_SALT)
    body["d"] = other.pk
    # тело нового токена (base64 без подписи) + подпись от старого токена
    forged_body = signing.dumps(body, salt=documents_link.LINK_SALT, compress=True).rsplit(":", 2)[0]
    forged = ":".join([forged_body, *token.rsplit(":", 2)[1:]])
    assert public.get(f"{PUBLIC}/{forged}/").status_code == 404


def test_bare_document_id_is_not_accepted(public, world):
    for bare in (str(world["document"].pk), f"{world['document'].pk}x", "link_1"):
        assert public.get(f"{PUBLIC}/{bare}/").status_code == 404


def test_expired_link_is_410_and_not_logged_as_download(crm, public, world, monkeypatch):
    issued = link_for(crm, world["document"])
    real_now = timezone.now()
    monkeypatch.setattr(documents_link.timezone, "now", lambda: real_now + datetime.timedelta(minutes=9, seconds=50))
    assert open_link(public, issued).status_code == 200, "до срока ссылка открывается"
    monkeypatch.setattr(documents_link.timezone, "now", lambda: real_now + datetime.timedelta(minutes=10, seconds=30))
    response = open_link(public, issued)
    assert response.status_code == 410 and response.json() == {"detail": "DOCUMENT_LINK_EXPIRED"}
    assert ActivityLog.objects.filter(event_code="document.link_downloaded").count() == 1


def test_document_cancelled_after_issue_does_not_open(crm, public, world):
    issued = link_for(crm, world["document"])
    GeneratedDocument.objects.filter(pk=world["document"].pk).update(
        status=GeneratedDocumentStatus.objects.get_or_create(code="CANCELLED", defaults={"name": "x"})[0]
    )
    assert open_link(public, issued).status_code == 404


def test_mapping_removed_after_issue_does_not_open(crm, public, world):
    issued = link_for(crm, world["document"])
    CrmClientMapping.objects.filter(company=world["company"]).delete()
    assert open_link(public, issued).status_code == 404


def test_link_of_one_client_does_not_open_after_the_document_moves_to_another(crm, public, world):
    issued = link_for(crm, world["document"])
    other = make_company("ООО Другой", crm_client_id=7003)
    GeneratedDocument.objects.filter(pk=world["document"].pk).update(company=other, deal=make_deal(other), contact=None)
    assert open_link(public, issued).status_code == 404


def test_public_route_is_throttled_like_public_documents(crm, public, world, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "public_document", "3/minute")
    statuses = [public.get(f"{PUBLIC}/guess-{n}/", REMOTE_ADDR="198.51.100.9").status_code for n in range(5)]
    assert statuses == [404, 404, 404, 429, 429]


# ── 5. Журнал ERP ───────────────────────────────────────────────────────────────────────────────────


def test_issue_and_every_download_are_written_to_the_erp_journal(crm, public, world):
    issued = link_for(crm, world["document"])
    document = world["document"]

    log = ActivityLog.objects.get(event_code="document.link_issued")
    assert (log.entity_type, log.entity_id, log.deal_id, log.company_id) == (
        "generated_document",
        document.pk,
        world["deal"].pk,
        world["company"].pk,
    )
    assert log.event_params == {
        "document_id": document.pk,
        "kind": "contract",
        "number": document.number,
        "crm_client_id": 7001,
        "crm_user_id": 55,
        "channel": "bot",
        "expires_at": issued.json()["expires_at"],
    }

    open_link(public, issued, REMOTE_ADDR="203.0.113.7")
    open_link(public, issued, REMOTE_ADDR="203.0.113.8")
    downloads = list(ActivityLog.objects.filter(event_code="document.link_downloaded").order_by("id"))
    assert len(downloads) == 2, "каждое скачивание — отдельная запись"
    assert [d.event_params["ip"] for d in downloads] == ["203.0.113.7", "203.0.113.8"]
    for download in downloads:
        assert download.event_params["crm_client_id"] == 7001
        assert download.event_params["crm_user_id"] == 55
        assert download.event_params["channel"] == "bot"
        assert download.event_params["document_id"] == document.pk
        assert (download.entity_id, download.deal_id, download.company_id) == (
            document.pk,
            world["deal"].pk,
            world["company"].pk,
        )


def test_every_issue_is_a_separate_journal_record(crm, world):
    for _ in range(3):
        link_for(crm, world["document"])
    assert ActivityLog.objects.filter(event_code="document.link_issued").count() == 3


def test_context_without_header_is_journaled_as_empty_not_invented(crm, world):
    assert link_for(crm, world["document"], context=None).status_code == 200
    params = ActivityLog.objects.get(event_code="document.link_issued").event_params
    assert (params["crm_client_id"], params["crm_user_id"], params["channel"]) == (None, None, None)


@pytest.mark.parametrize(
    "context",
    ['{"crm_client_id": "7001"}', '{"crm_client_id": true}', '{"crm_client_id": -1}', "[1, 2]", '{"channel": "sms"}'],
)
def test_malformed_context_fields_are_dropped_not_trusted(crm, world, context):
    assert link_for(crm, world["document"], context=context).status_code == 200
    params = ActivityLog.objects.get(event_code="document.link_issued").event_params
    assert params["crm_client_id"] is None and params["channel"] is None
