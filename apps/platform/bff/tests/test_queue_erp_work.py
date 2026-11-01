"""«Мои задачи»: работа ERP (D2-8, B-W15H9-1, B-UIA-2; SPEC-v3 §1.2 п. 3, §4.1).

Задания на расчёт и визы (`calc_task`), платёжки на подтверждение (`confirm_payment`), счета к
выставлению (`issue_invoice`), договор (`issue_contract`, `attach_scan`) и акт (`issue_act`): строка
— по праву роли из секции `queue` каталога, ведёт на экран, где действие делается; у совмещённой
роли дублей нет; бейджи меню и карточки — из тех же ответов ERP.
"""

from typing import Any

import pytest

from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments

NUMBER = "ЗВ-2027-104"
ENCODED = "%D0%97%D0%92-2027-104"


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def task(
    deal_id: int = 104,
    *,
    state: str = "in_progress",
    visas: dict[str, str] | None = None,
    due: str = "2027-01-15",
    number: str = NUMBER,
) -> dict[str, Any]:
    """Строка ERP `GET /calc/tasks/` (`calculation.list_tasks`)."""
    return {
        "deal": {
            "id": deal_id,
            "number": number,
            "title": "Стрелочные приводы",
            "client_name": "ООО «Демо-Депо»",
            "stage_code": "CALCULATING",
            "created_at": "2027-01-10T08:00:00Z",
            "manager_name": "Демо Менеджеров",
        },
        "letter_number": "ВХ-104/27",
        "due": due,
        "state": state,
        "lines": 3,
        "visas": visas or {"stock": "none", "supply": "waiting", "engineer": "done"},
        "assignees": [{"zone": "goods", "name": "Демо Широков"}],
    }


def receivable(inv_id: int, status: str, **over: Any) -> dict[str, Any]:
    """Строка доски ERP `GET /finance/receivables/` (`ReceivableRow`)."""
    base: dict[str, Any] = {
        "id": inv_id,
        "number": f"СЧ-2027/{inv_id}",
        "deal_id": 97,
        "deal_year": 2027,
        "client_name": "ООО «Север-Путь»",
        "currency": "UZS",
        "total_incl_vat": "28000000.00",
        "amount_paid": "0.00",
        "balance_due": "28000000.00",
        "issued_at": None if status == "draft" else "2027-01-05",
        "due_date": None if status == "draft" else "2027-01-25",
        "display_status": status,
        "days_overdue": None,
        "has_pending_proof": status == "proof_received",
        "proof_received_at": "2027-01-15T05:00:00Z" if status == "proof_received" else None,
    }
    return {**base, **over}


def project(
    deal_id: int,
    *,
    step: str = "CONTRACT",
    client_status: str = "contract_review",
    contract: dict[str, Any] | None = None,
    invoice: dict[str, Any] | None = None,
    act: dict[str, Any] | None = None,
    problems: list[str] | None = None,
) -> dict[str, Any]:
    """Строка ERP `GET /crm/projects/` (`ProjectRow`)."""
    return {
        "deal_id": deal_id,
        "title": "Автоблокировка",
        "company_name": "АО «Тест-Логистика»",
        "created_at": "2027-01-02T08:00:00Z",
        "step": step,
        "client_status": client_status,
        "total": {"amount": "56000000.00", "currency": "UZS"},
        "manager": None,
        "responsible": None,
        "due_date": None,
        "documents": {
            "quote": {"id": 1, "number": "КП-2027/001", "status": "accepted", "version": 1},
            "contract": contract,
            "invoice": invoice,
            "act": act,
        },
        "problems": problems or [],
    }


def contract(status: str, *, sent: bool = True, number: str = "ДОГ-2027/106") -> dict[str, Any]:
    return {"id": 312, "number": number, "status": status, "sent_to_client": sent}


