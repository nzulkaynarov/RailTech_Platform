"""Документы портала (FIX-23, P-12): только выпущенные, фильтры, PDF существующим рендером, аудит выдачи.

Мир фикстур (`contract_world` + `documents_world`) заводит документы всех видов в обоих состояниях — и то, что клиент
обязан видеть, и то, чего видеть не должен (черновики, КП до отправки, аннулированные, письма и рапорты, чужая компания).
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from portal.services import documents as service
from portal.tests.contract_support import check_response, component

from crm.constants import QuoteStatusCode
from crm.models import ActivityLog, Quote

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"


@pytest.fixture
def render_calls(monkeypatch):
    """Брокера в тестах нет: перехватываем постановку рендера и запоминаем (тип документа, id источника)."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr("crm.tasks.render_document_pdf.delay", lambda doc_type, pk: calls.append((doc_type, pk)))
    from django.core.cache import cache

    cache.clear()
    return calls


def listed(client, **params):
    response = client.get(f"{API}/documents", params)
    assert response.status_code == 200, response.content
    return response.json()


# ── Идентификатор ────────────────────────────────────────────────────────────────────────────────


def test_document_kinds_mirror_the_contract_enum():
    assert set(service.DOCUMENT_KINDS) == set(component("DocumentKind")["enum"])


@pytest.mark.parametrize("source", sorted(service.SLOT_BY_SOURCE))
def test_document_id_round_trips(source):
    document_id = service.encode_document_id(source, 4242)
    assert service.decode_document_id(document_id) == (source, 4242)


@pytest.mark.parametrize("document_id", [0, 1, 6, 7, -5])
def test_document_id_nobody_issued_does_not_decode(document_id):
    # pk < 1 или слот без источника (6 и 7) — не документ
    assert service.decode_document_id(document_id) is None


# ── GET /documents: только выпущенные ───────────────────────────────────────────────────────────


def test_list_has_exactly_the_issued_documents(contract_world, portal_client):
    ids = {item["id"] for item in listed(portal_client)}
    assert ids == set(contract_world["documents"].values())


def test_drafts_and_internal_documents_never_listed(contract_world, portal_client):
    ids = {item["id"] for item in listed(portal_client)}
    hidden = contract_world["hidden_documents"]
    assert hidden, "в мире должны быть заведены черновики и внутренние документы"
    assert not ids & set(hidden.values())


@pytest.mark.parametrize(
    "key",
    [
        "quote_draft",
        "quote_pending_approval",
        "quote_ready_to_send",
        "contract_draft",
        "contract_cancelled",
        "invoice_draft",
        "invoice_not_issued",
        "quote_hidden_draft",
        "quote_hidden_pending_trade_review",
        "quote_hidden_sent_without_link",
        "act_draft",
        "act_cancelled",
        "waybill_assembling",
        "generated_letter",
        "generated_report",
        "generated_custom",
        "generated_draft",
        "generated_cancelled",
        "other_company_quote",
        "other_company_invoice",
    ],
)
def test_hidden_document_is_404_by_id(contract_world, portal_client, key, render_calls):
    response = portal_client.get(f"{API}/documents/{contract_world['hidden_documents'][key]}/file")
    assert response.status_code == 404
    assert response.json() == {"detail": "NOT_FOUND"}
    assert render_calls == [], "для скрытого документа рендер не ставится"
    assert not ActivityLog.objects.filter(event_code="document.downloaded_by_client").exists()


def test_quote_is_a_document_only_after_it_was_sent(contract_world, portal_client):
    kinds = {item["id"]: item["kind"] for item in listed(portal_client)}
    for key in ("sent", "viewed", "accepted", "rejected", "expired"):
        assert kinds[contract_world["documents"][f"quote_{key}"]] == "quote"


def test_quote_expired_by_the_beat_task_is_still_a_document(contract_world, portal_client):
    """Статус `EXPIRED` ставит ежедневная задача `crm.expire_stale_quotes`: наутро после срока PDF не пропадает."""
    document_id = contract_world["documents"]["quote_expired_status"]
    item = next(i for i in listed(portal_client) if i["id"] == document_id)
    assert item["kind"] == "quote"
    response = portal_client.get(f"{API}/documents/{document_id}/file")
    assert response.status_code == 200 and response["Content-Type"].startswith("application/pdf")


