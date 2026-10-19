"""FIX-22: договор, счёт и акт в портале — подпись, приёмка и возврат только через сервисы ERP.

Находки аудита: P-5 (подпись договора из портала в обход двусторонней подписи и FSM; черновик подписывался и
показывался как `sent`), P-6 (возврат акта обнулял статус, приёмка из любого статуса закрывала сделку). Хвосты
FIX-21: срок оплаты счёта обязателен по контракту. На каждый эндпоинт — чужая компания → 404, `can_act=false` → 403,
повтор действия → 409.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from documents.models import GeneratedDocument
from portal.tests.contract_support import check_response, component, response_schema

from crm.constants import DEFAULT_INVOICE_DUE_DAYS, ActStatusCode, ContractStatusCode, DealStageCode
from crm.models import Act, ActivityLog, ActStatus, DealStage, Invoice
from crm.services.billing import reject_act, sign_act
from crm.services.contracts import sign_contract_by_client

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
PDF = b"%PDF-1.4 fake scan of the signed act"


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


def upload(client, name="act-scan.pdf", content=PDF, content_type="application/pdf"):
    response = client.post(
        f"{API}/uploads", {"file": SimpleUploadedFile(name, content, content_type=content_type)}, format="multipart"
    )
    assert response.status_code == 201, response.content
    return response.json()["upload_id"]


# ── Договор ────────────────────────────────────────────────────────────────────────────────────────


def test_client_sees_contracts_awaiting_signature_and_signed_but_not_draft_or_cancelled(contract_world, portal_client):
    listed = {item["id"]: item["status"] for item in portal_client.get(f"{API}/contracts").json()}
    contracts = contract_world["contracts"]
    assert listed == {
        contracts["sent"].pk: "sent",
        contracts["signed_by_client"].pk: "signed_by_client",
        contracts["signed_by_company"].pk: "signed_by_company",
        contracts["signed"].pk: "signed",
    }


@pytest.mark.parametrize("key", ["draft", "cancelled"])
def test_draft_and_cancelled_contract_is_not_found_and_cannot_be_signed(contract_world, portal_client, key):
    """P-5: Cabinet рисовал у черновика «Подписать», а `ContractSignView` подписывал и DRAFT."""
    contract = contract_world["contracts"][key]
    assert contract.pk not in {item["id"] for item in portal_client.get(f"{API}/contracts").json()}

    response = post(portal_client, f"/contracts/{contract.pk}/sign")

    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    contract.refresh_from_db()
    assert contract.client_signed_at is None and contract.client_signer is None
    assert contract.status.code == {"draft": ContractStatusCode.DRAFT, "cancelled": ContractStatusCode.CANCELLED}[key]


def test_sign_goes_through_the_service_and_waits_for_the_company_signature(
    contract_world, portal_client, client_contact
):
    contract = contract_world["contracts"]["sent"]
    stage_before = contract.deal.stage.code

    response = post(portal_client, f"/contracts/{contract.pk}/sign")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_by_client" and body["signed_by_client_at"] and body["signed_by_company_at"] is None
    assert not check_response(body, response_schema("/contracts/{id}/sign", "post", "200"))
    contract.refresh_from_db()
    assert contract.status.code == ContractStatusCode.PENDING_MANAGER  # ждёт подписи продавца, а не «подписан»
    assert contract.client_signer is None  # клиентских пользователей в ERP нет; кто подписал — в журнале
    event = ActivityLog.objects.get(event_code="contract.signed_client", deal=contract.deal)
    assert event.event_params["contact_id"] == client_contact.pk and event.event_params["channel"] == "portal"
    contract.deal.refresh_from_db()
    assert contract.deal.stage.code == stage_before  # сделку двигает сервис по двусторонней подписи, не портал


def test_sign_after_the_company_closes_the_deal_through_the_service(contract_world, portal_client):
    contract = contract_world["contracts"]["signed_by_company"]
    deal = contract.deal
    deal.stage = DealStage.objects.get(code=DealStageCode.CONTRACT_SIGNED)
    deal.save(update_fields=["stage"])

    response = post(portal_client, f"/contracts/{contract.pk}/sign")

    assert response.status_code == 200 and response.json()["status"] == "signed"
    contract.refresh_from_db()
    assert contract.status.code == ContractStatusCode.SIGNED and contract.is_fully_signed
    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.CLOSED_WON  # `_finalize_if_signed` обеих подписей


@pytest.mark.parametrize("key", ["signed_by_client", "signed"])
def test_sign_repeat_is_409(contract_world, portal_client, key):
    contract = contract_world["contracts"][key]
    response = post(portal_client, f"/contracts/{contract.pk}/sign")
    assert response.status_code == 409 and response.json() == {"detail": "CONTRACT_FINALIZED"}


def test_sign_twice_in_a_row_is_409_the_second_time(contract_world, portal_client):
    path = f"/contracts/{contract_world['contracts']['sent'].pk}/sign"
    assert post(portal_client, path).status_code == 200
    assert post(portal_client, path).json() == {"detail": "CONTRACT_FINALIZED"}


def test_sign_other_company_is_404(contract_world, other_portal_client):
    contract = contract_world["contracts"]["sent"]
    response = post(other_portal_client, f"/contracts/{contract.pk}/sign")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    contract.refresh_from_db()
    assert contract.client_signed_at is None


def test_sign_without_can_act_is_403(contract_world, readonly_portal_client):
    contract = contract_world["contracts"]["sent"]
    response = post(readonly_portal_client, f"/contracts/{contract.pk}/sign")
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    contract.refresh_from_db()
    assert contract.client_signed_at is None


def test_sign_without_session_is_401(contract_world, anon_portal_client):
    assert post(anon_portal_client, f"/contracts/{contract_world['contracts']['sent'].pk}/sign").status_code == 401


def test_service_signs_only_for_a_contact_of_the_same_company_with_can_act(
    contract_world, client_contact, readonly_contact, other_contact
):
    """Инвариант сервиса, а не только портала: чужой контакт и контакт без `can_act` подписать не могут."""
    contract = contract_world["contracts"]["sent"]
    for contact in (other_contact, readonly_contact):
        assert sign_contract_by_client(contract.pk, portal_contact=contact) == (None, "MEMBER_REQUIRED_FOR_ACTION")
    signed, error = sign_contract_by_client(contract.pk, portal_contact=client_contact)
    assert error is None and signed.client_signed_at


def test_service_does_not_sign_a_draft_for_a_portal_contact(contract_world, client_contact):
    contract = contract_world["contracts"]["draft"]
    assert sign_contract_by_client(contract.pk, portal_contact=client_contact) == (
        None,
        "CONTRACT_CLIENT_SIGN_NOT_ALLOWED",
    )


# ── Счёт ───────────────────────────────────────────────────────────────────────────────────────────


def test_invoice_due_date_is_always_a_date_and_unissued_invoices_are_hidden(contract_world, portal_client):
    invoices = contract_world["invoices"]
    response = portal_client.get(f"{API}/invoices")
    body = {item["id"]: item for item in response.json()}

    assert invoices["draft"].pk not in body and invoices["not_issued"].pk not in body
    for key in ("issued", "partially_paid", "paid", "overdue", "cancelled", "no_due_date"):
        item = body[invoices[key].pk]
        assert isinstance(item["due_date"], str) and not check_response(item, component("Invoice"))


def test_invoice_without_due_date_gets_it_by_the_issue_rule_not_invented(contract_world, portal_client):
    """Срок пуст — считается так же, как при выставлении (`issue_invoice`): дата выставления + срок оплаты продавца."""
    invoice = contract_world["invoices"]["no_due_date"]
    assert invoice.due_date is None
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["due_date"] == (invoice.issued_at + datetime.timedelta(days=DEFAULT_INVOICE_DUE_DAYS)).isoformat()


def test_invoice_overdue_uses_the_computed_due_date(contract_world, portal_client):
    invoice = contract_world["invoices"]["no_due_date"]
    long_ago = timezone.localdate() - datetime.timedelta(days=60)
    Invoice.objects.filter(pk=invoice.pk).update(issued_at=long_ago)
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["status"] == "overdue"


def test_invoice_stored_due_date_wins_over_the_rule(contract_world, portal_client):
    invoice = contract_world["invoices"]["issued"]
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["due_date"] == invoice.due_date.isoformat()


# ── Акт ────────────────────────────────────────────────────────────────────────────────────────────


def test_client_sees_issued_accepted_and_returned_acts_only(contract_world, portal_client):
    acts = contract_world["acts"]
    listed = {item["id"]: item["status"] for item in portal_client.get(f"{API}/acts").json()}
    assert listed == {acts["issued"].pk: "issued", acts["accepted"].pk: "accepted", acts["returned"].pk: "returned"}


@pytest.mark.parametrize("key", ["draft", "cancelled"])
@pytest.mark.parametrize("action", ["accept", "return"])
def test_draft_and_cancelled_acts_are_not_found(contract_world, portal_client, key, action):
    act = contract_world["acts"][key]
    body = {"reason": "нет"} if action == "return" else {}
    response = post(portal_client, f"/acts/{act.pk}/{action}", body)
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_accept_goes_through_sign_act_and_does_not_close_the_deal(contract_world, portal_client, client_contact):
    act = contract_world["acts"]["issued"]
    deal = act.deal
    deal.stage = DealStage.objects.get(code=DealStageCode.CONTRACT_SIGNED)
    deal.save(update_fields=["stage"])

    response = post(portal_client, f"/acts/{act.pk}/accept")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted" and body["scan_document_id"] is None
    assert not check_response(body, response_schema("/acts/{id}/accept", "post", "200"))
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.SIGNED and act.acceptor_signed_at and act.signed_at
    assert act.acceptor_signer is None
    event = ActivityLog.objects.get(event_code="act.signed", deal=deal)
    assert event.event_params["contact_id"] == client_contact.pk and event.event_params["manual"] is True
    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.CONTRACT_SIGNED  # приёмка акта сделку мимо сервиса не закрывает (P-6)


def test_accept_with_a_scan_stores_it_as_the_signed_copy_and_exposes_a_document(contract_world, portal_client):
    act = contract_world["acts"]["issued"]
    upload_id = upload(portal_client)

    response = post(portal_client, f"/acts/{act.pk}/accept", {"upload_id": upload_id})

    assert response.status_code == 200
    body = response.json()
    assert not check_response(body, component("Act"))
    act.refresh_from_db()
    assert act.signed_file and act.signed_file.read() == PDF
    document = GeneratedDocument.objects.get(number=f"SCAN-{act.number}")
    assert body["scan_document_id"] == document.pk and document.deal_id == act.deal_id
    assert document.pdf_file.name == act.signed_file.name  # файл один, копии не плодим
    # скан — документ из списка документов клиента (вид `act`) и отдаётся тем же файлом
    listed = {item["id"]: item for item in portal_client.get(f"{API}/documents").json()}
    assert listed[document.pk]["kind"] == "act"
    assert portal_client.get(f"{API}/documents/{document.pk}/file").status_code == 200
    # список актов видит тот же id
    in_list = next(item for item in portal_client.get(f"{API}/acts").json() if item["id"] == act.pk)
    assert in_list["scan_document_id"] == document.pk
    # исходная загрузка привязана к сделке акта
    from portal.models import PortalUpload

    assert PortalUpload.objects.get(upload_id=upload_id).deal_id == act.deal_id


@pytest.mark.parametrize(
    ("make_body", "status_code", "code"),
    [
        (lambda c, w: {"upload_id": "00000000-0000-4000-8000-000000000000"}, 422, "UPLOAD_NOT_FOUND"),
        (lambda c, w: {"upload_id": "not-a-uuid"}, 422, "UPLOAD_NOT_FOUND"),
        (
            lambda c, w: {"upload_id": upload(c, "act.exe", b"MZ....", "application/octet-stream")},
            422,
            "VALIDATION_ERROR",
        ),
        (lambda c, w: {"upload_id": upload(c, "act.pdf", b"not a pdf at all")}, 422, "VALIDATION_ERROR"),
        (lambda c, w: {"upload_id": upload(c, "act.txt", b"plain text", "text/plain")}, 422, "VALIDATION_ERROR"),
        (lambda c, w: {"upload_id": 5}, 422, "VALIDATION_ERROR"),
        (lambda c, w: {"upload_id": "x", "extra": 1}, 422, "VALIDATION_ERROR"),
    ],
)
def test_accept_with_a_bad_scan_is_422_and_changes_nothing(contract_world, portal_client, make_body, status_code, code):
    act = contract_world["acts"]["issued"]
    response = post(portal_client, f"/acts/{act.pk}/accept", make_body(portal_client, contract_world))
    assert response.status_code == status_code and response.json() == {"detail": code}
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.ISSUED and not act.signed_file
    assert not GeneratedDocument.objects.filter(number=f"SCAN-{act.number}").exists()


def test_accept_with_the_scan_of_another_company_is_422_not_found(contract_world, portal_client, other_portal_client):
    foreign = upload(other_portal_client)
    act = contract_world["acts"]["issued"]
    response = post(portal_client, f"/acts/{act.pk}/accept", {"upload_id": foreign})
    assert response.status_code == 422 and response.json() == {"detail": "UPLOAD_NOT_FOUND"}


def test_accept_with_an_image_scan(contract_world, portal_client):
    act = contract_world["acts"]["issued"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    response = post(
        portal_client, f"/acts/{act.pk}/accept", {"upload_id": upload(portal_client, "scan.png", png, "image/png")}
    )
    assert response.status_code == 200 and response.json()["scan_document_id"]


@pytest.mark.parametrize("key", ["accepted", "returned"])
def test_accept_repeat_or_after_return_is_409(contract_world, portal_client, key):
    act = contract_world["acts"][key]
    response = post(portal_client, f"/acts/{act.pk}/accept")
    assert response.status_code == 409 and response.json() == {"detail": "ACT_FINALIZED"}


def test_accept_twice_in_a_row_is_409_the_second_time(contract_world, portal_client):
    path = f"/acts/{contract_world['acts']['issued'].pk}/accept"
    assert post(portal_client, path).status_code == 200
    assert post(portal_client, path).json() == {"detail": "ACT_FINALIZED"}


def test_accept_other_company_is_404(contract_world, other_portal_client):
    act = contract_world["acts"]["issued"]
    response = post(other_portal_client, f"/acts/{act.pk}/accept")
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.ISSUED


def test_accept_without_can_act_is_403(contract_world, readonly_portal_client):
    act = contract_world["acts"]["issued"]
    response = post(readonly_portal_client, f"/acts/{act.pk}/accept")
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.ISSUED


def test_accept_without_session_is_401(contract_world, anon_portal_client):
    assert post(anon_portal_client, f"/acts/{contract_world['acts']['issued'].pk}/accept").status_code == 401


def test_return_goes_through_reject_act_and_never_writes_a_null_status(contract_world, portal_client, client_contact):
    act = contract_world["acts"]["issued"]
    deal = act.deal
    stage_before = deal.stage.code

    response = post(portal_client, f"/acts/{act.pk}/return", {"reason": "Не совпадает количество труб"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "returned" and body["returned_reason"] == "Не совпадает количество труб"
    assert not check_response(body, response_schema("/acts/{id}/return", "post", "200"))
    act.refresh_from_db()
    assert act.status is not None and act.status.code == ActStatusCode.DRAFT  # NULL больше не пишется (P-6)
    assert act.rejection_reason == "Не совпадает количество труб" and act.issuer_signed_at is None
    event = ActivityLog.objects.get(event_code="act.rejected", deal=deal)
    assert event.event_params["contact_id"] == client_contact.pk
    deal.refresh_from_db()
    assert deal.stage.code == stage_before


@pytest.mark.parametrize("key", ["accepted", "returned"])
def test_return_after_decision_is_409(contract_world, portal_client, key):
    response = post(portal_client, f"/acts/{contract_world['acts'][key].pk}/return", {"reason": "поздно"})
    assert response.status_code == 409 and response.json() == {"detail": "ACT_FINALIZED"}


def test_return_repeat_is_409(contract_world, portal_client):
    path = f"/acts/{contract_world['acts']['issued'].pk}/return"
    assert post(portal_client, path, {"reason": "нет"}).status_code == 200
    assert post(portal_client, path, {"reason": "нет"}).json() == {"detail": "ACT_FINALIZED"}


def test_return_blank_reason_is_422(contract_world, portal_client):
    response = post(portal_client, f"/acts/{contract_world['acts']['issued'].pk}/return", {"reason": " "})
    assert response.status_code == 422 and response.json() == {"detail": "REASON_REQUIRED"}


def test_return_other_company_is_404(contract_world, other_portal_client):
    response = post(other_portal_client, f"/acts/{contract_world['acts']['issued'].pk}/return", {"reason": "x"})
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_return_without_can_act_is_403(contract_world, readonly_portal_client):
    response = post(readonly_portal_client, f"/acts/{contract_world['acts']['issued'].pk}/return", {"reason": "x"})
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}


def test_legacy_act_with_a_null_status_and_a_reason_is_still_a_returned_act(contract_world, portal_client):
    """Запись прежнего портала (статус NULL + причина) не пропадает у клиента: это возвращённый акт."""
    act = contract_world["acts"]["returned"]
    Act.objects.filter(pk=act.pk).update(status=None)
    item = next(i for i in portal_client.get(f"{API}/acts").json() if i["id"] == act.pk)
    assert item["status"] == "returned"


def test_act_services_accept_only_a_contact_of_the_same_company_with_can_act(
    contract_world, client_contact, readonly_contact, other_contact
):
    act = contract_world["acts"]["issued"]
    for contact in (other_contact, readonly_contact):
        assert sign_act(act.pk, None, portal_contact=contact) == (None, "ACT_ACCEPTOR_SIDE_REQUIRED")
        assert reject_act(act.pk, None, "причина", portal_contact=contact) == (None, "ACT_ACCEPTOR_SIDE_REQUIRED")
    act.refresh_from_db()
    assert act.status.code == ActStatusCode.ISSUED
    _, error = sign_act(act.pk, None, portal_contact=client_contact)
    assert error is None


def test_act_services_do_not_accept_a_non_issued_act_for_a_portal_contact(contract_world, client_contact):
    for key in ("accepted", "returned", "draft", "cancelled"):
        assert sign_act(contract_world["acts"][key].pk, None, portal_contact=client_contact) == (
            None,
            "ACT_SIGN_NOT_ALLOWED",
        )
    assert ActStatus.objects.filter(code=ActStatusCode.ISSUED).exists()