def morning(fb: FeedBackends) -> None:
    """Утро менеджера-универсала (план 2026-11-01 §6 п. 3): расчёт, платёжка, счёт, договор."""
    fb.state["calc_tasks"] = {"results": [task(state="not_started")]}
    fb.state["receivables"] = {
        "proofs": [receivable(145, "proof_received")],
        "to_issue": [
            receivable(143, "draft", deal_id=107, client_name="АО «Тест-Логистика»"),
            # строка не черновик (гонка доски) — выставлять нечего, строки нет
            receivable(144, "issued"),
        ],
    }
    fb.state["receivable_counts"] = {"to_issue": 1, "awaiting": 3, "proofs": 1, "overdue": 0}
    fb.state["projects"] = {
        "CONTRACT": [project(106, contract=contract("issued_at_operator"))],
        "PAYMENT": [],
    }


async def queue_of(web: Web, check: ContractChecker | None = None) -> list[dict[str, Any]]:
    response = await web.client.get("/api/v1/queue")
    assert response.status_code == 200, response.json()
    if check is not None:
        check(response, "/queue", "get")
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_manager_all_morning_has_costing_payment_invoice_and_contract_rows(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    morning(fb)
    await web.login(["MANAGER_ALL"])

    items = await queue_of(web, check)

    by_kind = {i["kind"]: i for i in items}
    calc = by_kind["calc_task"]
    assert calc["title"] == f"Начать расчёт по заявке {NUMBER}"
    assert calc["subtitle"] == "ООО «Демо-Депо» · Стрелочные приводы · по письму ВХ-104/27"
    assert calc["due_label"] == "today"
    assert calc["object"] == {
        "kind": "request",
        "number": NUMBER,
        "title": "Стрелочные приводы",
        "path": f"/erp/calc/{ENCODED}",
        "step": "CALCULATION",
    }
    pay = by_kind["confirm_payment"]
    assert pay["title"] == "Подтвердить оплату по счёту СЧ-2027/145"
    assert "ООО «Север-Путь»" in pay["subtitle"]
    assert "ПР-2027-097" in pay["subtitle"]
    assert pay["object"]["path"] == "/eds/payments/145?panel=open&tab=payment"
    assert pay["due_label"] == "later"  # срока у подтверждения нет — без выдуманного «сегодня»
    assert [i["object"]["number"] for i in items if i["kind"] == "issue_invoice"] == ["СЧ-2027/143"]
    issue = by_kind["issue_invoice"]
    assert issue["title"] == "Выставить счёт СЧ-2027/143"
    assert issue["object"]["path"] == "/eds/payments/143?panel=open&tab=payment"
    scan = by_kind["attach_scan"]
    assert scan["title"] == "Прикрепить скан подписанного договора ДОГ-2027/106 по ПР-2027-106"
    assert scan["object"]["kind"] == "contract"
    assert scan["object"]["path"] == ("/eds/projects/%D0%9F%D0%A0-2027-106?panel=open&tab=contract")
    # одна строка — одно действие: у роли, совмещающей пять ролей SPEC, дублей нет
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert [i["kind"] for i in items].count("calc_task") == 1


@pytest.mark.parametrize(
    ("state", "visas", "role", "title"),
    [
        (
            "in_progress",
            {"stock": "none", "supply": "waiting", "engineer": "done"},
            "SUPPLY",
            "Завизировать строки расчёта по заявке",
        ),
        (
            "in_progress",
            {"stock": "none", "supply": "waiting", "engineer": "done"},
            "ENGINEER",
            "Рассчитать заявку",
        ),
        (
            "in_progress",
            {"stock": "done", "supply": "none", "engineer": "done"},
            "SUPPLY",
            "Отправить директору расчёт по заявке",
        ),
        (
            "returned",
            {"stock": "done", "supply": "none", "engineer": "done"},
            "ENGINEER",
            "Доработать расчёт по заявке",
        ),
    ],
)
async def test_costing_row_says_what_the_executor_does_now(
    web: Web, fb: FeedBackends, state: str, visas: dict[str, str], role: str, title: str
) -> None:
    """Виза строки — держателю визы зоны (`erp.calc.goods` — склад и снабжение, `erp.calc.services`
    — гл. инженер); состояние расчёта и визы решает ERP."""
    fb.state["calc_tasks"] = {"results": [task(state=state, visas=visas)]}
    await web.login([role])

    items = [i for i in await queue_of(web) if i["kind"] == "calc_task"]

    assert [i["title"] for i in items] == [f"{title} {NUMBER}"]
    assert fb.query(fb.erp["calc_tasks"]) == {"mine": "1"}  # «мои» решает ERP по резолюции


@pytest.mark.parametrize("state", ["at_director", "approved", "rejected"])
async def test_costing_at_the_director_or_closed_is_not_the_executors_work(
    web: Web, fb: FeedBackends, state: str
) -> None:
    fb.state["calc_tasks"] = {"results": [task(state=state)]}
    await web.login(["SUPPLY"])
    assert "calc_task" not in [i["kind"] for i in await queue_of(web)]


async def test_overdue_costing_is_red(web: Web, fb: FeedBackends) -> None:
    fb.state["calc_tasks"] = {"results": [task(due="2027-01-10")]}
    await web.login(["SUPPLY"])
    items = [i for i in await queue_of(web) if i["kind"] == "calc_task"]
    assert items[0]["due_label"] == "overdue"


@pytest.mark.parametrize("role", ["DIRECTOR", "MANAGER"])
async def test_payments_go_only_to_holders_of_the_payments_section_in_full(
    web: Web, fb: FeedBackends, role: str
) -> None:
    """Подтверждает оплату и выставляет счёт держатель `eds.payments: full` (бухгалтер,
    менеджер-универсал); директор и менеджер только читают — строк нет, ERP не спрашивается."""
    morning(fb)
    await web.login([role])

    kinds = [i["kind"] for i in await queue_of(web)]

    assert "confirm_payment" not in kinds
    assert "issue_invoice" not in kinds
    assert fb.calls(fb.erp["receivables"]) == 0


async def test_accountant_gets_payment_rows_cards_and_badge_from_the_same_board(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    """U1: пустая очередь бухгалтера не пишет «Платёжек нет», когда они есть; число бейджа и
    карточек — из той же доски ERP, что строки."""
    morning(fb)
    fb.state["receivable_counts"] = {"to_issue": 2, "awaiting": 3, "proofs": 1, "overdue": 0}
    await web.login(["ACCOUNTANT"])

    kinds = [i["kind"] for i in await queue_of(web)]
    assert kinds.count("confirm_payment") == 1
    assert kinds.count("issue_invoice") == 1
    assert "calc_task" not in kinds  # расчёт бухгалтер только читает

    cards = await web.client.get("/api/v1/queue/cards")
    check(cards, "/queue/cards", "get")
    by_key = {c["key"]: c for c in cards.json()["cards"]}
    assert by_key["payments_to_confirm"]["count"] == 1
    assert by_key["payments_to_confirm"]["path"] == "/eds/payments?show=proofs"
    assert by_key["invoices_to_issue"]["count"] == 2
    assert by_key["invoices_to_issue"]["path"] == "/eds/payments?show=to_issue"

    counters = await web.client.get("/api/v1/menu-counters")
    check(counters, "/menu-counters", "get")
    badges = {(c["module"], c["section"]): c for c in counters.json()["items"]}
    assert badges[("eds", "payments")]["count"] == 3
    assert badges[("eds", "payments")]["attention"] is True


async def test_menu_badge_of_my_costings_counts_the_queue_rows(web: Web, fb: FeedBackends) -> None:
    fb.state["calc_tasks"] = {
        "results": [task(), task(105, number="ЗВ-2027-105"), task(106, state="at_director")]
    }
    await web.login(["SUPPLY"])

    counters = (await web.client.get("/api/v1/menu-counters")).json()["items"]

    badge = next(c for c in counters if (c["module"], c["section"]) == ("erp", "calc"))
    assert badge == {"module": "erp", "section": "calc", "count": 2, "attention": True}


@pytest.mark.parametrize(
    ("row", "kind", "title"),
    [
        (
            project(104, problems=["no_contract"]),
            "issue_contract",
            "Сформировать проект договора по ПР-2027-104",
        ),
        (
            project(104, contract=contract("project", sent=False)),
            "issue_contract",
            "Отправить клиенту проект договора ДОГ-2027/106 по ПР-2027-104",
        ),
        (
            project(104, client_status="contract_signing", contract=contract("client_agreed")),
            "issue_contract",
            "Выставить у оператора договор ДОГ-2027/106 по ПР-2027-104",
        ),
        (
            project(104, contract=contract("rejected"), problems=["contract_rejected"]),
            "issue_contract",
            "Доработать договор ДОГ-2027/106 по ПР-2027-104",
        ),
    ],
)
async def test_contract_step_waiting_for_the_company_is_a_row(
    web: Web, fb: FeedBackends, row: dict[str, Any], kind: str, title: str
) -> None:
    fb.state["projects"] = {"CONTRACT": [row], "PAYMENT": []}
    await web.login(["ACCOUNTANT"])

    items = [i for i in await queue_of(web) if i["kind"] == kind]

    assert [i["title"] for i in items] == [title]
    assert items[0]["object"]["path"].endswith("?panel=open&tab=contract")


async def test_contract_at_the_client_or_signed_is_not_a_row(web: Web, fb: FeedBackends) -> None:
    fb.state["projects"] = {
        "CONTRACT": [project(104, contract=contract("project", sent=True))],
        "PAYMENT": [
            project(
                105, step="PAYMENT", client_status="awaiting_payment", contract=contract("signed")
            )
        ],
    }
    await web.login(["ACCOUNTANT"])
    kinds = {i["kind"] for i in await queue_of(web)}
    assert not kinds & {"issue_contract", "attach_scan", "issue_act"}


async def test_act_is_issued_after_payment_and_reissued_after_a_return(
    web: Web, fb: FeedBackends
) -> None:
    paid = {"id": 9, "number": "СЧ-2027/150", "status": "paid", "count": 1}
    fb.state["projects"] = {
        "CONTRACT": [],
        "PAYMENT": [
            project(
                97,
                step="PAYMENT",
                client_status="fulfilling",
                contract=contract("signed"),
                invoice=paid,
            ),
            project(
                98,
                step="PAYMENT",
                client_status="awaiting_payment",
                contract=contract("signed"),
                invoice={**paid, "status": "issued"},
            ),  # не оплачен — акт рано
            project(
                100,
                step="PAYMENT",
                client_status="awaiting_payment",
                contract=contract("signed"),
                invoice=paid,
            ),  # последний счёт оплачен, но другой ещё ждёт денег — акт рано
            project(
                99,
                step="PAYMENT",
                client_status="fulfilling",
                contract=contract("signed"),
                invoice=paid,
                act={"id": 3, "number": "АКТ-2027/003", "status": "returned"},
                problems=["act_returned"],
            ),
        ],
    }
    await web.login(["ACCOUNTANT"])

    acts = [i for i in await queue_of(web) if i["kind"] == "issue_act"]

    assert [i["title"] for i in acts] == [
        "Выпустить акт по ПР-2027-097",
        "Выпустить заново акт АКТ-2027/003 по ПР-2027-099",
    ]
    assert all(i["object"]["path"].endswith("?panel=open&tab=act") for i in acts)


async def test_erp_down_leaves_the_rest_and_hides_erp_badges(web: Web, fb: FeedBackends) -> None:
    morning(fb)
    fb.erp_down = 503
    await web.login(["ACCOUNTANT"])

    response = await web.client.get("/api/v1/queue")
    assert response.status_code == 200
    assert response.json()["sources"]["erp"] == "unavailable"
    kinds = {i["kind"] for i in response.json()["items"]}
    assert not kinds & {"confirm_payment", "issue_invoice", "issue_contract", "attach_scan"}
    counters = (await web.client.get("/api/v1/menu-counters")).json()["items"]
    assert ("eds", "payments") not in {(c["module"], c["section"]) for c in counters}