def test_quote_pdf_reference_survives_expiry(contract_world, portal_client):
    from crm.models import QuoteStatus

    quote = contract_world["quotes"]["sent"]
    quote.status = QuoteStatus.objects.get(code="EXPIRED")
    quote.save()
    detail = portal_client.get(f"{API}/quotes/{quote.pk}").json()
    assert detail["pdf_document_id"] == contract_world["documents"]["quote_sent"]


def test_returned_act_is_still_a_document(contract_world, portal_client):
    """Возвращённый клиентом акт ERP хранит черновиком с причиной, но клиент его получал."""
    ids = {item["id"] for item in listed(portal_client)}
    assert contract_world["documents"]["act_returned"] in ids


def test_documents_are_newest_first(contract_world, portal_client):
    dates = [item["date"] for item in listed(portal_client)]
    assert dates == sorted(dates, reverse=True)


def test_list_matches_contract_schema(contract_world, portal_client):
    schema = component("Document")
    problems = [p for item in listed(portal_client) for p in check_response(item, schema)]
    assert not problems, problems


def test_item_fields(contract_world, portal_client):
    item = next(i for i in listed(portal_client) if i["id"] == contract_world["documents"]["contract_signed"])
    contract = contract_world["contracts"]["signed"]
    assert item["kind"] == "contract" and item["number"] == contract.number
    assert item["title"] == f"Договор {contract.number}"
    assert item["deal"] == {"id": contract.deal_id, "number": f"D-{contract.deal_id}", "title": contract.deal.title}
    assert "deal_id" not in item
    assert item["file_name"] == "CT-GUARD-signed.pdf"
    assert item["size_bytes"] == len(b"%PDF-1.4 fake")


def test_size_is_zero_until_pdf_is_rendered(contract_world, portal_client):
    item = next(i for i in listed(portal_client) if i["id"] == contract_world["documents"]["contract_sent"])
    assert item["size_bytes"] == 0


def test_document_without_deal_has_null_deal(contract_world, portal_client):
    item = next(i for i in listed(portal_client) if i["id"] == contract_world["documents"]["generated_no_deal"])
    assert item["deal"] is None and "deal_id" not in item and item["kind"] == "act"


def test_titles_follow_contact_language(contract_world, portal_client, client_contact):
    client_contact.language = "en"
    client_contact.save(update_fields=["language"])
    titles = {i["id"]: i["title"] for i in listed(portal_client)}
    assert titles[contract_world["documents"]["contract_signed"]].startswith("Contract ")
    assert titles[contract_world["documents"]["invoice_paid"]].startswith("Invoice ")
    assert titles[contract_world["documents"]["waybill_shipped"]].startswith("Delivery note ")


# ── Фильтры ──────────────────────────────────────────────────────────────────────────────────────


#: Вид выпущенных `GeneratedDocument` мира: договор, счёт и акт — по виду шаблона.
GENERATED_KINDS = {"generated_contract": "contract", "generated_pending": "invoice", "generated_no_deal": "act"}


@pytest.mark.parametrize("kind", ["quote", "contract", "invoice", "act", "waybill"])
def test_kind_filter(contract_world, portal_client, kind):
    expected = {
        pk for key, pk in contract_world["documents"].items() if GENERATED_KINDS.get(key, key.split("_")[0]) == kind
    }
    assert expected
    assert {item["id"] for item in listed(portal_client, kind=kind)} == expected


@pytest.mark.parametrize("kind", ["specification", "receipt", "other"])
def test_kind_without_source_is_an_empty_list(contract_world, portal_client, kind):
    assert listed(portal_client, kind=kind) == []


def test_unknown_kind_is_422(contract_world, portal_client):
    response = portal_client.get(f"{API}/documents", {"kind": "passport"})
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


def test_deal_id_filter(contract_world, portal_client):
    main = contract_world["main"]
    items = listed(portal_client, deal_id=main.pk)
    assert items and {item["deal"]["id"] for item in items} == {main.pk}
    assert contract_world["documents"]["contract_signed"] in {i["id"] for i in items}
    assert contract_world["documents"]["quote_delivery_shipped"] not in {i["id"] for i in items}


def test_deal_id_and_kind_combine(contract_world, portal_client):
    items = listed(portal_client, deal_id=contract_world["main"].pk, kind="invoice")
    assert items and {(i["kind"], i["deal"]["id"]) for i in items} == {("invoice", contract_world["main"].pk)}


