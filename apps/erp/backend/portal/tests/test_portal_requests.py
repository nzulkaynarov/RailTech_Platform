"""`POST /requests` (FIX-23, P-15): без выдуманных «1 шт», без 500, с событием `request.created(source=cabinet)`.

Что держат тесты: количество — десятичная строка или `null` (ничего не подставляется), плохой ввод — 422
`VALIDATION_ERROR` (а не 500 на `InvalidOperation`), `summary` ≤ 5000, вложения только по `upload_id` из `PortalUpload` своей
компании (`UPLOAD_NOT_FOUND`), строки и вложения сохраняются и возвращаются в `GET /requests/{id}`, источник — по факту.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from portal.models import PortalRequestLine, PortalRequestSummary, PortalUpload
from portal.tests.contract_support import check_response, component

from crm.models import ActivityLog, Deal
from sourcing.models import Attachment

pytestmark = pytest.mark.django_db

URL = "/api/portal/v1/requests"


def post(client, **fields):
    data = {"summary": "Нужны трубы 89х4", "lines": []}
    data.update(fields)
    return client.post(URL, data, format="json")


def line(text="Труба 89х4", **fields):
    return {"text": text, **fields}


def upload(client, name="spec.pdf", content=b"%PDF-1.4 spec"):
    response = client.post(
        "/api/portal/v1/uploads",
        {"file": SimpleUploadedFile(name, content, content_type="application/pdf")},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    return response.json()


def assert_nothing_created(company):
    assert not Deal.objects.filter(company=company).exists()
    assert not PortalRequestLine.objects.exists()
    assert not IntegrationWebhookEvent.objects.filter(event_type="request.created").exists()


# ── Количество: строка или null, без выдумок ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sent", "stored", "returned"),
    [
        ("150", Decimal("150"), "150"),
        ("150.5", Decimal("150.5"), "150.5"),
        ("0.001", Decimal("0.001"), "0.001"),
        ("999999999.999", Decimal("999999999.999"), "999999999.999"),
        ("10.000", Decimal("10"), "10"),
        (None, None, None),
    ],
)
def test_quantity_is_a_decimal_string_or_null(portal_client, sent, stored, returned):
    response = post(portal_client, lines=[line(quantity=sent, unit="м")])
    assert response.status_code == 201, response.content
    assert response.json()["lines"] == [{"text": "Труба 89х4", "quantity": returned, "unit": "м"}]
    assert PortalRequestLine.objects.get().quantity == stored


def test_missing_quantity_and_unit_are_not_invented(portal_client):
    response = post(portal_client, lines=[line()])
    assert response.status_code == 201
    stored = PortalRequestLine.objects.get()
    assert stored.quantity is None and stored.unit == ""
    assert response.json()["lines"] == [{"text": "Труба 89х4", "quantity": None, "unit": None}]


def test_null_unit_is_accepted(portal_client):
    response = post(portal_client, lines=[line(quantity="2", unit=None)])
    assert response.status_code == 201
    assert response.json()["lines"][0]["unit"] is None


@pytest.mark.parametrize(
    "quantity",
    [
        "abc",
        "",
        "  ",
        "-5",
        "0",
        "0.000",
        "1e3",
        "1,5",
        "NaN",
        "Infinity",
        "-Infinity",
        "12345678901",  # 11 цифр до запятой: не помещается в DecimalField(12, 3)
        "1.0001",  # четыре знака после запятой: молча округлять нельзя
        "١٢٣",  # арабо-индийские цифры
        "5 шт",
        150,  # число вместо строки: контракт — строка
        1.5,
        True,
        [],
        {},
    ],
)
def test_bad_quantity_is_422_not_500(portal_client, client_company, quantity):
    response = post(portal_client, lines=[line(quantity=quantity)])
    assert response.status_code == 422, response.content
    assert response.json() == {"detail": "VALIDATION_ERROR"}
    assert_nothing_created(client_company)


@pytest.mark.parametrize(
    "bad_line",
    [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 1001}, {"text": 5}, {"quantity": "1"}, "строка", None, 5],
)
def test_bad_line_is_422(portal_client, client_company, bad_line):
    response = post(portal_client, lines=[bad_line])
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    assert_nothing_created(client_company)


def test_line_text_up_to_the_contract_limit_is_stored(portal_client):
    """Контракт разрешает 1000 знаков в строке (`RequestLineIn.text`); поле базы раньше резало на 500 → 500 Server Error."""
    text = "Ш" * 1000
    response = post(portal_client, lines=[line(text, quantity="1")])
    assert response.status_code == 201, response.content
    assert PortalRequestLine.objects.get().text == text
    assert response.json()["lines"][0]["text"] == text


def test_unit_longer_than_the_field_is_422(portal_client, client_company):
    response = post(portal_client, lines=[line(unit="м" * 51)])
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    assert_nothing_created(client_company)


def test_lines_may_be_empty_or_omitted(portal_client, client_company):
    """Контракт перечисляет `lines` обязательным, но пустой список допускает; отсутствие поля читаем как «строк нет»."""
    assert post(portal_client, lines=[]).status_code == 201
    omitted = portal_client.post(URL, {"summary": "Без строк"}, format="json")
    assert omitted.status_code == 201 and omitted.json()["lines"] == []


def test_lines_keep_their_order(portal_client):
    texts = ["Первая", "Вторая", "Третья"]
    created = post(portal_client, lines=[line(t) for t in texts]).json()
    assert [row["text"] for row in created["lines"]] == texts
    detail = portal_client.get(f"{URL}/{created['id']}").json()
    assert [row["text"] for row in detail["lines"]] == texts


# ── summary ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("length", [1, 255, 256, 5000])
def test_summary_up_to_5000_is_kept_whole(portal_client, length):
    summary = "а" * length
    response = post(portal_client, summary=summary)
    assert response.status_code == 201, response.content
    assert response.json()["summary"] == summary
    deal = Deal.objects.get()
    assert len(deal.title) <= 255
    assert PortalRequestSummary.objects.get(deal=deal).text == summary
    assert portal_client.get(f"{URL}/{deal.pk}").json()["summary"] == summary


@pytest.mark.parametrize("summary", ["", "   ", "а" * 5001, None, 5, ["x"]])
def test_bad_summary_is_422(portal_client, client_company, summary):
    response = post(portal_client, summary=summary)
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    assert_nothing_created(client_company)


# ── Вложения ─────────────────────────────────────────────────────────────────────────────────────


def test_attachment_by_upload_id_is_saved_and_returned(portal_client, client_company):
    uploaded = upload(portal_client)
    response = post(portal_client, attachments=[{"upload_id": uploaded["upload_id"], "name": "spec.pdf"}])
    assert response.status_code == 201, response.content
    assert response.json()["attachments"] == [{"upload_id": uploaded["upload_id"], "name": "spec.pdf"}]

    deal = Deal.objects.get()
    stored = PortalUpload.objects.get(upload_id=uploaded["upload_id"])
    assert stored.deal_id == deal.pk
    attachment = Attachment.objects.get(deal=deal)
    assert attachment.original_filename == "spec.pdf" and attachment.kind == "SOURCE"
    assert attachment.file.read() == b"%PDF-1.4 spec"

    detail = portal_client.get(f"{URL}/{deal.pk}").json()
    assert detail["attachments"] == [{"upload_id": uploaded["upload_id"], "name": "spec.pdf"}]


def test_attachment_name_comes_from_the_upload_not_from_the_client(portal_client):
    uploaded = upload(portal_client, name="real.pdf")
    response = post(portal_client, attachments=[{"upload_id": uploaded["upload_id"], "name": "подделка.exe"}])
    assert response.status_code == 201
    assert response.json()["attachments"] == [{"upload_id": uploaded["upload_id"], "name": "real.pdf"}]


def test_several_attachments_and_a_repeated_one(portal_client):
    first, second = upload(portal_client, "a.pdf"), upload(portal_client, "b.pdf")
    refs = [{"upload_id": u["upload_id"], "name": u["name"]} for u in (first, second, first)]
    response = post(portal_client, attachments=refs)
    assert response.status_code == 201
    assert sorted(a["name"] for a in response.json()["attachments"]) == ["a.pdf", "b.pdf"]
    assert Attachment.objects.count() == 2


@pytest.mark.parametrize("upload_id", [str(uuid.uuid4()), "not-a-uuid", "1; DROP TABLE", "{}", "0" * 36])
def test_unknown_upload_is_422_upload_not_found(portal_client, client_company, upload_id):
    response = post(portal_client, attachments=[{"upload_id": upload_id, "name": "x.pdf"}])
    assert response.status_code == 422, response.content
    assert response.json() == {"detail": "UPLOAD_NOT_FOUND"}
    assert_nothing_created(client_company)
    assert not Attachment.objects.exists()


def test_upload_of_another_company_is_not_found(portal_client, other_portal_client, client_company):
    foreign = upload(other_portal_client)
    response = post(portal_client, attachments=[{"upload_id": foreign["upload_id"], "name": "x.pdf"}])
    assert response.status_code == 422 and response.json() == {"detail": "UPLOAD_NOT_FOUND"}
    assert PortalUpload.objects.get(upload_id=foreign["upload_id"]).deal_id is None, "чужой файл не присваивается"
    assert_nothing_created(client_company)


def test_upload_is_consumed_by_one_request(portal_client, client_company):
    uploaded = upload(portal_client)
    ref = [{"upload_id": uploaded["upload_id"], "name": "spec.pdf"}]
    first = post(portal_client, attachments=ref)
    assert first.status_code == 201
    second = post(portal_client, attachments=ref)
    assert second.status_code == 422 and second.json() == {"detail": "UPLOAD_NOT_FOUND"}
    assert Deal.objects.filter(company=client_company).count() == 1
    assert PortalUpload.objects.get(upload_id=uploaded["upload_id"]).deal_id == first.json()["id"]


def test_one_bad_attachment_rejects_the_whole_request(portal_client, client_company):
    good = upload(portal_client)
    response = post(
        portal_client,
        attachments=[
            {"upload_id": good["upload_id"], "name": "spec.pdf"},
            {"upload_id": str(uuid.uuid4()), "name": "ghost.pdf"},
        ],
    )
    assert response.status_code == 422
    assert PortalUpload.objects.get(upload_id=good["upload_id"]).deal_id is None
    assert_nothing_created(client_company)


@pytest.mark.parametrize(
    "ref",
    [
        {},
        {"upload_id": str(uuid.uuid4())},
        {"name": "x.pdf"},
        {"upload_id": "", "name": "x"},
        {"upload_id": "0" * 400, "name": "x"},
        {"upload_id": 5, "name": "x"},
        "id",
        None,
        7,
    ],
)
def test_malformed_attachment_ref_is_422(portal_client, client_company, ref):
    response = post(portal_client, attachments=[ref])
    assert response.status_code == 422
    assert_nothing_created(client_company)


# ── Источник и событие ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mapped(client_company):
    return CrmClientMapping.objects.create(company=client_company, crm_client_id=4242)


def test_request_created_event_has_source_cabinet(portal_client, client_company, mapped):
    response = post(portal_client, summary="Нужны трубы " + "а" * 400, lines=[line(quantity="3", unit="шт")])
    assert response.status_code == 201
    created = response.json()

    events = IntegrationWebhookEvent.objects.filter(event_type="request.created")
    assert events.count() == 1, "одно событие на запрос"
    envelope = events.get().payload
    assert envelope["payload"]["source"] == "cabinet"
    assert envelope["payload"]["erp_request_id"] == created["id"]
    assert envelope["payload"]["summary"] == created["summary"], "в событии — полная суть запроса, не название сделки"
    assert envelope["erp_company_id"] == client_company.pk and envelope["crm_client_id"] == mapped.crm_client_id


def test_request_source_is_cabinet_in_the_response_and_in_the_journal(portal_client):
    created = post(portal_client).json()
    assert created["source"] == "cabinet"
    log = ActivityLog.objects.get(event_code="deal.created", deal_id=created["id"])
    assert log.event_params["source"] == "cabinet" and log.event_params["contact_id"]
    assert portal_client.get(f"{URL}/{created['id']}").json()["source"] == "cabinet"
    assert [r["source"] for r in portal_client.get(URL).json()] == ["cabinet"]


def test_request_is_not_a_deal_yet(portal_client):
    created = post(portal_client).json()
    assert created["status"] == "new" and created["deal"] is None and "deal_id" not in created
    assert created["number"] == f"Z-{created['id']}"


def test_deal_created_by_portal_belongs_to_the_session_company_and_contact(
    portal_client, client_company, client_contact
):
    created = post(portal_client).json()
    deal = Deal.objects.get(pk=created["id"])
    assert deal.company_id == client_company.pk and deal.contact_id == client_contact.pk


def test_staff_deal_event_is_not_cabinet(client_company, mapped):
    """Сделку, заведённую не порталом (сотрудник, интеграция), сигнал помечает `erp`: контакт портала ни о чём не говорит."""
    Deal.objects.create(company=client_company, title="Заведена в ERP")
    event = IntegrationWebhookEvent.objects.get(event_type="request.created")
    assert event.payload["payload"]["source"] == "erp"


def test_portal_marker_does_not_leak_to_later_saves(portal_client, client_company, mapped):
    created = post(portal_client).json()
    deal = Deal.objects.get(pk=created["id"])
    deal.title = "Правка названия"
    deal.save()
    assert IntegrationWebhookEvent.objects.filter(event_type="request.created").count() == 1


def test_event_payload_matches_the_events_schema(portal_client, mapped):
    import json
    from pathlib import Path

    from portal.tests.contract_support import find_contract_path

    schema_path = find_contract_path().parents[1] / "events.schema.json"
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    post(portal_client)
    payload = IntegrationWebhookEvent.objects.get(event_type="request.created").payload["payload"]
    assert not list(
        Draft202012Validator({**schema["$defs"]["RequestCreated"], "$defs": schema["$defs"]}).iter_errors(payload)
    )


# ── Форма ответа, права, изоляция ────────────────────────────────────────────────────────────────


def test_response_matches_contract(portal_client):
    uploaded = upload(portal_client)
    response = post(
        portal_client,
        lines=[line(quantity="4", unit="шт"), line("Без количества")],
        attachments=[{"upload_id": uploaded["upload_id"], "name": "spec.pdf"}],
    )
    assert response.status_code == 201
    assert not check_response(response.json(), component("ClientRequest"))


def test_read_only_contact_cannot_create_a_request(readonly_portal_client, client_company):
    response = post(readonly_portal_client, lines=[line(quantity="1")])
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    assert_nothing_created(client_company)


def test_request_without_session_is_401(anon_portal_client):
    assert post(anon_portal_client).status_code == 401


def test_other_company_cannot_read_the_request(portal_client, other_portal_client):
    created = post(portal_client).json()
    response = other_portal_client.get(f"{URL}/{created['id']}")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    assert other_portal_client.get(URL).json() == []


def test_requests_of_a_company_do_not_mix(portal_client, other_portal_client, other_company):
    post(portal_client, summary="Запрос A")
    post(other_portal_client, summary="Запрос B")
    assert [r["summary"] for r in portal_client.get(URL).json()] == ["Запрос A"]
    assert [r["summary"] for r in other_portal_client.get(URL).json()] == ["Запрос B"]
    assert Deal.objects.get(company=other_company).title == "Запрос B"


def test_unknown_fields_do_not_reach_the_deal(portal_client):
    response = post(portal_client, company_id=999, stage="CLOSED_WON", contact_id=5)
    assert response.status_code == 201
    deal = Deal.objects.get()
    assert deal.stage.code == "DRAFT" and deal.company_id != 999
