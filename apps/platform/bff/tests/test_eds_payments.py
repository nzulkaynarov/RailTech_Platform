"""EDS · Счета и оплаты бухгалтера (BFF 0.25.0, D2-4): `/eds/payments*`, `/eds/payment-memos*`.

ERP и EDS — на respx (`eds_payments_support`), ответы BFF сверяются со схемами platform-bff.yaml.
Проверяется то, что делает BFF: разделы каталога (чтение — менеджер, действия — бухгалтер;
снабженец, инженер, администратор — 403 до доменов), сборка таблицы, карточки и служебок, тело
подтверждения в ERP, идемпотентность повтора, частичная оплата с остатком, «сумма больше остатка»
словами, проверка суммы и даты до сети, перевод ошибок ERP и EDS, файлы потоком. Остаток, статус,
право на оплату и шаг маршрута решают ERP и EDS (их тесты — отдельно).
"""

from typing import Any

import httpx
import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_payments_support import (
    PAY_DOC,
    PAY_DOC_NUMBER,
    PAY_ROUTE,
    RECEIPT_FILE,
    TODAY,
    PaymentsFake,
    eds_error,
    pay_route,
)
from tests.roles import custom

BASE = "/api/v1/eds"
BOUNDARY = "demo-boundary-d24"
READ_ONLY = custom(60, "Директор по SPEC (чтение)", {"eds.payments": "read"})
NO_PAYMENTS = custom(61, "Без счетов", {"dashboard.queue": "full", "eds.memo.create": "full"})
FULL_PAYMENT = {"amount": "112000000.00", "date": TODAY}


@pytest.fixture
def fake(be: Backends) -> PaymentsFake:
    return PaymentsFake(be)


def multipart(content: bytes = b"%PDF-1.4 demo", filename: str = "pp.pdf") -> tuple[bytes, str]:
    head = (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    )
    return (
        head.encode() + content + f"\r\n--{BOUNDARY}--\r\n".encode(),
        f"multipart/form-data; boundary={BOUNDARY}",
    )


async def post_file(web: Web, url: str, body: bytes, content_type: str) -> httpx.Response:
    return await web.client.post(
        url, content=body, headers={"content-type": content_type, CSRF_HEADER: web.csrf}
    )


async def confirm(web: Web, invoice_id: int, body: dict[str, Any], key: str | None = None) -> Any:
    headers = {CSRF_HEADER: web.csrf}
    if key:
        headers["Idempotency-Key"] = key
    return await web.client.post(
        f"{BASE}/payments/{invoice_id}/confirm", json=body, headers=headers
    )


# --- права -------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["SUPPLY", "ENGINEER", "ADMIN", NO_PAYMENTS])
async def test_roles_without_the_payments_section_get_403_everywhere_before_the_domains(
    web: Web, fake: PaymentsFake, role: Any
) -> None:
    await web.login([role])
    for url in (
        f"{BASE}/payments",
        f"{BASE}/payments/142",
        f"{BASE}/payments/142/proofs/5/file",
        f"{BASE}/payment-memos",
        f"{BASE}/payment-memos/{PAY_DOC}",
    ):
        assert (await web.client.get(url)).status_code == 403, url
    for url, body in (
        (f"{BASE}/payments/142/confirm", FULL_PAYMENT),
        (f"{BASE}/payments/142/request-payment-doc", None),
        (
            f"{BASE}/payment-memos/{PAY_DOC}/pay",
            {"paid_on": TODAY, "amount": "8500000.00", "currency": "UZS"},
        ),
    ):
        assert (await web.send("POST", url, json=body)).status_code == 403, url
    sent, content_type = multipart()
    proofs = await post_file(web, f"{BASE}/payments/142/proofs", sent, content_type)
    assert proofs.status_code == 403
    receipts = await post_file(web, f"{BASE}/payment-receipt-files", sent, content_type)
    assert receipts.status_code == 403
    assert fake.erp_requests == []
    assert fake.issued == []


