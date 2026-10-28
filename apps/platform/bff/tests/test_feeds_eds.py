"""EDS в «Моей очереди», счётчиках и поиске (D1-6, контракт 0.25.0): письма без резолюции и
служебки на моём шаге маршрута — строки по секции `queue` каталога, поиск по реестру EDS,
частичный ответ `sources.eds`, права — по токену `aud=eds` и разделам каталога."""

from typing import Any

import httpx
import pytest

from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, deal, quote
from tests.roles import custom, rid


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


LETTER_ID = "20000000-0000-4000-8000-000000000104"


def letter_row(number: str = "ВХ-104/26", *, urgent: bool = True, due: str | None = None) -> Any:
    return {
        "id": LETTER_ID
        if number == "ВХ-104/26"
        else f"2000{number[3:6]}-0000-4000-8000-000000000001",
        "number": number,
        "subject": "Запрос коммерческого предложения на стрелочные приводы",
        "sender": {"name": "ООО «Демо-Рейл»", "inn": "300123456", "contact": "Алия Демо"},
        "received_at": "2027-01-13",
        "status": "awaiting_resolution",
        "links": {"deal_number": "ЗВ-2026-104"},
        "urgent": urgent,
        "due": due,
    }


def route(number: str = "СЗ-2026/031", *, template: str = "memo", step: str = "Директор") -> Any:
    tail = number.split("/")[-1].zfill(12)
    return {
        "id": f"50000000-0000-4000-8000-{tail}",
        "template": template,
        "title": "Закупка кофе для офиса",
        "object": {
            "kind": "document",
            "document_id": f"60000000-0000-4000-8000-{tail}",
            "number": number,
        },
        "status": "open",
        "current_step": {"index": 1, "label": step, "status": "current"},
        "created_at": "2027-01-14T04:00:00Z",
    }


def page(*items: Any) -> dict[str, Any]:
    return {"items": list(items), "next_cursor": None}


def registry_item(kind: str, number: str | None, **over: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": "70000000-0000-4000-8000-000000000001",
        "number": number,
        "title": "Закупка кофе для офиса",
        "status": "open",
        "registered_at": "2027-01-14T04:00:00Z",
        "responsible": None,
        "client": {"name": "ООО «Демо-Рейл»"},
        "links": {},
        **over,
    }


# --- Моя очередь ------------------------------------------------------------------------------


async def test_director_queue_gets_letters_and_memos_from_eds(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["letters"] = page(letter_row(), letter_row("ВХ-105/26", urgent=False))
    fb.state["memos"] = page(route(), route("ЗЯ-2026/003", template="application"))
    fb.state["approvals"] = {
        "count": 1,
        "results": [quote(11, 5, number="КП-2026/118", valid_until="2027-01-16")],
    }
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "ok"}
    by_number = {i["object"]["number"]: i for i in body["items"]}
    urgent = by_number["ВХ-104/26"]
    assert urgent["kind"] == "resolve_letter"
    assert urgent["title"] == "Наложить резолюцию на письмо ВХ-104/26"
    assert urgent["due_label"] == "today"  # срочное письмо без срока — сегодня
    assert urgent["role_id"] == rid("DIRECTOR")
    assert "ООО «Демо-Рейл»" in urgent["subtitle"]
    assert urgent["object"]["path"] == "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution"
    assert by_number["ВХ-105/26"]["due_label"] == "later"
    memo = by_number["СЗ-2026/031"]
    assert (memo["kind"], memo["due_label"]) == ("approve_memo", "memo")
    assert memo["title"] == "Согласовать СЗ-2026/031 · Закупка кофе для офиса"
    assert memo["object"]["kind"] == "memo"
    assert memo["object"]["path"] == "/eds/approvals/%D0%A1%D0%97-2026%2F031?panel=open&tab=agree"
    assert by_number["ЗЯ-2026/003"]["kind"] == "approve_memo"
    assert by_number["КП-2026/118"]["kind"] == "approve_quote"  # КП по-прежнему ведёт ERP
    # срочное письмо — выше служебок и КП на завтра
    assert body["items"][0]["object"]["number"] == "ВХ-104/26"
    # EDS читают под токеном сотрудника (aud=eds), запросы — по виду работы
    letters = fb.eds["letters"].calls.last.request
    assert letters.headers["authorization"] == "Bearer eds-access-1"
    assert dict(letters.url.params) == {"status": "awaiting_resolution", "limit": "50"}
    approvals = fb.eds["approvals"].calls.last.request
    assert approvals.url.params["mine"] == "true"
    assert approvals.url.params.get_list("template") == ["memo", "application", "report"]


