"""УВ-1: уведомления открывают действие, а не «ничего»; заголовок ERP — на языке сотрудника."""

from typing import Any

import pytest

from app.feeds.notifications import map_crm, map_erp
from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, deal, notification


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def erp_row(event: str, title: str, *, link: str = "", **params: Any) -> dict[str, Any]:
    row = notification(1, event, title)
    row["link"] = link
    row["event_params"] = params
    return row


def test_quote_approval_notification_opens_the_approve_tab_by_quote_number() -> None:
    row = erp_row(
        "quote.approval_your_turn",
        "Требуется согласование КП",
        link="#deal-quote/5",
        number="КП-2027/7",
    )
    note = map_erp(row, {})
    assert note is not None
    assert note.object is not None
    assert note.object.path == "/eds/drafts/%D0%9A%D0%9F-2027%2F7?panel=open&tab=approve"


def test_informational_quote_notifications_open_the_card_not_the_approve_tab() -> None:
    row = erp_row("quote.visas_complete", "Визы собраны", link="#deal-quote/5", number="КП-2027/7")
    note = map_erp(row, {})
    assert note is not None
    assert note.object is not None
    assert note.object.path.endswith("?panel=open&tab=card")


def test_bank_change_opens_the_clients_queue_with_bank_changes() -> None:
    row = erp_row(
        "portal.bank_change_requested",
        "Запрос на смену банковских реквизитов: ООО Альфа",
        link="/eds/payments?show=bank_changes",
        company="ООО Альфа",
    )
    note = map_erp(row, {})
    assert note is not None
    assert note.object is not None
    assert note.object.path == "/crm/clients?kind=bank_changes"
    assert note.object.number == "ООО Альфа"


@pytest.mark.parametrize(
    ("link", "opens"),
    [
        ("/eds/projects/D-1", True),
        ("/erp/stock/PO-1", True),
        ("/crm/leads?lead=L-1", True),
        ("/crm/clients?kind=all", True),
        ("/crm/kb", True),
        ("/crm/deals/5", False),
        ("/crm/deals", False),
        ("/crm/quotes", False),
        ("/crm/documents", False),
        ("/crm/leads/12", False),
        ("/crm/clientsx", False),
        ("/admin/anything", False),
    ],
)
def test_only_routes_the_platform_opens_are_taken_from_the_erp_link(link: str, opens: bool) -> None:
    note = map_erp(erp_row("deal.created", "Сделка", link=link), {})
    assert note is not None
    assert (note.object is not None) is opens
    if opens:
        assert note.object is not None
        assert note.object.path == link


@pytest.mark.parametrize("link", ["/crm/deals/5", "/crm/deals", "/crm/quotes", "/crm/documents"])
def test_old_erp_link_with_a_deal_falls_back_to_the_deal_card(link: str) -> None:
    row = notification(1, "deal.assigned", "Назначена сделка", deal_id=5)
    row["link"] = link
    deals = {5: deal(5, "QUOTE_SENT", title="Приводы")}
    note = map_erp(row, deals)
    assert note is not None
    assert note.object is not None
    assert note.object.path.startswith("/erp/requests?request=")


def test_calc_visa_holder_without_drafts_gets_the_request_not_the_forbidden_quote() -> None:
    row = erp_row(
        "quote.approval_your_turn", "Требуется согласование КП", link="#deal-quote/5", number="КП-1"
    )
    deals = {5: deal(5, "QUOTE_SENT", title="Приводы")}
    with_drafts = map_erp(row, deals, "ru", True)
    without = map_erp(row, deals, "ru", False)
    assert with_drafts is not None
    assert with_drafts.object is not None
    assert with_drafts.object.path.startswith("/eds/drafts/")
    assert without is not None
    assert without.object is not None
    assert without.object.path.startswith("/erp/requests?request=")


def test_legacy_link_without_deal_gives_no_object() -> None:
    row = erp_row("deal.assigned", "Назначена сделка", link="#deal/12")
    note = map_erp(row, {})
    assert note is not None
    assert note.object is None


def test_title_follows_the_staff_language_and_falls_back_to_erp_title() -> None:
    row = erp_row("quote.approval_your_turn", "Требуется согласование КП", number="КП-1")
    en, uz, ru = map_erp(row, {}, "en"), map_erp(row, {}, "uz"), map_erp(row, {}, "ru")
    assert en is not None
    assert uz is not None
    assert ru is not None
    assert en.title == "Quote approval needed"
    assert uz.title == "Tijorat taklifini kelişiş kerak"
    assert ru.title == "Требуется согласование КП"
    unknown = map_erp(erp_row("deal.created", "Создана сделка"), {}, "en")
    assert unknown is not None
    assert unknown.title == "Создана сделка"
    # нужного параметра нет — не печатаем пустую скобку, остаётся заголовок ERP
    no_company = map_erp(erp_row("portal.bank_change_requested", "Запрос"), {}, "en")
    assert no_company is not None
    assert no_company.title == "Запрос"


@pytest.mark.parametrize("kind", ["eds.approve_memo", "eds.pay_memo"])
def test_memo_decision_notice_opens_the_decision_window_not_the_document_card(kind: str) -> None:
    note = map_crm(
        {
            "id": 3,
            "kind": kind,
            "tab": "decisions",
            "title": "Согласуйте: Служебка СЗ-2026/014",
            "object_kind": "document",
            "object_id": "7f9c1c3e-0000-4000-8000-000000000001",
            "object_number": "СЗ-2026/014",
            "created_at": "2027-01-15T07:55:00Z",
            "read": False,
        }
    )
    assert note is not None
    assert note.object is not None
    assert note.object.path == (
        "/eds/approvals/7f9c1c3e-0000-4000-8000-000000000001?panel=open&tab=agree"
    )
    assert note.object.number == "СЗ-2026/014"


def test_other_document_notice_still_opens_the_document_card() -> None:
    note = map_crm(
        {
            "id": 4,
            "kind": "eds.rework_document",
            "tab": "decisions",
            "title": "Доработайте",
            "object_kind": "document",
            "object_id": "7f9c1c3e-0000-4000-8000-000000000001",
            "object_number": "СЗ-2026/014",
            "created_at": "2027-01-15T07:55:00Z",
            "read": False,
        }
    )
    assert note is not None
    assert note.object is not None
    assert note.object.path.startswith("/eds/documents?scope=all&doc=")


async def test_feed_uses_the_session_language(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["notifications"]["results"] = [
        erp_row("quote.approval_your_turn", "Требуется согласование КП", number="КП-1")
    ]
    web.be.profile["language"] = "en"
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200
    check(response, "/notifications", "get")
    (item,) = response.json()["items"]
    assert item["title"] == "Quote approval needed"
    assert item["object"]["path"].endswith("?panel=open&tab=approve")


def test_needs_action_follows_the_decisions_tab() -> None:
    """УВЕД-1: «требует действия» — от вкладки «Решения»; к сведению — остальное."""
    decision = map_erp(erp_row("quote.submitted_for_review", "КП на согласовании", number="КП-1"), {})
    info = map_erp(erp_row("document.created", "Документ создан"), {})
    assert decision is not None and decision.needs_action is True
    assert info is not None and info.needs_action is False