def test_deal_id_of_another_company_is_an_empty_list_not_a_leak(contract_world, portal_client):
    assert listed(portal_client, deal_id=contract_world["other"]["deal"].pk) == []


@pytest.mark.parametrize("deal_id", ["0", "-1", str(10**30)])
def test_deal_id_out_of_range_is_an_empty_list(contract_world, portal_client, deal_id):
    assert listed(portal_client, deal_id=deal_id) == []


def test_list_does_not_query_per_document(contract_world, portal_client, django_assert_max_num_queries):
    """Список — по запросу на источник, а не на документ (в мире их десятки)."""
    assert len(listed(portal_client)) >= 30
    with django_assert_max_num_queries(20):
        portal_client.get(f"{API}/documents")


def test_deal_id_not_a_number_is_422(contract_world, portal_client):
    response = portal_client.get(f"{API}/documents", {"deal_id": "abc"})
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


def test_other_company_sees_only_its_own_documents(contract_world, other_portal_client):
    items = listed(other_portal_client)
    assert {i["id"] for i in items} == {
        contract_world["hidden_documents"]["other_company_quote"],
        contract_world["hidden_documents"]["other_company_invoice"],
    }


# ── GET /documents/{id}/file ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    ["quote_sent", "contract_signed", "invoice_paid", "act_accepted", "waybill_shipped", "generated_contract"],
)
def test_ready_pdf_is_streamed(contract_world, portal_client, render_calls, key):
    document_id = contract_world["ready_documents"][key]
    response = portal_client.get(f"{API}/documents/{document_id}/file")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/pdf")
    assert b"".join(response.streaming_content) == b"%PDF-1.4 fake"
    item = next(i for i in listed(portal_client) if i["id"] == document_id)
    assert item["file_name"] in unquote(response["Content-Disposition"])
    assert render_calls == []


@pytest.mark.parametrize(
    ("key", "render_type"),
    [
        ("quote_viewed", "quote"),
        ("contract_sent", "contract"),
        ("invoice_overdue", "invoice"),
        ("act_issued", "act"),
        ("waybill_in_transit", "delivery_note"),
        ("generated_pending", "generated"),
    ],
)
def test_pdf_not_ready_is_202_and_render_is_queued(contract_world, portal_client, render_calls, key, render_type):
    document_id = contract_world["documents"][key]
    response = portal_client.get(f"{API}/documents/{document_id}/file")
    assert response.status_code == 202
    assert response.json() == {"detail": "DOCUMENT_PENDING"}
    assert response["Retry-After"] == str(service.RETRY_AFTER_SECONDS)
    source, pk = service.decode_document_id(document_id)
    assert render_calls == [(render_type, pk)], "202 — это постановка рендера в очередь, а не пустой ответ"
    assert not ActivityLog.objects.filter(event_code="document.downloaded_by_client").exists()


def test_polling_does_not_flood_the_render_queue(contract_world, portal_client, render_calls):
    document_id = contract_world["documents"]["contract_sent"]
    for _ in range(3):
        assert portal_client.get(f"{API}/documents/{document_id}/file").status_code == 202
    assert len(render_calls) == 1


def test_lost_pdf_in_storage_is_rendered_again(contract_world, portal_client, render_calls):
    contract = contract_world["contracts"]["signed"]
    contract.pdf_file.storage.delete(contract.pdf_file.name)  # имя в базе осталось, файла в хранилище нет
    response = portal_client.get(f"{API}/documents/{contract_world['documents']['contract_signed']}/file")
    assert response.status_code == 202
    assert render_calls == [("contract", contract.pk)]


def test_quote_pdf_is_the_client_projection_file(contract_world, portal_client, render_calls):
    quote = contract_world["quotes"]["sent"]
    response = portal_client.get(f"{API}/documents/{contract_world['documents']['quote_sent']}/file")
    assert response.status_code == 200
    from crm.services.documents import quote_pdf_filename

    assert quote_pdf_filename(quote) in unquote(response["Content-Disposition"])


@pytest.mark.parametrize("document_id", [0, 7, 999999999, -1, 10**30])
def test_unknown_document_id_is_404(contract_world, portal_client, document_id):
    assert portal_client.get(f"{API}/documents/{document_id}/file").status_code == 404


def test_other_company_document_file_is_404(contract_world, other_portal_client, render_calls):
    for key in ("contract_signed", "invoice_paid", "quote_sent", "generated_contract"):
        response = other_portal_client.get(f"{API}/documents/{contract_world['documents'][key]}/file")
        assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert render_calls == []