@pytest.mark.parametrize("role", ["MANAGER", READ_ONLY])
async def test_read_only_roles_read_but_every_action_is_403_before_the_domains(
    web: Web, fake: PaymentsFake, role: Any
) -> None:
    await web.login([role])
    assert (await web.client.get(f"{BASE}/payments")).status_code == 200
    assert (await web.client.get(f"{BASE}/payments/142")).status_code == 200
    assert (await web.client.get(f"{BASE}/payment-memos")).status_code == 200
    assert (await web.client.get(f"{BASE}/payment-memos/{PAY_DOC}")).status_code == 200
    reads = len(fake.erp_requests)
    for url, body in (
        (f"{BASE}/payments/142/confirm", FULL_PAYMENT),
        (f"{BASE}/payments/142/request-payment-doc", None),
        (
            f"{BASE}/payment-memos/{PAY_DOC}/pay",
            {"paid_on": TODAY, "amount": "8500000.00", "currency": "UZS"},
        ),
    ):
        response = await web.send("POST", url, json=body)
        assert response.status_code == 403, url
        assert response.json()["details"] == {"resource": "eds.payments", "need": "full"}
    sent, content_type = multipart()
    proofs = await post_file(web, f"{BASE}/payments/142/proofs", sent, content_type)
    assert proofs.status_code == 403
    receipts = await post_file(web, f"{BASE}/payment-receipt-files", sent, content_type)
    assert receipts.status_code == 403
    assert len(fake.erp_requests) == reads  # ни одного изменяющего вызова в ERP
    assert fake.paid == []


async def test_session_and_csrf_are_required(web: Web, fake: PaymentsFake) -> None:
    anonymous = await web.client.get(f"{BASE}/payments")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "SESSION_EXPIRED"
    await web.login(["ACCOUNTANT"])
    stolen = await web.send("POST", f"{BASE}/payments/142/confirm", json=FULL_PAYMENT, csrf="x")
    assert stolen.status_code == 403
    assert fake.erp_made("POST", "142/confirm-payment/") == []


async def test_erp_refusal_for_a_role_without_finance_rights_is_a_403_from_erp(
    web: Web, fake: PaymentsFake
) -> None:
    """Раздел каталога пропустил (чтение), а ERP не даёт счета без права на финансы: 403 `source =
    erp`.
    """
    await web.login(["MANAGER"])
    fake.erp_status = 403
    response = await web.client.get(f"{BASE}/payments")
    assert response.status_code == 403
    assert response.json()["source"] == "erp"


# --- таблица -----------------------------------------------------------------------------------


async def test_board_maps_rows_counts_and_the_memo_badge(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])

    response = await web.client.get(f"{BASE}/payments", params={"tab": "all"})

    check(response, "/eds/payments", "get")
    body = response.json()
    assert body["tab"] == "all"
    assert body["count"] == 5
    assert body["counts"] == {"to_issue": 1, "awaiting": 1, "proofs": 1, "overdue": 1}
    assert body["memos_to_pay"] == 1
    assert body["sources"] == {"erp": "ok", "eds": "ok"}
    rows = {r["number"]: r for r in body["items"]}
    first = rows["СЧ-2026/142"]
    assert first["project_number"] == "ПР-2026-104"
    assert first["client_name"] == "ООО «Демо-Рейл»"
    assert first["amount"] == {"amount": "112000000.00", "currency": "UZS"}
    assert first["balance"] == {"amount": "112000000.00", "currency": "UZS"}
    assert first["status"] == "issued"
    assert first["due_date"] == "2026-11-07"
    assert rows["СЧ-2026/144"]["status"] == "overdue"
    assert rows["СЧ-2026/144"]["days_overdue"] == 8
    assert rows["СЧ-2026/145"]["status"] == "proof_received"
    assert rows["СЧ-2026/145"]["has_pending_proof"] is True
    assert rows["СЧ-2026/146"]["status"] == "paid"
    assert rows["СЧ-2026/143"]["status"] == "draft"


