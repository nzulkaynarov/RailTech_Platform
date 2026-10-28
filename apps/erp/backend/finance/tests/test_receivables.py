"""D2-4: «Счета и оплаты» бухгалтера — доска вкладок, карточка, подтверждение оплаты, платёжка клиента, запрос платёжки.

Матрица: бухгалтер (`finance.payment`) — действует; руководитель (`finance.invoice`) — читает и открывает карточку; сотрудник без
прав на финансы (менеджер/снабжение) и участник чужой компании — 403 `ROLE_NOT_PERMITTED` на каждой операции, в том числе
на чтении (прямой вызов ERP, мимо Платформы). Ответы сверяются со схемой `erp-internal.yaml`.
"""

import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from finance.models import PaymentConfirmation
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from core.tests.openapi_fixtures import conforms
from crm.models import ActivityLog, Invoice, InvoiceStatus, Payment
from crm.tests.test_record_payment_back_office import world as base_world  # noqa: F401

pytestmark = pytest.mark.django_db
D = Decimal
BASE = "/api/v1/finance/receivables/"


def _client(user):
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _member(company, email, permissions):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    role = CompanyRole.objects.create(company=company, name=email, permissions=permissions)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        company_roles=[role],
        is_active=True,
        is_primary=True,
    )
    return user


def _invoice(base, number, code, *, total="112.00", paid="0", due=None, days_ago=None):
    due_date = due or (timezone.localdate() - datetime.timedelta(days=days_ago) if days_ago is not None else None)
    return Invoice.objects.create(
        deal=base["invoice"].deal,
        number=number,
        status=InvoiceStatus.objects.get(code=code),
        issued_at=timezone.localdate() - datetime.timedelta(days=20),
        due_date=due_date,
        total_incl_vat=D(total),
        subtotal_excl_vat=D(total),
        amount_paid=D(paid),
    )


@pytest.fixture
def world(base_world):  # noqa: F811
    own = Company.objects.get(name="Own Co")
    base_world["head"] = _member(own, "head@own.test", ["finance.invoice", "quote.view_cost_margin"])
    base_world["supply"] = _member(own, "supply@own.test", ["catalog.manage", "supply.manage", "quote.build"])
    base_world["day"] = timezone.localdate()
    invoice = base_world["invoice"]
    invoice.due_date = base_world["day"] + datetime.timedelta(days=10)
    invoice.save(update_fields=["due_date"])
    return base_world


def _get(user, path, **params):
    return _client(user).get(path, params)


def _confirm(user, invoice_id, **body):
    payload = {"amount": "112.00", "paid_at": timezone.localdate().isoformat()}
    payload.update(body)
    return _client(user).post(f"{BASE}{invoice_id}/confirm-payment/", payload, format="json")