def test_foreign_session_without_cookie_is_401(contract_world, anon_portal_client):
    response = anon_portal_client.get(f"{API}/documents/{contract_world['documents']['contract_signed']}/file")
    assert response.status_code == 401
    assert anon_portal_client.get(f"{API}/documents").status_code == 401


def test_read_only_contact_can_read_and_download(contract_world, readonly_portal_client):
    """Просмотр и скачивание — чтение: `can_act=false` их не закрывает (403 — только мутациям)."""
    assert readonly_portal_client.get(f"{API}/documents").status_code == 200
    response = readonly_portal_client.get(f"{API}/documents/{contract_world['documents']['contract_signed']}/file")
    assert response.status_code == 200


# ── Аудит выдачи ─────────────────────────────────────────────────────────────────────────────────


def test_every_issue_is_audited_with_who_what_when(contract_world, portal_client, client_contact, client_session):
    document_id = contract_world["documents"]["contract_signed"]
    portal_client.get(f"{API}/documents/{document_id}/file", REMOTE_ADDR="203.0.113.7")
    portal_client.get(f"{API}/documents/{document_id}/file", REMOTE_ADDR="203.0.113.7")

    logs = list(ActivityLog.objects.filter(event_code="document.downloaded_by_client").order_by("id"))
    assert len(logs) == 2, "каждая выдача — отдельная запись"
    log = logs[0]
    contract = contract_world["contracts"]["signed"]
    assert log.contact_id == client_contact.pk and log.company_id == client_contact.company_id  # кто
    assert (log.entity_type, log.entity_id, log.deal_id) == ("contract", contract.pk, contract.deal_id)  # что
    assert log.event_params == {
        "document_id": document_id,
        "kind": "contract",
        "number": contract.number,
        "contact_id": client_contact.pk,
        "contact_name": client_contact.name,
        "session_id": client_session.pk,
        "ip": "203.0.113.7",
    }
    assert log.timestamp is not None  # когда
    assert log.user_id is None, "клиент портала — не сотрудник"


def test_audit_of_a_document_without_deal(contract_world, portal_client, client_contact):
    portal_client.get(f"{API}/documents/{contract_world['ready_documents']['generated_contract']}/file")
    log = ActivityLog.objects.get(event_code="document.downloaded_by_client")
    assert log.entity_type == "generated" and log.contact_id == client_contact.pk


# ── Идентификаторы в ответах про КП, договоры, счета, акты ────────────────────────────────────────


def test_documents_referenced_from_entities_are_reachable_by_id(contract_world, portal_client, render_calls):
    """Q-FIX21-1: `document_id` / `pdf_document_id` ведут на документ из списка, а тот отдаётся по `/file`."""
    known = {item["id"]: item for item in listed(portal_client)}
    seen: list[int] = []
    for path in ("contracts", "invoices", "acts"):
        for item in portal_client.get(f"{API}/{path}").json():
            if item["document_id"] is not None:
                seen.append(item["document_id"])
                assert known[item["document_id"]]["number"] == item["number"]
    for quote in portal_client.get(f"{API}/quotes").json():
        detail = portal_client.get(f"{API}/quotes/{quote['id']}").json()
        if detail["pdf_document_id"] is not None:
            seen.append(detail["pdf_document_id"])
            assert known[detail["pdf_document_id"]]["kind"] == "quote"
    assert seen, "хотя бы часть сущностей мира обязана ссылаться на документ"
    for document_id in seen:
        assert portal_client.get(f"{API}/documents/{document_id}/file").status_code in (200, 202)


@pytest.mark.parametrize(
    ("path", "key", "expected_key"),
    [
        ("contracts", "signed", "contract_signed"),
        ("contracts", "sent", "contract_sent"),
        ("invoices", "paid", "invoice_paid"),
        ("acts", "accepted", "act_accepted"),
        ("acts", "returned", "act_returned"),
    ],
)
def test_entity_points_at_its_document(contract_world, portal_client, path, key, expected_key):
    obj = contract_world[path][key]
    item = next(i for i in portal_client.get(f"{API}/{path}").json() if i["id"] == obj.pk)
    assert item["document_id"] == contract_world["documents"][expected_key]


