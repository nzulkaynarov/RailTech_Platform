"""УВ-1: уведомления открывают действие, а не «ничего»; заголовок ERP — на языке сотрудника."""

from typing import Any

import pytest

from app.feeds.notifications import map_crm, map_erp
from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, notification


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


def test_platform_link_from_erp_is_followed() -> None:
    row = erp_row(
        "portal.bank_change_requested",
        "Запрос на смену банковских реквизитов: ООО Альфа",
        link="/eds/payments?show=bank_changes",
        company="ООО Альфа",
    )
    note = map_erp(row, {})
    assert note is not None
    assert note.object is not None
    assert note.object.path == "/eds/payments?show=bank_changes"
    assert note.object.number == "ООО Альфа"


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
    assert uz.title == "Tijorat taklifini kelishish kerak"
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