async def test_letter_due_date_gives_the_badge(web: Web, fb: FeedBackends) -> None:
    fb.state["letters"] = page(letter_row(urgent=False, due="2027-01-16"))
    await web.login(["DIRECTOR"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    letter = next(i for i in items if i["kind"] == "resolve_letter")
    assert (letter["due_label"], letter["due_at"]) == ("tomorrow", "2027-01-16T18:59:59Z")


async def test_accountant_gets_memos_on_his_step_to_pay(web: Web, fb: FeedBackends) -> None:
    fb.state["memos"] = page(route("СЗ-2026/015", step="Бухгалтер"))
    await web.login(["ACCOUNTANT"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert [(i["kind"], i["title"]) for i in items] == [
        ("pay_memo", "Принять к оплате СЗ-2026/015 · Закупка кофе для офиса")
    ]
    assert items[0]["subtitle"].startswith("Бухгалтер")
    assert fb.calls(fb.eds["letters"]) == 0  # писем бухгалтеру не нужно: резолюция — директору


async def test_eds_down_keeps_the_rest_and_marks_the_source(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.eds_down = httpx.ConnectError("down")
    fb.state["approvals"] = {"count": 1, "results": [quote(11, 5, number="КП-2026/118")]}
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "unavailable"}
    assert [i["kind"] for i in body["items"]] == ["approve_quote"]  # не «пустая очередь»


async def test_eds_5xx_is_a_partial_answer_too(web: Web, fb: FeedBackends) -> None:
    fb.eds_down = 503
    await web.login(["DIRECTOR"])

    body = (await web.client.get("/api/v1/queue")).json()

    assert body["sources"]["eds"] == "unavailable"


async def test_eds_refuses_the_employee_by_token_not_by_the_bff(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    """Права — по токену `aud=eds`: EDS не пустил сотрудника — ни строк, ни плашки."""
    fb.eds_exchange_status = 403
    fb.state["approvals"] = {"count": 1, "results": [quote(11, 5, number="КП-2026/118")]}
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT")]
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"]["eds"] == "not_applicable"
    assert [i["kind"] for i in body["items"]] == ["approve_quote"]


async def test_no_eds_section_means_no_eds_call(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    await web.login(
        [custom(90, "Только клиенты", {"dashboard.queue": "full", "crm.leads": "full"})]
    )

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    assert response.json()["sources"] == {"crm": "ok", "erp": "ok"}  # `eds` — нет: не обращались
    assert fb.eds_exchange.call_count == 0
    assert fb.calls(fb.eds["letters"]) == fb.calls(fb.eds["approvals"]) == 0


async def test_manager_with_read_only_eds_sections_does_not_call_eds(
    web: Web, fb: FeedBackends
) -> None:
    """У менеджера `eds.inbox` и `eds.drafts` — чтение: решений по письмам и КП у него нет. EDS он
    читает только ради своих возвращённых документов («Доработать», D1-6b)."""
    await web.login(["MANAGER"])

    body = (await web.client.get("/api/v1/queue")).json()

    assert body["sources"]["eds"] == "ok"
    assert fb.calls(fb.eds["letters"]) == fb.calls(fb.eds["approvals"]) == 0


# --- карточки и бейджи меню -------------------------------------------------------------------


async def test_director_cards_and_menu_badges_count_eds_work(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["letters"] = page(letter_row(), letter_row("ВХ-105/26"), letter_row("ВХ-106/26"))
    fb.state["memos"] = page(route())
    fb.state["approvals"] = {"count": 2, "results": [quote(11, 5, number="КП-2026/118")]}
    await web.login(["DIRECTOR"])

    cards_response = await web.client.get("/api/v1/queue/cards")
    counters_response = await web.client.get("/api/v1/menu-counters")

    check(cards_response, "/queue/cards", "get")
    cards = {c["key"]: c for c in cards_response.json()["cards"]}
    assert list(cards)[:3] == [
        "letters_without_resolution",
        "quotes_to_approve",
        "memos_to_approve",
    ]
    assert cards["letters_without_resolution"]["count"] == 3
    assert cards["letters_without_resolution"]["path"] == "/eds/inbox"
    assert cards["memos_to_approve"]["count"] == 1
    assert cards["memos_to_approve"]["path"] == "/eds/approvals"
    check(counters_response, "/menu-counters", "get")
    counters = {(c["module"], c["section"]): c for c in counters_response.json()["items"]}
    assert counters[("eds", "inbox")]["count"] == 3
    assert counters[("eds", "inbox")]["attention"] is True
    assert counters[("eds", "approvals")]["count"] == 1


async def test_eds_down_hides_its_cards_and_badges(web: Web, fb: FeedBackends) -> None:
    """Ноль вместо «не знаем» был бы ложью: карточек и бейджей EDS нет, плашка — в `sources`."""
    fb.eds_down = httpx.ConnectError("down")
    await web.login(["DIRECTOR"])

    cards = (await web.client.get("/api/v1/queue/cards")).json()
    counters = (await web.client.get("/api/v1/menu-counters")).json()

    assert "letters_without_resolution" not in [c["key"] for c in cards["cards"]]
    assert "memos_to_approve" not in [c["key"] for c in cards["cards"]]
    assert cards["sources"]["eds"] == counters["sources"]["eds"] == "unavailable"
    assert ("eds", "inbox") not in [(c["module"], c["section"]) for c in counters["items"]]


# --- поиск по реестру EDS ---------------------------------------------------------------------


async def test_search_finds_letters_memos_and_documents_in_the_eds_registry(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["registry"] = page(
        registry_item("letter_in", "ВХ-104/26", title="Запрос КП на стрелочные приводы"),
        registry_item("memo", "СЗ-2026/031", status="on_approval"),
        registry_item("application", "ЗЯ-2026/003", status="draft"),
        registry_item("letter_out", "ИСХ-027/26", status="sent"),
        registry_item("quote", "КП-2026/118", status="open"),
        registry_item("report", None),  # без номера — не показываем
    )
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "kp-2026"})

    assert response.status_code == 200
    check(response, "/search", "get")
    body = response.json()
    assert body["sources"]["eds"] == "ok"
    hits = {h["object"]["number"]: h["object"] for g in body["groups"] for h in g["items"]}
    assert hits["ВХ-104/26"]["path"] == "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution"
    assert hits["СЗ-2026/031"]["path"].startswith("/eds/approvals/%D0%A1%D0%97-2026%2F031")
    assert hits["СЗ-2026/031"]["path"].endswith("?panel=open&tab=agree")
    assert hits["ЗЯ-2026/003"]["path"] == "/eds/documents?doc=70000000-0000-4000-8000-000000000001"
    assert hits["ИСХ-027/26"]["path"] == "/eds/documents?doc=70000000-0000-4000-8000-000000000001"
    assert hits["КП-2026/118"]["path"].endswith("tab=approve")
    assert "None" not in hits
    # EDS получил запрос с латинской раскладкой, исправленной на кириллицу, и токен сотрудника
    request = fb.eds["registry"].calls.last.request
    assert request.url.params["q"] == "КП-2026"
    assert request.headers["authorization"] == "Bearer eds-access-1"


async def test_record_kind_not_opened_by_a_section_of_the_role_is_not_found(
    web: Web, fb: FeedBackends
) -> None:
    """EDS вернул записи, но разделы каталога роли их вид не открывают — их нет в результатах.

    Второй замок: сам доступ к реестру EDS проверяет по `registry.read` (тест EDS
    `test_registry_requires_registry_read`), BFF только не показывает вид, не открытый роли."""
    fb.state["registry"] = page(
        registry_item("letter_in", "ВХ-104/26"),
        registry_item("quote", "КП-2026/118"),
        registry_item("memo", "СЗ-2026/031", status="on_approval"),
    )
    # читает только КП (eds.drafts): письма и служебки — не его разделы
    await web.login([custom(91, "Только КП", {"dashboard.queue": "full", "eds.drafts": "read"})])

    response = await web.client.get("/api/v1/search", params={"q": "2026"})

    numbers = [h["object"]["number"] for g in response.json()["groups"] for h in g["items"]]
    assert numbers == ["КП-2026/118"]


async def test_role_with_no_document_section_never_reaches_eds_in_search(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["registry"] = page(registry_item("letter_in", "ВХ-104/26"))
    await web.login([custom(92, "Клиенты", {"dashboard.queue": "full", "crm.leads": "read"})])

    response = await web.client.get("/api/v1/search", params={"q": "ВХ-104"})

    assert response.json()["groups"] == []
    assert "eds" not in response.json()["sources"]
    assert fb.calls(fb.eds["registry"]) == 0


async def test_eds_refusal_in_search_finds_nothing_from_eds(web: Web, fb: FeedBackends) -> None:
    """Нет `registry.read` в EDS (403 по токену): документов EDS у сотрудника нет, поиск жив."""
    fb.state["registry"] = (403, {"code": "FORBIDDEN", "message": "x", "source": "eds"})
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "ВХ-104"})

    assert response.status_code == 200
    assert response.json()["sources"]["eds"] == "not_applicable"


async def test_eds_down_in_search_marks_the_source(web: Web, fb: FeedBackends) -> None:
    fb.eds_down = httpx.ConnectError("down")
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "ВХ-104"})

    assert response.status_code == 200
    assert response.json()["sources"]["eds"] == "unavailable"


async def test_two_versions_of_one_quote_give_one_hit_and_returned_opens_the_draft(
    web: Web, fb: FeedBackends
) -> None:
    """У каждой версии КП свой маршрут EDS и общий номер; реестр отдаёт новые первыми."""
    fb.state["registry"] = page(
        registry_item(
            "quote", "КП-2026/118", id="70000000-0000-4000-8000-0000000000b2", status="returned"
        ),
        registry_item(
            "quote", "КП-2026/118", id="70000000-0000-4000-8000-0000000000b1", status="rejected"
        ),
        registry_item("quote", "КП-2026/119", status="approved"),
    )
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "КП-2026"})

    hits = [h["object"] for g in response.json()["groups"] for h in g["items"]]
    assert [h["number"] for h in hits] == ["КП-2026/118", "КП-2026/119"]
    # возвращённое КП — в «Черновик» на «Одобрение»; одобренное (отправленное) — в «Исходящие»
    assert hits[0]["path"] == "/eds/drafts/%D0%9A%D0%9F-2026%2F118?panel=open&tab=approve"
    assert hits[1]["path"].startswith("/eds/outbox/")


async def test_memo_row_kind_follows_the_permission_of_the_current_step(
    web: Web, fb: FeedBackends
) -> None:
    """Директор с ролью бухгалтера на шаге бухгалтера: «Принять к оплате», а не «Согласовать»
    (сам директор «Счета и оплаты» только читает, D2-4)."""
    director_step = route("СЗ-2026/031")
    director_step["current_step"]["assignee"] = {"crm_user_id": None, "permission": "memos.approve"}
    pay_step = route("СЗ-2026/015", step="Бухгалтер")
    pay_step["current_step"]["assignee"] = {"crm_user_id": None, "permission": "payments.confirm"}
    named = route("СЗ-2026/016")
    named["current_step"]["assignee"] = {"crm_user_id": 7, "permission": None}
    fb.state["memos"] = page(director_step, pay_step, named)
    await web.login(["DIRECTOR", "ACCOUNTANT"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert {i["object"]["number"]: i["kind"] for i in items} == {
        "СЗ-2026/031": "approve_memo",
        "СЗ-2026/015": "pay_memo",
        "СЗ-2026/016": "approve_memo",  # шаг конкретного сотрудника — вид по разделу роли
    }
    pay = next(i for i in items if i["kind"] == "pay_memo")
    assert pay["title"].startswith("Принять к оплате СЗ-2026/015")


async def test_card_says_not_fewer_when_eds_has_another_page(web: Web, fb: FeedBackends) -> None:
    fb.state["letters"] = {"items": [letter_row()], "next_cursor": "c2"}
    fb.state["memos"] = page(route())
    await web.login(["DIRECTOR"])

    cards = {c["key"]: c for c in (await web.client.get("/api/v1/queue/cards")).json()["cards"]}

    assert cards["letters_without_resolution"]["hint"] == "Документы · Входящие письма · не меньше"
    assert cards["memos_to_approve"]["hint"] == "Документы · На согласовании"