def test_cancelled_invoice_is_listed_and_has_its_document_like_the_invoice_list(contract_world, portal_client):
    """Видимость одна: счёт в `GET /invoices` (в том числе аннулированный) — документ в `GET /documents`."""
    invoice = contract_world["invoices"]["cancelled"]
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["status"] == "cancelled" and item["document_id"] == contract_world["documents"]["invoice_cancelled"]


@pytest.mark.parametrize(
    ("path", "source", "model_path"),
    [
        ("quotes", "quote", "crm.models.Quote"),
        ("contracts", "contract", "crm.models.Contract"),
        ("invoices", "invoice", "crm.models.Invoice"),
        ("acts", "act", "crm.models.Act"),
    ],
)
def test_visibility_in_documents_equals_visibility_in_the_entity_lists(
    contract_world, portal_client, path, source, model_path
):
    """Для КП, договоров, счетов и актов: записи, которые клиент видит в своём списке, — ровно те, у которых есть документ."""
    import importlib

    module, name = model_path.rsplit(".", 1)
    model = getattr(importlib.import_module(module), name)
    visible = {item["id"] for item in portal_client.get(f"{API}/{path}").json()}
    in_documents = {
        service.decode_document_id(i["id"])[1]
        for i in listed(portal_client)
        if service.decode_document_id(i["id"])[0] == source
    }
    assert visible and visible == in_documents
    # и поштучно: предикат записи совпадает с запросом списка
    for obj in model.objects.filter(deal__company=contract_world["company"]).select_related("status", "deal"):
        assert (service.document_id_for(source, obj) is not None) == (obj.pk in visible), f"{source} #{obj.pk}"


def test_quote_pdf_reference(contract_world, portal_client):
    sent = contract_world["quotes"]["sent"]
    detail = portal_client.get(f"{API}/quotes/{sent.pk}").json()
    assert detail["pdf_document_id"] == contract_world["documents"]["quote_sent"]


def test_act_scan_reference_is_the_documents_id_and_leads_to_the_file(contract_world, portal_client):
    """`scan_document_id` — id из `GET /documents` (закодированный, не сырой pk `GeneratedDocument`)."""
    act = contract_world["acts"]["accepted"]
    item = next(i for i in portal_client.get(f"{API}/acts").json() if i["id"] == act.pk)
    scan = contract_world["scan_document"]
    assert item["scan_document_id"] == contract_world["documents"]["act_scan"] != scan.pk
    assert item["scan_document_id"] in {i["id"] for i in listed(portal_client)}
    response = portal_client.get(f"{API}/documents/{item['scan_document_id']}/file")
    assert response.status_code == 200 and b"".join(response.streaming_content) == b"%PDF-1.4 scan"
    plain = next(i for i in portal_client.get(f"{API}/acts").json() if i["id"] == contract_world["acts"]["issued"].pk)
    assert plain["scan_document_id"] is None


def test_scan_is_found_only_by_its_deal_and_source(contract_world, portal_client):
    """Документ с номером `SCAN-<акт>`, но чужой сделки или не заведённый приёмкой, ссылкой на скан не становится."""
    from documents.models import GeneratedDocument
    from portal.services.act_scan import annotate_scan_documents

    act = contract_world["acts"]["accepted"]
    scan = contract_world["scan_document"]
    GeneratedDocument.objects.filter(pk=scan.pk).update(values={"source": "something_else"})
    annotate_scan_documents([act])
    assert act.portal_scan_document_id is None
    GeneratedDocument.objects.filter(pk=scan.pk).update(values={"source": "portal_scan"}, deal=contract_world["closed"])
    act = type(act).objects.get(pk=act.pk)
    annotate_scan_documents([act])
    assert act.portal_scan_document_id is None


def _scan_with_file(contract_world, name, content):
    from django.core.files.base import ContentFile

    scan = contract_world["scan_document"]
    scan.pdf_file.save(name, ContentFile(content), save=True)
    return contract_world["documents"]["act_scan"]


def test_image_scan_keeps_its_content_type_and_extension(contract_world, portal_client, render_calls):
    document_id = _scan_with_file(contract_world, "photo.png", b"\x89PNG\r\n\x1a\nfake")
    item = next(i for i in listed(portal_client) if i["id"] == document_id)
    assert item["file_name"] == "SCAN-ACT-GUARD-accepted.png"
    response = portal_client.get(f"{API}/documents/{document_id}/file")
    assert response.status_code == 200 and response["Content-Type"] == "image/png"
    assert ".png" in unquote(response["Content-Disposition"]) and ".pdf" not in unquote(response["Content-Disposition"])
    assert render_calls == []


