"""«Выставить счёт» из Платформы (B-D24-4, D2-8): BFF `POST /eds/payments/{id}/issue` → ERP
`POST /crm/invoices/{id}/issue/`; ответ — карточка счёта после выставления. Право — раздел
`eds.payments` полный (каталог: ERP `finance.invoice`), права ERP проверяет сам ERP.
"""

import re
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.eds_payments_support import PaymentsFake

BASE = "/api/v1/eds"
ISSUE = re.compile(rf"^{re.escape(ERP_URL)}/api/v1/crm/invoices/(\d+)/issue/$")


class IssueFake(PaymentsFake):
    """ERP счетов и выставление черновика: `DRAFT` → `ISSUED` или отказ с кодом ERP."""

    def __init__(self, be: Backends) -> None:
        super().__init__(be)
        self.issue_reply: tuple[int, dict[str, Any]] | None = None
        self.issue_calls: list[int] = []
        be.router.post(url__regex=ISSUE).mock(side_effect=self._issue)

    def _issue(self, request: httpx.Request) -> httpx.Response:
        match = ISSUE.match(str(request.url))
        assert match is not None
        invoice_id = int(match[1])
        self.issue_calls.append(invoice_id)
        if self.issue_reply is not None:
            status, body = self.issue_reply
            return httpx.Response(status, json=body)
        inv = self.invoices[invoice_id]
        if inv["status"] != "DRAFT":
            return httpx.Response(400, json={"detail": "INVOICE_ALREADY_ISSUED"})
        inv.update(status="ISSUED", issued_at="2026-10-28", due_date="2026-11-07")
        return httpx.Response(200, json={"id": invoice_id, "status": "ISSUED"})


@pytest.fixture
def fake(be: Backends) -> IssueFake:
    return IssueFake(be)


@pytest.mark.parametrize("role", ["ACCOUNTANT", "MANAGER_ALL"])
async def test_draft_is_issued_and_the_card_comes_back_issued(
    web: Web, fake: IssueFake, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.send("POST", f"{BASE}/payments/143/issue")

    assert response.status_code == 200, response.json()
    check(response, "/eds/payments/{id}/issue", "post")
    body = response.json()
    assert body["id"] == 143
    assert body["status"] == "issued"
    assert body["issued_at"] == "2026-10-28"
    assert fake.issue_calls == [143]


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("INVOICE_ALREADY_ISSUED", "already_issued"),
        ("SELLER_BANK_DETAILS_REQUIRED", "bank_details_required"),
    ],
)
async def test_erp_refusal_is_a_conflict_with_a_reason(
    web: Web, fake: IssueFake, check: ContractChecker, code: str, reason: str
) -> None:
    fake.issue_reply = (400, {"detail": code})
    await web.login(["ACCOUNTANT"])

    response = await web.send("POST", f"{BASE}/payments/143/issue")

    assert response.status_code == 409
    check(response, "/eds/payments/{id}/issue", "post")
    assert response.json()["source"] == "erp"
    assert response.json()["details"]["reason"] == reason


async def test_not_a_seller_member_is_forbidden_by_erp(web: Web, fake: IssueFake) -> None:
    fake.issue_reply = (400, {"detail": "MEMBER_REQUIRED_FOR_ACTION"})
    await web.login(["ACCOUNTANT"])
    response = await web.send("POST", f"{BASE}/payments/143/issue")
    assert response.status_code == 403
    assert response.json()["source"] == "erp"


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER"])
async def test_read_only_roles_cannot_issue_and_erp_is_not_called(
    web: Web, fake: IssueFake, role: str
) -> None:
    await web.login([role])
    response = await web.send("POST", f"{BASE}/payments/143/issue")
    assert response.status_code == 403
    assert response.json()["details"] == {"resource": "eds.payments", "need": "full"}
    assert fake.issue_calls == []


async def test_csrf_is_required(web: Web, fake: IssueFake) -> None:
    await web.login(["ACCOUNTANT"])
    response = await web.send("POST", f"{BASE}/payments/143/issue", csrf="x")
    assert response.status_code == 403
    assert fake.issue_calls == []


@pytest.mark.parametrize("role", ["ACCOUNTANT", "MANAGER_ALL"])
async def test_missing_bank_details_are_known_before_the_click(
    web: Web, fake: IssueFake, check: ContractChecker, role: str
) -> None:
    """D26G-6: ERP говорит заранее, что реквизитов своей компании нет, — доска «К выставлению» и
    карточка черновика несут `bank_details_ready: false`; у выставленного счёта — `true`."""
    fake.bank_ready = False
    await web.login([role])

    board = await web.client.get(f"{BASE}/payments", params={"tab": "to_issue"})
    draft = await web.client.get(f"{BASE}/payments/143")
    issued = await web.client.get(f"{BASE}/payments/142")

    check(board, "/eds/payments", "get")
    check(draft, "/eds/payments/{id}", "get")
    assert board.json()["bank_details_ready"] is False
    assert draft.json()["bank_details_ready"] is False
    assert issued.json()["bank_details_ready"] is True
    assert fake.issue_calls == []  # предупреждение — без попытки выставить

    fake.bank_ready = True
    assert (await web.client.get(f"{BASE}/payments/143")).json()["bank_details_ready"] is True