@pytest.mark.parametrize(
    ("tab", "numbers"),
    [
        ("awaiting", ["СЧ-2026/142"]),
        ("to_issue", ["СЧ-2026/143"]),
        ("proofs", ["СЧ-2026/145"]),
        ("overdue", ["СЧ-2026/144"]),
    ],
)
async def test_tabs_are_passed_to_erp(
    web: Web, fake: PaymentsFake, check: ContractChecker, tab: str, numbers: list[str]
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.client.get(
        f"{BASE}/payments", params={"tab": tab, "q": "демо", "limit": 20}
    )
    check(response, "/eds/payments", "get")
    assert [r["number"] for r in response.json()["items"]] == numbers
    [call] = fake.erp_made("GET")
    assert dict(call.url.params) == {"tab": tab, "q": "демо", "limit": "20", "offset": "0"}


async def test_default_tab_is_awaiting_and_a_bad_tab_is_422_before_erp(
    web: Web, fake: PaymentsFake
) -> None:
    await web.login(["ACCOUNTANT"])
    assert (await web.client.get(f"{BASE}/payments")).json()["tab"] == "awaiting"
    assert (await web.client.get(f"{BASE}/payments", params={"tab": "paid"})).status_code == 422
    assert (await web.client.get(f"{BASE}/payments", params={"limit": 0})).status_code == 422
    assert len(fake.erp_made("GET")) == 1


async def test_eds_down_keeps_the_board_without_the_memo_number(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    fake.eds_list_status = 503
    response = await web.client.get(f"{BASE}/payments")
    check(response, "/eds/payments", "get")
    body = response.json()
    assert body["memos_to_pay"] is None
    assert body["sources"] == {"erp": "ok", "eds": "unavailable"}
    assert len(body["items"]) == 1


async def test_erp_down_is_503(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    fake.erp_status = 500
    response = await web.client.get(f"{BASE}/payments")
    assert response.status_code == 503
    assert response.json()["source"] == "erp"


# --- карточка ----------------------------------------------------------------------------------


async def test_card_shows_proofs_payments_remainder_and_flags(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.client.get(f"{BASE}/payments/145")
    check(response, "/eds/payments/{id}", "get")
    body = response.json()
    assert body["status"] == "proof_received"
    assert body["proofs"] == [
        {
            "id": 5,
            "source": "CABINET",
            "status": "PENDING",
            "original_name": "платёжка.pdf",
            "claimed_amount": "112000000.00",
            "claimed_date": "2026-10-27",
            "note": "",
            "received_at": "2026-10-27T15:00:00Z",
            "recorded_by": None,
            "payment_id": None,
        }
    ]
    assert body["items"][0] == {
        "description": "Привод стрелочный СП-6",
        "quantity": 12,
        "unit_price": "8333333.33",
        "total": "100000000.00",
    }
    assert (body["subtotal"], body["vat"]) == ("100000000.00", "12000000.00")
    assert body["can_confirm"] is True
    assert body["replayed"] is False


async def test_card_of_an_unknown_invoice_is_404_from_erp(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.client.get(f"{BASE}/payments/999")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["source"] == "erp"


async def test_no_cost_margin_or_supplier_prices_anywhere(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    texts = [
        (await web.client.get(f"{BASE}/payments", params={"tab": "all"})).text,
        (await web.client.get(f"{BASE}/payments/142")).text,
        (await web.client.get(f"{BASE}/payment-memos")).text,
        (await web.client.get(f"{BASE}/payment-memos/{PAY_DOC}")).text,
    ]
    for text in texts:
        for word in ("cost", "margin", "supplier", "purchase"):
            assert word not in text.lower(), word


# --- подтверждение оплаты ----------------------------------------------------------------------


async def test_confirm_full_payment_closes_the_invoice(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])

    response = await confirm(web, 142, {**FULL_PAYMENT, "reference": "BANK-1"}, key="attempt-0001")

    check(response, "/eds/payments/{id}/confirm", "post")
    body = response.json()
    assert body["status"] == "paid"
    assert body["balance"]["amount"] == "0.00"
    assert body["paid"]["amount"] == "112000000.00"
    assert body["can_confirm"] is False
    assert body["payments"][0]["reference"] == "BANK-1"
    assert body["payments"][0]["paid_at"] == TODAY
    [sent] = fake.erp_made("POST", "142/confirm-payment/")
    assert sent.headers["idempotency-key"] == "attempt-0001"
    assert sent.headers["authorization"].startswith("Bearer ey")  # токен ERP из сессии сотрудника
    assert sent.read() == (
        b'{"amount":"112000000.00","paid_at":"%s","reference":"BANK-1","confirmation_id":null}'
        % TODAY.encode()
    )


async def test_partial_payment_keeps_the_remainder_visible(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])

    first = await confirm(web, 142, {"amount": "40000000.00", "date": TODAY}, key="attempt-0001")
    check(first, "/eds/payments/{id}/confirm", "post")
    assert first.json()["status"] == "partially_paid"
    assert first.json()["balance"]["amount"] == "72000000.00"
    assert first.json()["can_confirm"] is True

    rest = await confirm(web, 142, {"amount": "72000000.00", "date": TODAY}, key="attempt-0002")
    assert rest.json()["status"] == "paid"
    assert len(rest.json()["payments"]) == 2


async def test_amount_above_the_remainder_is_a_409_in_words_and_nothing_is_written(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await confirm(web, 142, {"amount": "112000000.01", "date": TODAY})
    check(response, "/eds/payments/{id}/confirm", "post")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert body["source"] == "erp"
    assert body["message"] == "Сумма больше остатка по счёту."
    assert body["details"]["reason"] == "exceeds_balance"
    assert body["details"]["fields"] == ["amount"]
    assert fake.invoices[142]["payments"] == []


async def test_repeat_with_the_same_key_is_idempotent(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    first = await confirm(web, 142, FULL_PAYMENT, key="attempt-0001")
    second = await confirm(web, 142, FULL_PAYMENT, key="attempt-0001")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(fake.invoices[142]["payments"]) == 1


async def test_repeat_without_a_key_on_a_paid_invoice_returns_the_same_payment(
    web: Web, fake: PaymentsFake
) -> None:
    await web.login(["ACCOUNTANT"])
    await confirm(web, 142, FULL_PAYMENT)
    again = await confirm(web, 142, FULL_PAYMENT)
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert len(fake.invoices[142]["payments"]) == 1
    other = await confirm(web, 142, {"amount": "1.00", "date": TODAY})
    assert other.status_code == 409
    assert other.json()["details"]["reason"] == "already_paid"


async def test_confirming_a_client_proof_links_it_and_a_repeat_is_idempotent(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    body = {**FULL_PAYMENT, "proof_id": 5}
    first = await confirm(web, 145, body)
    again = await confirm(web, 145, body)
    check(first, "/eds/payments/{id}/confirm", "post")
    assert first.json()["proofs"][0]["status"] == "CONFIRMED"
    assert first.json()["proofs"][0]["payment_id"]
    assert again.json()["replayed"] is True
    assert len(fake.invoices[145]["payments"]) == 1
    unknown = await confirm(web, 142, {**FULL_PAYMENT, "proof_id": 99})
    assert unknown.status_code == 404
    assert unknown.json()["message"] == "Платёжка не найдена."


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"amount": "0.00", "date": TODAY}, "amount"),
        ({"amount": "-5.00", "date": TODAY}, "amount"),
        ({"amount": "12", "date": TODAY}, "amount"),
        ({"amount": "1.00", "date": "2999-01-01"}, "date"),
        ({"amount": "1.00"}, "date"),
        ({"amount": "1.00", "date": TODAY, "surprise": 1}, "surprise"),
    ],
)
async def test_bad_amount_or_date_is_422_before_erp(
    web: Web, fake: PaymentsFake, body: dict[str, Any], field: str
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await confirm(web, 142, body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert f"body.{field}" in response.json()["details"]["fields"]
    assert fake.erp_made("POST", "142/confirm-payment/") == []


async def test_draft_invoice_cannot_be_confirmed(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    response = await confirm(web, 143, FULL_PAYMENT)
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "not_issued"


async def test_erp_date_refusal_is_a_422_on_the_date_field(web: Web, fake: PaymentsFake) -> None:
    """Часы ERP и BFF могут разойтись: отказ ERP по дате — 422 на поле `date`, а не 500."""
    await web.login(["ACCOUNTANT"])
    fake.reject_date = True
    response = await confirm(web, 142, FULL_PAYMENT)
    assert response.status_code == 422
    assert response.json()["details"]["fields"] == ["date"]
    assert response.json()["details"]["reason"] == "payment_date_in_future"


# --- платёжка клиента и запрос платёжки --------------------------------------------------------


async def test_attach_proof_passes_the_multipart_body_as_is(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    body, content_type = multipart()

    response = await post_file(web, f"{BASE}/payments/142/proofs", body, content_type)

    assert response.status_code == 201, response.text
    check(response, "/eds/payments/{id}/proofs", "post")
    assert response.json()["status"] == "proof_received"
    assert response.json()["proofs"][0]["source"] == "EMAIL"
    [sent] = fake.erp_made("POST", "142/confirmations/")
    assert sent.read() == body
    assert sent.headers["content-type"] == content_type


async def test_attach_proof_to_a_paid_invoice_is_a_409(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    body, content_type = multipart()
    response = await post_file(web, f"{BASE}/payments/146/proofs", body, content_type)
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "not_open"


async def test_attach_proof_needs_multipart_and_has_a_size_limit(
    web: Web, fake: PaymentsFake
) -> None:
    from app.api.eds_documents import MAX_BODY_BYTES

    await web.login(["ACCOUNTANT"])
    plain = await post_file(web, f"{BASE}/payments/142/proofs", b"x", "application/json")
    assert plain.status_code == 422
    assert plain.json()["details"]["reason"] == "multipart_required"
    big = await post_file(
        web,
        f"{BASE}/payments/142/proofs",
        b"x" * (MAX_BODY_BYTES + 1),
        f"multipart/form-data; boundary={BOUNDARY}",
    )
    assert big.status_code == 413
    assert fake.erp_made("POST", "142/confirmations/") == []


async def test_proof_file_streams_as_an_attachment(web: Web, fake: PaymentsFake) -> None:
    await web.login(["MANAGER"])
    response = await web.client.get(f"{BASE}/payments/145/proofs/5/file")
    assert response.status_code == 200
    assert response.content == fake.proof_bytes
    assert response.headers["content-disposition"] == "attachment; filename=pp.pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (await web.client.get(f"{BASE}/payments/145/proofs/99/file")).status_code == 404


async def test_request_payment_doc_is_logged_on_the_card(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.send("POST", f"{BASE}/payments/142/request-payment-doc")
    check(response, "/eds/payments/{id}/request-payment-doc", "post")
    body = response.json()
    assert body["payment_doc_requested_at"] == "2026-10-28T09:10:00Z"
    assert body["history"][0]["code"] == "payment_doc.requested"
    closed = await web.send("POST", f"{BASE}/payments/146/request-payment-doc")
    assert closed.status_code == 409
    assert closed.json()["details"]["reason"] == "not_open"


# --- служебки к оплате -------------------------------------------------------------------------


async def test_memo_list_and_card(web: Web, fake: PaymentsFake, check: ContractChecker) -> None:
    await web.login(["ACCOUNTANT"])

    listing = await web.client.get(f"{BASE}/payment-memos")
    check(listing, "/eds/payment-memos", "get")
    assert listing.json()["items"] == [
        {
            "id": PAY_DOC,
            "number": PAY_DOC_NUMBER,
            "subject": "Оплата аренды склада за ноябрь",
            "author": {"crm_user_id": 2, "full_name": "Менеджер Демо"},
            "amount": {"amount": "8500000.00", "currency": "UZS"},
            "due_date": "2026-10-31",
            "files_count": 1,
            "invoice_attached": True,
            "status": "to_pay",
            "paid_on": None,
            "created_at": "2026-10-27T10:00:00Z",
        }
    ]
    [call] = [
        c for c in fake.calls if c.url.path == "/api/v1/documents" and "limit" in c.url.params
    ]
    assert call.url.params["kind"] == "memo"
    assert call.url.params["status"] == "to_accountant"

    card = await web.client.get(f"{BASE}/payment-memos/{PAY_DOC}")
    check(card, "/eds/payment-memos/{id}", "get")
    body = card.json()
    assert body["can_pay"] is True
    assert body["can_return"] is True
    assert body["status"] == "to_pay"
    assert body["approval_id"] == PAY_ROUTE
    assert body["payment"] is None
    assert body["files"][0]["name"] == "счёт-аренда.pdf"


async def test_memo_card_hides_the_actions_from_someone_whose_step_it_is_not(
    web: Web, fake: PaymentsFake
) -> None:
    await web.login(["ACCOUNTANT"])
    fake.routes[PAY_ROUTE] = pay_route(can_decide=False, allowed_decisions=[])
    body = (await web.client.get(f"{BASE}/payment-memos/{PAY_DOC}")).json()
    assert body["can_pay"] is False
    assert body["can_return"] is False


async def test_pay_memo_sends_date_amount_and_receipt_to_eds(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    body = {
        "paid_on": TODAY,
        "amount": "8500000.00",
        "currency": "UZS",
        "receipt_file_id": RECEIPT_FILE,
        "note": "Платёжка №15",
    }

    response = await web.send("POST", f"{BASE}/payment-memos/{PAY_DOC}/pay", json=body)

    check(response, "/eds/payment-memos/{id}/pay", "post")
    card = response.json()
    assert card["status"] == "paid"
    assert card["can_pay"] is False
    assert card["payment"]["paid_on"] == TODAY
    assert card["payment"]["paid_by"]["full_name"] == "Бахтиёр Бухгалтеров"
    assert card["payment"]["receipt_file_id"] == RECEIPT_FILE
    assert card["journal"][-1]["action"] == "document.paid"
    assert fake.paid == [
        {
            "paid_on": TODAY,
            "amount": {"amount": "8500000.00", "currency": "UZS"},
            "receipt_file_id": RECEIPT_FILE,
            "note": "Платёжка №15",
        }
    ]
    again = await web.send("POST", f"{BASE}/payment-memos/{PAY_DOC}/pay", json=body)
    assert again.status_code == 200
    assert len(fake.paid) == 1
    paid_list = await web.client.get(f"{BASE}/payment-memos", params={"status": "paid"})
    assert paid_list.json()["items"][0]["status"] == "paid"
    assert paid_list.json()["items"][0]["paid_on"] == TODAY


@pytest.mark.parametrize(
    "body",
    [
        {"paid_on": TODAY, "amount": "0.00", "currency": "UZS"},
        {"paid_on": "2999-01-01", "amount": "1.00", "currency": "UZS"},
        {"paid_on": TODAY, "amount": "1.00", "currency": "uzs"},
        {"paid_on": TODAY, "amount": "1.00", "currency": "UZS", "surprise": 1},
    ],
)
async def test_pay_memo_validates_before_eds(
    web: Web, fake: PaymentsFake, body: dict[str, Any]
) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.send("POST", f"{BASE}/payment-memos/{PAY_DOC}/pay", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert fake.paid == []


async def test_eds_refusals_are_translated(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    over = await web.send(
        "POST",
        f"{BASE}/payment-memos/{PAY_DOC}/pay",
        json={"paid_on": TODAY, "amount": "8500000.01", "currency": "UZS"},
    )
    assert over.status_code == 422
    assert over.json()["details"]["fields"] == ["amount"]
    assert over.json()["details"]["messages"] == {"amount": "exceeds_approved"}
    assert over.json()["source"] == "eds"
    fake.answer(
        "POST",
        f"documents/{PAY_DOC}/payment",
        httpx.Response(
            403, json=eds_error("FORBIDDEN", "Сейчас решение за другим.", reason="not_your_step")
        ),
    )
    foreign = await web.send(
        "POST",
        f"{BASE}/payment-memos/{PAY_DOC}/pay",
        json={"paid_on": TODAY, "amount": "8500000.00", "currency": "UZS"},
    )
    assert foreign.status_code == 403
    assert foreign.json()["details"]["reason"] == "not_your_step"


async def test_pay_memo_with_another_amount_after_payment_is_409(
    web: Web, fake: PaymentsFake
) -> None:
    await web.login(["ACCOUNTANT"])
    good = {"paid_on": TODAY, "amount": "8500000.00", "currency": "UZS"}
    await web.send("POST", f"{BASE}/payment-memos/{PAY_DOC}/pay", json=good)
    other = await web.send(
        "POST", f"{BASE}/payment-memos/{PAY_DOC}/pay", json={**good, "amount": "1000.00"}
    )
    assert other.status_code == 409
    assert other.json()["details"]["reason"] == "already_paid"


async def test_receipt_upload_goes_to_eds_with_the_payments_section(
    web: Web, fake: PaymentsFake, check: ContractChecker
) -> None:
    await web.login(["ACCOUNTANT"])
    body, content_type = multipart()
    response = await post_file(web, f"{BASE}/payment-receipt-files", body, content_type)
    assert response.status_code == 201, response.text
    check(response, "/eds/payment-receipt-files", "post")
    assert response.json()["id"] == RECEIPT_FILE
    [sent] = [c for c in fake.calls if c.method == "POST" and c.url.path == "/api/v1/files"]
    assert sent.read() == body
    assert sent.headers["content-type"] == content_type


async def test_non_memo_document_is_404(web: Web, fake: PaymentsFake) -> None:
    await web.login(["ACCOUNTANT"])
    fake.documents[PAY_DOC] = {**fake.documents[PAY_DOC], "kind": "report"}
    assert (await web.client.get(f"{BASE}/payment-memos/{PAY_DOC}")).status_code == 404


async def test_unknown_erp_status_is_a_503_bad_response_not_a_500(
    web: Web, fake: PaymentsFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ERP прислал неизвестный статус: BFF не падает, а отвечает «источник недоступен»."""
    await web.login(["ACCOUNTANT"])
    monkeypatch.setattr("tests.eds_payments_support.display_status", lambda _inv: "weird")

    card = await web.client.get(f"{BASE}/payments/142")
    board = await web.client.get(f"{BASE}/payments", params={"tab": "all"})

    assert card.status_code == 503
    assert card.json()["source"] == "erp"
    assert board.status_code == 503