def test_pdf_scan_is_a_pdf_with_pdf_name(contract_world, portal_client):
    item = next(i for i in listed(portal_client) if i["id"] == contract_world["documents"]["act_scan"])
    assert item["file_name"] == "SCAN-ACT-GUARD-accepted.pdf"
    response = portal_client.get(f"{API}/documents/{item['id']}/file")
    assert response["Content-Type"].startswith("application/pdf")


def test_scan_without_a_file_is_404_and_never_rendered(contract_world, portal_client, render_calls):
    """Рендер скана записал бы в `pdf_file` пустой бланк и потерял ссылку на `Act.signed_file`: 404, очереди нет."""
    from documents.models import GeneratedDocument

    scan = contract_world["scan_document"]
    GeneratedDocument.objects.filter(pk=scan.pk).update(pdf_file="")
    document_id = contract_world["documents"]["act_scan"]
    response = portal_client.get(f"{API}/documents/{document_id}/file")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert render_calls == []
    assert not ActivityLog.objects.filter(event_code="document.downloaded_by_client").exists()


def test_scan_whose_file_vanished_from_storage_is_404_and_keeps_the_reference(
    contract_world, portal_client, render_calls
):
    from documents.models import GeneratedDocument

    scan = contract_world["scan_document"]
    scan.pdf_file.storage.delete(scan.pdf_file.name)
    document_id = contract_world["documents"]["act_scan"]
    assert portal_client.get(f"{API}/documents/{document_id}/file").status_code == 404
    assert GeneratedDocument.objects.get(pk=scan.pk).pdf_file.name == scan.pdf_file.name
    assert render_calls == []


def test_quote_becomes_a_document_when_sent(contract_world, portal_client):
    """КП отправлено — документ появился; пока оно в согласовании — нет ни его, ни ссылки."""
    deal = contract_world["internal_deal"]
    quote = Quote.objects.get(deal=deal, version=1)  # DRAFT
    assert service.document_id_for("quote", quote) is None
    from crm.models import QuoteStatus

    quote.status = QuoteStatus.objects.get(code=QuoteStatusCode.SENT)
    quote.save()
    assert (
        service.document_id_for("quote", quote) is None
    ), "отправленное без публичной ссылки — аномалия, как в /quotes"
    quote.public_access_token = "t" * 32
    quote.save()
    assert service.document_id_for("quote", quote) == service.encode_document_id("quote", quote.pk)
    assert service.encode_document_id("quote", quote.pk) in {i["id"] for i in listed(portal_client)}


# ── Накладная: номер при выпуске (FIX-55, m2 D-6) ───────────────────────────────────────────────


def test_waybill_shipped_before_numbering_gets_its_final_number_in_the_list(
    contract_world, portal_client, render_calls, django_capture_on_commit_callbacks
):
    """Отгрузка, выпущенная без номера и без файла, в списке получает итоговый номер (не `DN-<id>`), рендер ставится,
    и номер не меняется после повторного запроса и рендера."""
    from crm.models import Fulfillment

    fulfillment = contract_world["deliveries"]["in_transit"]
    Fulfillment.objects.filter(pk=fulfillment.pk).update(note_number="")
    document_id = contract_world["documents"]["waybill_in_transit"]

    with django_capture_on_commit_callbacks(execute=True):
        first = next(i for i in listed(portal_client) if i["id"] == document_id)
    fulfillment.refresh_from_db()

    assert fulfillment.note_number, "номер присвоен при первом показе"
    assert first["number"] == fulfillment.note_number != f"DN-{fulfillment.pk}"
    assert ("delivery_note", fulfillment.pk) in render_calls

    second = next(i for i in listed(portal_client) if i["id"] == document_id)
    assert second["number"] == first["number"]
    assert render_calls.count(("delivery_note", fulfillment.pk)) == 1


def test_already_numbered_waybill_keeps_its_number(contract_world, portal_client, render_calls):
    fulfillment = contract_world["deliveries"]["shipped"]
    document_id = contract_world["documents"]["waybill_shipped"]

    item = next(i for i in listed(portal_client) if i["id"] == document_id)

    assert item["number"] == "DN-GUARD-shipped"
    assert ("delivery_note", fulfillment.pk) not in render_calls
