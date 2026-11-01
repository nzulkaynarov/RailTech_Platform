"""«Я оплатил» (`POST /invoices/{id}/proofs`) и комментарий к КП (`POST /quotes/{id}/comments`) — B-CABFIX-1.

Платёжка клиента — та же `PaymentConfirmation`, что у менеджера (источник `CABINET`): поэтому счёт встаёт на вкладку
«Платёжки на подтверждение» (`finance.services.receivables`) без новых экранов. Проверяются права (can_act, чужая
компания), 404 и 409, лимиты файла, суммы и текста, идемпотентность по `Idempotency-Key`, журнал и уведомление.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from finance.models import PaymentConfirmation
from finance.services import receivables
from portal.models import PortalUpload, QuoteComment
from portal.tests.contract_support import check_response, response_schema

from accounts.models import CustomUser
from crm.models import ActivityLog
from notifications.models import Notification

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
PDF = b"%PDF-1.4 payment order"


def post(client, path, body=None, **extra):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json", **extra)


def upload(client, name="platezhka.pdf", content=PDF, content_type="application/pdf"):
    response = client.post(
        f"{API}/uploads", {"file": SimpleUploadedFile(name, content, content_type=content_type)}, format="multipart"
    )
    assert response.status_code == 201, response.content
    return response.json()["upload_id"]


@pytest.fixture
def manager(contract_world):
    user = CustomUser.objects.create_user(email="m@seller.uz", username="m@seller.uz", password="x")
    deal = contract_world["main"]
    deal.assigned_to = user
    deal.save(update_fields=["assigned_to"])
    return user


# ── «Я оплатил» ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["issued", "partially_paid", "overdue"])
def test_client_proof_lands_in_the_same_confirmation_queue_as_the_managers(
    contract_world, portal_client, client_contact, manager, django_capture_on_commit_callbacks, key
):
    invoice = contract_world["invoices"][key]
    upload_id = upload(portal_client)
    with django_capture_on_commit_callbacks(execute=True):
        response = post(
            portal_client,
            f"/invoices/{invoice.pk}/proofs",
            {
                "upload_id": upload_id,
                "paid_on": timezone.localdate().isoformat(),
                "amount": "84000000.00",
                "comment": "Оплатили сегодня",
            },
        )

    assert response.status_code == 201, response.content
    body = response.json()
    assert check_response(body, response_schema("/invoices/{id}/proofs", "post", "201")) == []
    assert body["status"] == "pending" and body["source"] == "cabinet" and body["file_name"] == "platezhka.pdf"
    assert body["amount"] == {"amount": "84000000.00", "currency": "UZS"} and body["comment"] == "Оплатили сегодня"

    proof = PaymentConfirmation.objects.get(pk=body["id"])
    assert proof.invoice_id == invoice.pk and proof.source == PaymentConfirmation.Source.CABINET
    assert proof.status == PaymentConfirmation.Status.PENDING and proof.recorded_by is None
    assert proof.claimed_amount == Decimal("84000000") and proof.file.read() == PDF
    assert PortalUpload.objects.get(upload_id=upload_id).deal_id == invoice.deal_id
    # Вкладка «Платёжки на подтверждение» Платформы — та же выборка, что у платёжки менеджера.
    rows, _ = receivables.board(tab="proofs", day=timezone.localdate())
    assert invoice.pk in {row.pk for row in rows}

    log = ActivityLog.objects.get(event_code="payment_doc.attached", entity_id=invoice.pk)
    assert log.company_id == invoice.deal.company_id and log.user_id is None
    assert log.event_params["source"] == "CABINET" and log.event_params["contact_id"] == client_contact.pk
    note = Notification.objects.get(user=manager, event_code="payment.proof_received")
    assert invoice.number in note.title


def test_invoice_lists_its_proofs_with_status(contract_world, portal_client):
    invoice = contract_world["invoices"]["issued"]
    post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(portal_client)})
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert [p["status"] for p in item["proofs"]] == ["pending"]
    assert item["proofs"][0]["amount"] is None and item["proofs"][0]["paid_on"] is None


def test_staff_note_of_a_manual_proof_is_not_shown_to_the_client(contract_world, portal_client):
    invoice = contract_world["invoices"]["issued"]
    PaymentConfirmation.objects.create(
        invoice=invoice,
        source=PaymentConfirmation.Source.MANUAL,
        file=SimpleUploadedFile("mail.pdf", PDF),
        original_name="mail.pdf",
        note="Пришла на почту бухгалтерии",
    )
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["proofs"][0]["source"] == "manager" and item["proofs"][0]["comment"] is None


@pytest.mark.parametrize("key", ["paid", "cancelled"])
def test_proof_for_a_paid_or_cancelled_invoice_is_409(contract_world, portal_client, key):
    invoice = contract_world["invoices"][key]
    response = post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(portal_client)})
    assert response.status_code == 409 and response.json() == {"detail": "INVOICE_NOT_OPEN"}
    assert not PaymentConfirmation.objects.filter(invoice=invoice).exists()


@pytest.mark.parametrize("key", ["draft", "not_issued"])
def test_proof_for_an_invoice_hidden_from_the_client_is_404(contract_world, portal_client, key):
    invoice = contract_world["invoices"][key]
    response = post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(portal_client)})
    assert response.status_code == 404 and response.json() == {"detail": "NOT_FOUND"}


def test_proof_for_another_companys_invoice_is_404(contract_world, other_portal_client):
    invoice = contract_world["invoices"]["issued"]
    response = post(other_portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(other_portal_client)})
    assert response.status_code == 404
    assert not PaymentConfirmation.objects.filter(invoice=invoice).exists()


def test_proof_without_can_act_is_403(contract_world, readonly_portal_client, portal_client):
    invoice = contract_world["invoices"]["issued"]
    response = post(readonly_portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(portal_client)})
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}


def test_proof_without_session_is_401(contract_world, anon_portal_client):
    invoice = contract_world["invoices"]["issued"]
    assert post(anon_portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": "x"}).status_code == 401


def test_proof_repeat_with_the_same_idempotency_key_creates_one_confirmation(contract_world, portal_client):
    invoice = contract_world["invoices"]["issued"]
    body = {"upload_id": upload(portal_client)}
    first = post(portal_client, f"/invoices/{invoice.pk}/proofs", body, HTTP_IDEMPOTENCY_KEY="proof-once")
    second = post(portal_client, f"/invoices/{invoice.pk}/proofs", body, HTTP_IDEMPOTENCY_KEY="proof-once")
    assert first.status_code == second.status_code == 201
    assert second["Idempotent-Replay"] == "true" and second.json() == first.json()
    assert PaymentConfirmation.objects.filter(invoice=invoice).count() == 1


def test_proof_with_an_image(contract_world, portal_client):
    invoice = contract_world["invoices"]["issued"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    upload_id = upload(portal_client, "screen.png", png, "image/png")
    response = post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload_id})
    assert response.status_code == 201 and response.json()["file_name"] == "screen.png"


TOMORROW = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()


@pytest.mark.parametrize(
    "make_body, code",
    [
        (lambda c: {"upload_id": "00000000-0000-4000-8000-000000000000"}, "UPLOAD_NOT_FOUND"),
        (lambda c: {"upload_id": upload(c, "order.exe", b"MZ....", "application/octet-stream")}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c, "order.pdf", b"not a pdf at all")}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "amount": "0.00"}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "amount": "-5.00"}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "amount": "12,5"}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "amount": 100}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "paid_on": TOMORROW}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "comment": "я" * 501}, "VALIDATION_ERROR"),
        (lambda c: {"upload_id": upload(c), "extra": 1}, "VALIDATION_ERROR"),
        (lambda c: {}, "VALIDATION_ERROR"),
    ],
)
def test_bad_proof_is_422_and_changes_nothing(contract_world, portal_client, make_body, code):
    invoice = contract_world["invoices"]["issued"]
    response = post(portal_client, f"/invoices/{invoice.pk}/proofs", make_body(portal_client))
    assert response.status_code == 422 and response.json() == {"detail": code}
    assert not PaymentConfirmation.objects.filter(invoice=invoice).exists()


def test_upload_over_the_limit_is_refused_before_the_proof(contract_world, portal_client, settings):
    settings.PORTAL_UPLOAD_MAX_BYTES = 10
    response = portal_client.post(
        f"{API}/uploads",
        {"file": SimpleUploadedFile("big.pdf", PDF, content_type="application/pdf")},
        format="multipart",
    )
    assert response.status_code == 422 and response.json() == {"detail": "FILE_TOO_LARGE"}


def test_upload_of_another_company_is_422_not_found(contract_world, portal_client, other_portal_client):
    invoice = contract_world["invoices"]["issued"]
    response = post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(other_portal_client)})
    assert response.status_code == 422 and response.json() == {"detail": "UPLOAD_NOT_FOUND"}


def test_confirming_the_client_proof_marks_it_confirmed_for_the_client(contract_world, portal_client, manager):
    invoice = contract_world["invoices"]["issued"]
    proof_id = post(portal_client, f"/invoices/{invoice.pk}/proofs", {"upload_id": upload(portal_client)}).json()["id"]
    manager.is_superuser = True
    manager.save(update_fields=["is_superuser"])
    done, err = receivables.confirm_payment(
        invoice.pk, manager, amount=Decimal("84000000.00"), paid_at=timezone.localdate(), confirmation_id=proof_id
    )
    assert err is None and done is not None
    item = next(i for i in portal_client.get(f"{API}/invoices").json() if i["id"] == invoice.pk)
    assert item["status"] == "paid"
    assert item["proofs"][0]["status"] == "confirmed" and item["proofs"][0]["confirmed_at"]


# ── Комментарий к КП ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["sent", "viewed"])
def test_client_comments_a_quote_awaiting_decision(
    contract_world, portal_client, client_contact, manager, django_capture_on_commit_callbacks, key
):
    quote = contract_world["quotes"][key]
    with django_capture_on_commit_callbacks(execute=True):
        response = post(portal_client, f"/quotes/{quote.pk}/comments", {"text": "  Можно срок поставки 30 дней?  "})

    assert response.status_code == 201, response.content
    body = response.json()
    assert check_response(body, response_schema("/quotes/{id}/comments", "post", "201")) == []
    assert body["author"] == "client" and body["author_name"] == client_contact.name
    assert body["text"] == "Можно срок поставки 30 дней?"

    detail = portal_client.get(f"{API}/quotes/{quote.pk}").json()
    assert [c["text"] for c in detail["comments"]] == ["Можно срок поставки 30 дней?"]
    log = ActivityLog.objects.get(event_code="quote.client_commented", entity_id=quote.pk)
    assert log.company_id == quote.deal.company_id and log.event_params["note"] == "Можно срок поставки 30 дней?"
    assert Notification.objects.filter(user=manager, event_code="quote.client_commented").exists()


def test_manager_comment_is_shown_with_the_manager_author(contract_world, portal_client, manager):
    quote = contract_world["quotes"]["sent"]
    manager.first_name, manager.last_name = "Азиз", "Каримов"
    manager.save(update_fields=["first_name", "last_name"])
    QuoteComment.objects.create(quote=quote, author_user=manager, text="Да, можно")
    comments = portal_client.get(f"{API}/quotes/{quote.pk}").json()["comments"]
    assert comments[0]["author"] == "manager" and comments[0]["author_name"] == "Азиз Каримов"


@pytest.mark.parametrize(
    "key, code", [("accepted", "QUOTE_FINALIZED"), ("rejected", "QUOTE_FINALIZED"), ("expired", "QUOTE_EXPIRED")]
)
def test_comment_on_a_decided_or_expired_quote_is_409(contract_world, portal_client, key, code):
    quote = contract_world["quotes"][key]
    before = QuoteComment.objects.count()
    response = post(portal_client, f"/quotes/{quote.pk}/comments", {"text": "Вопрос"})
    assert response.status_code == 409 and response.json() == {"detail": code}
    assert QuoteComment.objects.count() == before


@pytest.mark.parametrize(
    "body, code",
    [
        ({"text": ""}, "TEXT_REQUIRED"),
        ({"text": "   "}, "TEXT_REQUIRED"),
        ({"text": "я" * 2001}, "VALIDATION_ERROR"),
        ({"text": 5}, "VALIDATION_ERROR"),
        ({}, "VALIDATION_ERROR"),
        ({"text": "x", "extra": 1}, "VALIDATION_ERROR"),
    ],
)
def test_bad_comment_is_422(contract_world, portal_client, body, code):
    quote = contract_world["quotes"]["sent"]
    response = post(portal_client, f"/quotes/{quote.pk}/comments", body)
    assert response.status_code == 422 and response.json() == {"detail": code}


def test_comment_of_2000_chars_is_accepted(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    assert post(portal_client, f"/quotes/{quote.pk}/comments", {"text": "я" * 2000}).status_code == 201


def test_comment_without_can_act_is_403(contract_world, readonly_portal_client):
    quote = contract_world["quotes"]["sent"]
    response = post(readonly_portal_client, f"/quotes/{quote.pk}/comments", {"text": "Вопрос"})
    assert response.status_code == 403 and not QuoteComment.objects.filter(quote=quote).exists()


def test_comment_on_another_companys_or_hidden_quote_is_404(contract_world, portal_client, other_portal_client):
    quote = contract_world["quotes"]["sent"]
    assert post(other_portal_client, f"/quotes/{quote.pk}/comments", {"text": "Вопрос"}).status_code == 404
    hidden = contract_world["hidden_quotes"]["draft"]
    assert post(portal_client, f"/quotes/{hidden.pk}/comments", {"text": "Вопрос"}).status_code == 404
    assert not QuoteComment.objects.filter(quote__in=[quote, hidden]).exists()


def test_comment_repeat_with_the_same_idempotency_key_creates_one_comment(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    first = post(portal_client, f"/quotes/{quote.pk}/comments", {"text": "Один раз"}, HTTP_IDEMPOTENCY_KEY="c-once")
    second = post(portal_client, f"/quotes/{quote.pk}/comments", {"text": "Один раз"}, HTTP_IDEMPOTENCY_KEY="c-once")
    assert first.status_code == second.status_code == 201 and second.json() == first.json()
    assert QuoteComment.objects.filter(quote=quote).count() == 1


def test_staff_quote_card_carries_client_comments_only_on_the_detail(contract_world, client_contact):
    """Карточка КП Платформы (BFF → `GET /api/v1/crm/quotes/{id}/`) показывает комментарии клиента."""
    from crm.serializers.quote import QuoteSerializer

    quote = contract_world["quotes"]["rejected"]
    detail = QuoteSerializer(quote, context={"include_economics": True}).data["client_comments"]
    assert [(c["author"], c["text"]) for c in detail] == [
        ("client", "Можно дешевле?"),
        ("manager", "Пришлём новую версию"),
    ]
    assert detail[0]["author_name"] == client_contact.name
    assert QuoteSerializer(quote).data["client_comments"] == []