def _attach(user, invoice_id, name="pp.pdf", **body):
    data = {"file": SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf"), **body}
    return _client(user).post(f"{BASE}{invoice_id}/confirmations/", data, format="multipart")


def _assert_schema(response, path, method):
    conforms(response, path, method)


# ── вкладки ─────────────────────────────────────────────────────────────────────────────────


def test_tabs_are_mutually_exclusive_and_counted(world):
    draft = _invoice(world, "SCH-DRAFT", "DRAFT")
    overdue = _invoice(world, "SCH-LATE", "ISSUED", days_ago=5)
    partial_late = _invoice(world, "SCH-PART", "PARTIAL", paid="40", days_ago=1)
    proof_late = _invoice(world, "SCH-PROOF", "ISSUED", days_ago=9)
    paid = _invoice(world, "SCH-PAID", "PAID", paid="112")
    _attach(world["finance"], proof_late.pk)
    ids = {
        name: obj.pk
        for name, obj in {"draft": draft, "overdue": overdue, "partial": partial_late, "proof": proof_late}.items()
    }

    board = _get(world["finance"], BASE, tab="awaiting").json()
    assert board["counts"] == {"to_issue": 1, "awaiting": 1, "proofs": 1, "overdue": 2}
    assert [r["id"] for r in board["results"]] == [world["invoice"].pk]
    assert [r["id"] for r in _get(world["finance"], BASE, tab="to_issue").json()["results"]] == [ids["draft"]]
    assert [r["id"] for r in _get(world["finance"], BASE, tab="proofs").json()["results"]] == [ids["proof"]]
    assert {r["id"] for r in _get(world["finance"], BASE, tab="overdue").json()["results"]} == {
        ids["overdue"],
        ids["partial"],
    }
    everything = _get(world["finance"], BASE, tab="all").json()
    assert everything["count"] == 6 and paid.pk in {r["id"] for r in everything["results"]}


def test_row_statuses_in_words_and_overdue_is_computed_from_the_due_date(world):
    late = _invoice(world, "SCH-LATE", "ISSUED", days_ago=5)
    partial = _invoice(world, "SCH-PART", "PARTIAL", paid="40", due=world["day"] + datetime.timedelta(days=3))
    rows = {r["number"]: r for r in _get(world["finance"], BASE, tab="all").json()["results"]}
    assert rows["SCH-LATE"]["display_status"] == "overdue"
    assert rows["SCH-LATE"]["status"] == "ISSUED"  # статус в базе не менялся: просрочку считает код
    assert rows["SCH-LATE"]["days_overdue"] == 5 and rows["SCH-LATE"]["is_overdue"] is True
    assert rows["SCH-PART"]["display_status"] == "partially_paid"
    assert D(rows["SCH-PART"]["balance_due"]) == D("72.00")
    assert rows[world["invoice"].number]["display_status"] == "issued"
    assert late.pk and partial.pk


def test_a_pending_proof_changes_the_status_and_the_tab_until_it_is_confirmed(world):
    invoice = world["invoice"]
    response = _attach(world["finance"], invoice.pk, source="EMAIL", claimed_amount="112.00")
    assert response.status_code == 201, response.content
    card = response.json()
    _assert_schema(response, f"{BASE}{{invoice_id}}/confirmations/", "post")
    assert card["display_status"] == "proof_received" and card["has_pending_proof"] is True
    assert card["confirmations"][0]["source"] == "EMAIL" and card["confirmations"][0]["status"] == "PENDING"
    assert card["confirmations"][0]["recorded_by"] == "finance@own.test"
    assert _get(world["finance"], BASE, tab="proofs").json()["count"] == 1
    confirmed = _confirm(world["finance"], invoice.pk, confirmation_id=card["confirmations"][0]["id"])
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["display_status"] == "paid"
    assert _get(world["finance"], BASE, tab="proofs").json()["count"] == 0


def test_search_by_number_or_client_and_pagination(world):
    for index in range(3):
        _invoice(world, f"SCH-X{index}", "ISSUED", days_ago=index + 1)
    assert _get(world["finance"], BASE, tab="all", q="SCH-X1").json()["count"] == 1
    assert _get(world["finance"], BASE, tab="all", q="client co").json()["count"] == 4
    page = _get(world["finance"], BASE, tab="all", limit=2, offset=3).json()
    assert page["count"] == 4 and len(page["results"]) == 1


@pytest.mark.parametrize("params", [{"tab": "paid"}, {"limit": "many"}])
def test_bad_query_is_a_400_with_a_code(world, params):
    response = _get(world["finance"], BASE, **params)
    assert response.status_code == 400 and response.json()["detail"] in {"TAB_INVALID", "PAGINATION_INVALID"}
    _assert_schema(response, BASE, "get")


# ── подтверждение оплаты ────────────────────────────────────────────────────────────────────


def test_confirm_full_payment_closes_the_invoice_and_publishes_invoice_paid(world, monkeypatch):
    published = []
    monkeypatch.setattr(
        "integration.services.events.publish_invoice_event",
        lambda event, invoice: published.append((event, invoice.pk)),
    )
    invoice = world["invoice"]
    response = _confirm(world["finance"], invoice.pk, reference="BANK-1")
    assert response.status_code == 200, response.content
    card = response.json()
    assert card["status"] == "PAID" and card["display_status"] == "paid"
    assert D(card["amount_paid"]) == D("112.00") and D(card["balance_due"]) == D("0.00")
    assert card["can_confirm"] is False
    assert [p["reference"] for p in card["payments"]] == ["BANK-1"]
    assert published == [("invoice.paid", invoice.pk)]
    assert any(h["code"] == "payment.recorded" for h in card["history"])
    _assert_schema(response, f"{BASE}{{invoice_id}}/confirm-payment/", "post")


def test_partial_payment_keeps_the_remainder_visible_and_the_invoice_open(world, monkeypatch):
    published = []
    monkeypatch.setattr(
        "integration.services.events.publish_invoice_event", lambda event, invoice: published.append(event)
    )
    invoice = world["invoice"]
    first = _confirm(world["finance"], invoice.pk, amount="40.00", reference="BANK-A").json()
    assert first["status"] == "PARTIAL" and first["display_status"] == "partially_paid"
    assert D(first["balance_due"]) == D("72.00") and first["can_confirm"] is True
    assert published == []  # событие «оплачен» — только когда закрыт весь счёт
    second = _confirm(world["finance"], invoice.pk, amount="72.00", reference="BANK-B").json()
    assert second["status"] == "PAID" and len(second["payments"]) == 2
    assert published == ["invoice.paid"]


def test_amount_above_the_remainder_is_refused_and_nothing_is_written(world):
    invoice = world["invoice"]
    response = _confirm(world["finance"], invoice.pk, amount="112.01")
    assert response.status_code == 409 and response.json()["detail"] == "PAYMENT_EXCEEDS_BALANCE_DUE"
    _assert_schema(response, f"{BASE}{{invoice_id}}/confirm-payment/", "post")
    invoice.refresh_from_db()
    assert invoice.amount_paid == 0 and not Payment.objects.filter(invoice=invoice).exists()
    _confirm(world["finance"], invoice.pk, amount="100.00", reference="B1")
    again = _confirm(world["finance"], invoice.pk, amount="20.00", reference="B2")
    assert again.status_code == 409 and again.json()["detail"] == "PAYMENT_EXCEEDS_BALANCE_DUE"


def test_repeat_of_a_confirmed_payment_is_idempotent(world):
    invoice = world["invoice"]
    first = _confirm(world["finance"], invoice.pk)
    second = _confirm(world["finance"], invoice.pk)
    assert first.status_code == second.status_code == 200
    assert first.json()["replayed"] is False and second.json()["replayed"] is True
    assert Payment.objects.filter(invoice=invoice).count() == 1
    invoice.refresh_from_db()
    assert invoice.amount_paid == D("112.00")


def test_repeat_with_the_same_reference_and_with_the_same_confirmation_does_not_duplicate(world):
    invoice = world["invoice"]
    proof = _attach(world["finance"], invoice.pk).json()["confirmations"][0]["id"]
    a = _confirm(world["finance"], invoice.pk, amount="30.00", reference="REF-1")
    b = _confirm(world["finance"], invoice.pk, amount="30.00", reference="REF-1")
    assert b.json()["replayed"] is True and Payment.objects.filter(invoice=invoice).count() == 1
    c = _confirm(world["finance"], invoice.pk, amount="30.00", confirmation_id=proof)
    d = _confirm(world["finance"], invoice.pk, amount="30.00", confirmation_id=proof)
    assert c.status_code == d.status_code == 200 and d.json()["replayed"] is True
    assert Payment.objects.filter(invoice=invoice).count() == 2
    assert a.status_code == 200


def test_same_reference_with_another_amount_is_a_conflict(world):
    invoice = world["invoice"]
    _confirm(world["finance"], invoice.pk, amount="30.00", reference="REF-9")
    response = _confirm(world["finance"], invoice.pk, amount="31.00", reference="REF-9")
    assert response.status_code == 409 and response.json()["detail"] == "PAYMENT_REFERENCE_CONFLICT"


@pytest.mark.parametrize(
    ("body", "status_code", "code"),
    [
        ({"amount": "0.00"}, 400, "PAYMENT_AMOUNT_MUST_BE_POSITIVE"),
        ({"amount": "-5.00"}, 400, "PAYMENT_AMOUNT_MUST_BE_POSITIVE"),
        ({"paid_at": (timezone.localdate() + datetime.timedelta(days=1)).isoformat()}, 400, "PAYMENT_DATE_IN_FUTURE"),
    ],
)
def test_invalid_amount_or_future_date_is_refused(world, body, status_code, code):
    response = _confirm(world["finance"], world["invoice"].pk, **body)
    assert response.status_code == status_code and response.json()["detail"] == code


def test_missing_fields_are_field_errors(world):
    response = _client(world["finance"]).post(f"{BASE}{world['invoice'].pk}/confirm-payment/", {}, format="json")
    assert response.status_code == 400 and {"amount", "paid_at"} <= set(response.json())


def test_draft_and_cancelled_invoices_take_no_payment(world):
    draft = _invoice(world, "SCH-D", "DRAFT")
    cancelled = _invoice(world, "SCH-C", "CANCELLED")
    assert _confirm(world["finance"], draft.pk).json()["detail"] == "INVOICE_NOT_ISSUED"
    assert _confirm(world["finance"], cancelled.pk).json()["detail"] == "INVOICE_CANCELLED"
    assert _attach(world["finance"], draft.pk).json()["detail"] == "INVOICE_NOT_OPEN"


def test_the_confirmation_of_another_invoice_is_not_found(world):
    other = _invoice(world, "SCH-O", "ISSUED", days_ago=1)
    proof = _attach(world["finance"], other.pk).json()["confirmations"][0]["id"]
    response = _confirm(world["finance"], world["invoice"].pk, confirmation_id=proof)
    assert response.status_code == 404 and response.json()["detail"] == "CONFIRMATION_NOT_FOUND"
    assert PaymentConfirmation.objects.get(pk=proof).status == "PENDING"


def test_unknown_invoice_is_404(world):
    assert _confirm(world["finance"], 999999).status_code == 404
    assert _get(world["finance"], f"{BASE}999999/").status_code == 404


# ── платёжка, запрос платёжки, файл ────────────────────────────────────────────────────────


def test_attached_proof_streams_back_and_is_attached_to_the_payment(world):
    invoice = world["invoice"]
    card = _attach(world["finance"], invoice.pk, note="пришла по почте").json()
    proof = card["confirmations"][0]
    assert proof["original_name"] == "pp.pdf" and proof["note"] == "пришла по почте"
    file_response = _get(world["finance"], f"{BASE}{invoice.pk}/confirmations/{proof['id']}/file/")
    assert file_response.status_code == 200
    assert b"".join(file_response.streaming_content).startswith(b"%PDF")
    paid = _confirm(world["finance"], invoice.pk, confirmation_id=proof["id"]).json()
    assert paid["payments"][0]["has_proof"] is True
    assert paid["confirmations"][0]["status"] == "CONFIRMED" and paid["confirmations"][0]["payment_id"]


def test_proof_file_of_another_invoice_is_not_served(world):
    other = _invoice(world, "SCH-O", "ISSUED", days_ago=1)
    proof = _attach(world["finance"], other.pk).json()["confirmations"][0]["id"]
    response = _get(world["finance"], f"{BASE}{world['invoice'].pk}/confirmations/{proof}/file/")
    assert response.status_code == 404


def test_bad_file_is_refused(world):
    bad = SimpleUploadedFile("pp.exe", b"MZ", content_type="application/octet-stream")
    response = _client(world["finance"]).post(
        f"{BASE}{world['invoice'].pk}/confirmations/", {"file": bad}, format="multipart"
    )
    assert response.status_code == 400
    assert not PaymentConfirmation.objects.exists()


def test_request_payment_doc_is_logged_in_the_invoice_journal(world):
    invoice = world["invoice"]
    response = _client(world["finance"]).post(f"{BASE}{invoice.pk}/request-payment-doc/")
    assert response.status_code == 200, response.content
    card = response.json()
    assert card["payment_doc_requested_at"] is not None
    assert card["history"][0]["code"] == "payment_doc.requested" and card["history"][0]["by"] == "finance@own.test"
    assert (
        ActivityLog.objects.filter(event_code="payment_doc.requested", event_params__number=invoice.number).count() == 1
    )
    _assert_schema(response, f"{BASE}{{invoice_id}}/request-payment-doc/", "post")


# ── права: прямой вызов ERP ────────────────────────────────────────────────────────────────

WRITE = [
    ("post", "confirm-payment/", {"amount": "1.00", "paid_at": "2026-10-01"}, "json"),
    ("post", "request-payment-doc/", None, "json"),
]


@pytest.mark.parametrize("who", ["sales", "supply", "stranger"])
def test_roles_without_finance_rights_get_403_on_every_operation(world, who):
    invoice = world["invoice"]
    user = world[who]
    for path in ("", f"{invoice.pk}/"):
        response = _get(user, f"{BASE}{path}")
        assert response.status_code == 403 and response.json()["detail"] == "ROLE_NOT_PERMITTED", path
    for method, tail, body, fmt in WRITE:
        response = getattr(_client(user), method)(f"{BASE}{invoice.pk}/{tail}", body, format=fmt)
        assert response.status_code == 403 and response.json()["detail"] == "ROLE_NOT_PERMITTED", tail
    assert _attach(user, invoice.pk).status_code == 403
    proof = PaymentConfirmation.objects.create(invoice=invoice, file="x.pdf")
    assert _get(user, f"{BASE}{invoice.pk}/confirmations/{proof.pk}/file/").status_code == 403
    invoice.refresh_from_db()
    assert invoice.amount_paid == 0 and not Payment.objects.exists()


def test_anonymous_gets_401(world):
    assert _get(None, BASE).status_code == 401


def test_head_reads_the_board_and_the_card_but_the_card_hides_the_actions_without_the_payment_right(world):
    invoice = world["invoice"]
    board = _get(world["head"], BASE, tab="awaiting")
    assert board.status_code == 200 and board.json()["count"] == 1
    card = _get(world["head"], f"{BASE}{invoice.pk}/").json()
    assert card["can_confirm"] is False and card["can_attach_proof"] is False and card["can_request_proof"] is False
    assert _confirm(world["head"], invoice.pk).status_code == 403
    assert _get(world["finance"], f"{BASE}{invoice.pk}/").json()["can_confirm"] is True


def test_the_card_has_no_cost_or_margin_or_supplier_prices(world):
    card = _get(world["finance"], f"{BASE}{world['invoice'].pk}/").json()
    text = str(card).lower()
    for word in ("cost", "margin", "supplier", "purchase"):
        assert word not in text, word
    _assert_schema(_get(world["finance"], f"{BASE}{world['invoice'].pk}/"), f"{BASE}{{invoice_id}}/", "get")


def test_board_response_matches_the_contract(world):
    response = _get(world["finance"], BASE, tab="all")
    _assert_schema(response, BASE, "get")
