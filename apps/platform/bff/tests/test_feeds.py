"""Dashboard, уведомления и поиск: объединение источников CRM и ERP, недоступный бэкенд (`sources`),
роли «вида», вырезание полей с ограничением (PLT-14)."""

from typing import Any

import httpx
import pytest

from app.feeds.feed import RESTRICTED_KEYS
from app.rbac import strip_restricted
from tests.conftest import ContractChecker, Web
from tests.feeds_support import (
    FeedBackends,
    Moments,
    deal,
    escalation,
    lead,
    notification,
    quote,
)


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


# --- Моя очередь: MANAGER (CRM /inbox) ------------------------------------------------------------


async def test_manager_queue_comes_from_crm_inbox(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["inbox"] = {
        # передача бота: свободная, со сроком SLA сегодня
        "escalations": [
            lead(
                2041,
                "Демо Клиентов",
                summary="Просит КП на 40 стрелочных приводов",
                escalation=escalation(sla_due_at=m.ahead(hours=2), reason="Просит цену и договор"),
                last_msg=m.ago(minutes=20),
            ),
            # передача, которую взял другой менеджер, — не в очереди
            lead(2042, "Чужой Лид", escalation=escalation(taken_by=99)),
            # передача, отложенная на будущее, — не в очереди
            lead(2043, "Отложенный", escalation=escalation(snoozed_until=m.ahead(hours=5))),
        ],
        "mine": [
            lead(2050, "Ждёт ответа", unread=True, last_msg=m.ago(hours=3)),
            lead(2051, "Без новостей", unread=False),
            lead(2041, "Повтор той же передачи", unread=True),
        ],
        "unassigned": [
            lead(2060, "Свободный", summary="Нужны рельсовые скрепления", created=m.ago(hours=1))
        ],
    }
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok"}
    assert [(i["object"]["number"], i["kind"]) for i in body["items"]] == [
        ("L-2041", "take_lead"),
        ("L-2050", "answer_lead"),
        ("L-2060", "take_lead"),
    ]
    first = body["items"][0]
    assert first["role"] == "MANAGER"
    assert first["title"] == "Взять в работу лида L-2041"
    assert first["due_label"] == "today"
    assert "Демо Клиентов" in first["subtitle"]
    assert "Просит цену и договор" in first["subtitle"]
    assert first["object"]["path"] == "/crm/leads?lead=L-2041&panel=open&tab=card"
    assert body["items"][1]["title"] == "Ответить лиду L-2050"
    assert "3 ч назад" in body["items"][1]["subtitle"]
    assert fb.calls(fb.erp["approvals"]) == 0  # у менеджера ERP-очереди нет


async def test_my_escalation_is_answered_not_taken(web: Web, fb: FeedBackends) -> None:
    fb.state["inbox"]["escalations"] = [
        lead(2070, "Мой лид", escalation=escalation(taken_by=7, sla_due_at=fb.m.ago(minutes=5)))
    ]
    await web.login(["MANAGER"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert [(i["kind"], i["due_label"]) for i in items] == [("answer_lead", "overdue")]


async def test_queue_is_sorted_overdue_today_tomorrow_later(web: Web, fb: FeedBackends) -> None:
    m = fb.m
    fb.state["inbox"]["escalations"] = [
        lead(1, "Позже", escalation=escalation(sla_due_at=m.ahead(days=3))),
        lead(2, "Завтра", escalation=escalation(sla_due_at=m.ahead(hours=14))),
        lead(3, "Просрочено", escalation=escalation(sla_due_at=m.ago(hours=1))),
        lead(4, "Сегодня", escalation=escalation(sla_due_at=m.ahead(hours=1))),
    ]
    await web.login(["MANAGER"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert [(i["object"]["number"], i["due_label"]) for i in items] == [
        ("L-0003", "overdue"),
        ("L-0004", "today"),
        ("L-0002", "tomorrow"),
        ("L-0001", "later"),
    ]


# --- Моя очередь: DIRECTOR (ERP my-approval-queue) ------------------------------------------------


def director_data(fb: FeedBackends) -> None:
    fb.state["approvals"] = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [
            quote(11, 5, number="КП-2026/118", valid_until="2027-01-16"),
            quote(12, 6, number=None, version=3, total="900000.50"),
        ],
    }
    fb.state["deals"]["results"] = [
        deal(5, "QUOTE_SENT", title="Стрелочные приводы"),
        deal(6, "SOURCING", company="ООО «Демо-Рейл»"),
    ]


async def test_director_queue_comes_from_erp_approvals(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    director_data(fb)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    items = response.json()["items"]
    assert [i["title"] for i in items] == ["Одобрить КП-2026/118", "Одобрить КП v3"]
    first = items[0]
    assert first["role"] == "DIRECTOR"
    assert first["kind"] == "approve_quote"
    assert first["due_label"] == "tomorrow"  # КП действует до 16.01 — завтра по календарю компании
    assert first["subtitle"].startswith("Стрелочные приводы · 12 450 000 сум")
    assert first["object"] == {
        "kind": "quote",
        "number": "КП-2026/118",
        "title": "Стрелочные приводы",
        "path": "/eds/drafts/%D0%9A%D0%9F-2026%2F118?panel=open&tab=approve",
    }
    assert items[1]["subtitle"].startswith("ООО «Демо-Рейл» · 900 000,50 сум")
    assert items[1]["due_label"] == "later"
    assert fb.calls(fb.crm["inbox"]) == 0


async def test_cost_and_margin_never_reach_the_response(web: Web, fb: FeedBackends) -> None:
    director_data(fb)
    await web.login(["DIRECTOR"])

    text = (await web.client.get("/api/v1/queue")).text

    for secret in ("margin_percent", "economics", "gross_profit", "23.40", "charges"):
        assert secret not in text


def test_restricted_keys_are_stripped_for_roles_without_the_group() -> None:
    payload = {"id": 1, "margin_percent": "23.4", "items": [{"supplier_price": "5", "name": "x"}]}

    manager = strip_restricted(payload, ["MANAGER"], RESTRICTED_KEYS)
    director = strip_restricted(payload, ["DIRECTOR"], RESTRICTED_KEYS)
    accountant = strip_restricted(payload, ["ACCOUNTANT"], RESTRICTED_KEYS)

    assert manager == {"id": 1, "items": [{"name": "x"}]}
    assert director == payload  # директору видны и маржа, и цены поставщиков
    assert accountant == {"id": 1, "items": [{"supplier_price": "5", "name": "x"}]}


# --- Роли: активная роль, объединение, явный role -------------------------------------------------


async def test_queue_unites_roles_and_active_role_narrows_it(web: Web, fb: FeedBackends) -> None:
    director_data(fb)
    fb.state["inbox"]["unassigned"] = [lead(2060, "Свободный")]
    await web.login(["MANAGER", "DIRECTOR"])

    union = (await web.client.get("/api/v1/queue")).json()["items"]

    assert {i["role"] for i in union} == {"MANAGER", "DIRECTOR"}
    assert len(union) == 3

    await web.send("PATCH", "/api/v1/me", json={"active_role": "DIRECTOR"})
    only_director = (await web.client.get("/api/v1/queue")).json()["items"]
    assert {i["role"] for i in only_director} == {"DIRECTOR"}
    await web.send("PATCH", "/api/v1/me", json={"active_role": "MANAGER"})
    only_manager = (await web.client.get("/api/v1/queue")).json()["items"]
    assert [i["object"]["number"] for i in only_manager] == ["L-2060"]


async def test_explicit_role_parameter(web: Web, fb: FeedBackends, check: ContractChecker) -> None:
    director_data(fb)
    fb.state["inbox"]["unassigned"] = [lead(2060, "Свободный")]
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/queue", params={"role": "MANAGER"})
    check(response, "/queue", "get")
    assert {i["role"] for i in response.json()["items"]} == {"MANAGER"}

    foreign = await web.client.get("/api/v1/queue", params={"role": "ADMIN"})
    assert foreign.status_code == 403
    check(foreign, "/queue", "get")
    assert foreign.json()["details"]["reason"] == "role_not_assigned"


@pytest.mark.parametrize("role", ["SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN"])
async def test_other_roles_have_an_empty_queue(
    web: Web, fb: FeedBackends, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    assert response.json() == {"items": [], "sources": {"crm": "ok", "erp": "ok"}}
    assert fb.calls(fb.crm["inbox"]) == 0
    assert fb.calls(fb.erp["approvals"]) == 0


# --- Недоступный бэкенд и сотрудник без ERP -------------------------------------------------------


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("t"), 503])
async def test_erp_down_keeps_crm_part_and_marks_source(
    web: Web, fb: FeedBackends, check: ContractChecker, failure: Exception | int
) -> None:
    director_data(fb)
    fb.state["inbox"]["unassigned"] = [lead(2060, "Свободный")]
    fb.erp_down = failure
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "unavailable"}
    assert [i["object"]["number"] for i in body["items"]] == ["L-2060"]


async def test_crm_down_keeps_erp_part_and_marks_source(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    director_data(fb)
    fb.crm_down = httpx.ConnectError("down")
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "unavailable", "erp": "ok"}
    assert [i["role"] for i in body["items"]] == ["DIRECTOR", "DIRECTOR"]


async def test_both_backends_down_is_still_a_200(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.crm_down = fb.erp_down = 503
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    assert response.json() == {"items": [], "sources": {"crm": "unavailable", "erp": "unavailable"}}


async def test_employee_without_erp_access_gets_not_applicable(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    web.be.profile["platform_access"] = ["crm"]
    fb.state["inbox"]["unassigned"] = [lead(2060, "Свободный")]
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "not_applicable"}
    assert [i["object"]["number"] for i in body["items"]] == ["L-2060"]
    assert fb.calls(fb.erp["approvals"]) == 0


async def test_erp_unavailable_since_login_recovers_when_it_answers(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    director_data(fb)
    web.be.exchange_status = 503  # ERP не ответила при входе: сессия без токенов ERP
    await web.login(["DIRECTOR"])
    first = await web.client.get("/api/v1/queue")
    assert first.json()["sources"]["erp"] == "unavailable"

    web.be.exchange_status = 200
    web.clock.advance(120)  # пауза между переподключениями прошла
    second = await web.client.get("/api/v1/queue")

    check(second, "/queue", "get")
    assert second.json()["sources"]["erp"] == "ok"
    assert len(second.json()["items"]) == 2


async def test_dashboard_needs_a_session(web: Web) -> None:
    for path in ("/queue", "/queue/cards", "/menu-counters", "/activity/today", "/notifications"):
        response = await web.client.get(f"/api/v1{path}")
        assert response.status_code == 401, path
    assert (await web.client.get("/api/v1/search", params={"q": "ab"})).status_code == 401


# --- Карточки и счётчики меню ---------------------------------------------------------------------


async def test_cards_for_director(web: Web, fb: FeedBackends, check: ContractChecker) -> None:
    director_data(fb)
    fb.state["deals"]["results"] += [
        deal(7, "CLOSED_WON"),
        deal(8, "CLOSED_WON", complete=True),
        deal(9, "CONTRACT_SIGNED"),
    ]
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue/cards")

    check(response, "/queue/cards", "get")
    cards = {c["key"]: c for c in response.json()["cards"]}
    assert list(cards) == ["quotes_to_approve", "projects_in_work"]
    assert cards["quotes_to_approve"]["count"] == 2
    assert cards["quotes_to_approve"]["path"] == "/eds/drafts"
    assert cards["projects_in_work"]["count"] == 2  # исполнение закрыто целиком у одного
    assert cards["projects_in_work"]["hint"] == "EDS · Все проекты"


async def test_cards_for_manager_count_queue_kinds(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["inbox"]["mine"] = [lead(1, "А", unread=True), lead(2, "Б", unread=True)]
    fb.state["inbox"]["unassigned"] = [lead(3, "В")]
    fb.state["deals"]["results"] = [deal(5, "CLOSED_WON")]
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue/cards")

    check(response, "/queue/cards", "get")
    cards = {c["key"]: c["count"] for c in response.json()["cards"]}
    assert cards == {"leads_without_answer": 2, "leads_to_take": 1, "projects_in_work": 1}


async def test_cards_for_admin_are_empty_and_erp_down_is_flagged(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    admin = await web.client.get("/api/v1/queue/cards")
    check(admin, "/queue/cards", "get")
    assert admin.json()["cards"] == []

    fb.erp_down = 503
    await web.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": web.csrf})
    await web.login(["DIRECTOR"])
    director = await web.client.get("/api/v1/queue/cards")
    check(director, "/queue/cards", "get")
    assert director.json()["sources"]["erp"] == "unavailable"


async def test_menu_counters_follow_roles(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    director_data(fb)
    fb.state["inbox"]["unassigned"] = [lead(2060, "Свободный")]
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/menu-counters")

    check(response, "/menu-counters", "get")
    counters = {
        (c["module"], c["section"]): (c["count"], c["attention"]) for c in response.json()["items"]
    }
    assert counters[("dashboard", "queue")] == (3, True)
    assert counters[("crm", "messages")] == (1, True)
    assert counters[("eds", "drafts")] == (2, True)
    assert counters[("eds", "projects")][1] is False


async def test_menu_counters_for_supply_have_no_action_badges(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])

    response = await web.client.get("/api/v1/menu-counters")

    check(response, "/menu-counters", "get")
    assert [(c["module"], c["section"], c["attention"]) for c in response.json()["items"]] == [
        ("dashboard", "queue", False),
        ("dashboard", "projects", False),
        ("eds", "projects", False),
    ]


# --- Лента «Сегодня» ------------------------------------------------------------------------------


def log(entry_id: int, when: str, action: str, **extra: object) -> dict[str, Any]:
    return {
        "id": entry_id,
        "action": action,
        "detail": "",
        "event_code": "",
        "event_params": {},
        "user_name": "Демо Бухгалтерова",
        "level": "INFO",
        "timestamp": when,
        **extra,
    }


async def test_activity_from_the_platform_log_for_admins(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["activity_logs"] = {
        "results": [
            log(1, m.ago(minutes=10), "[MANUAL_MODE] Зафиксирован платёж"),
            log(2, m.ago(days=2), "Вчерашнее событие"),
            log(3, m.ago(hours=1), "Сделка создана", user_name=""),
        ]
    }
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/activity/today")

    check(response, "/activity/today", "get")
    items = response.json()["items"]
    assert [i["text"] for i in items] == ["Зафиксирован платёж", "Сделка создана"]
    assert items[0]["actor"] == {"id": "", "name": "Демо Бухгалтерова", "initials": "ДБ"}
    assert items[1]["actor"]["name"] == "Система"
    assert fb.calls(fb.erp["timeline"]) == 0


async def test_activity_falls_back_to_deal_timelines_when_log_is_closed(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    fb.state["timeline"] = [
        log(21, m.ago(minutes=30), "КП отправлено клиенту", deal_id=5, entity_type="quote"),
        log(22, m.ago(days=3), "Старое", deal_id=5, entity_type="deal"),
    ]
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/activity/today")

    check(response, "/activity/today", "get")
    items = response.json()["items"]
    assert [i["text"] for i in items] == ["КП отправлено клиенту · ЗВ-2027-005"]
    assert items[0]["module"] == "eds"
    assert items[0]["object"]["path"].startswith("/crm/requests?request=")
    assert fb.query(fb.erp["timeline"])["deal_id"] == "5"


async def test_activity_with_erp_down(web: Web, fb: FeedBackends, check: ContractChecker) -> None:
    fb.erp_down = httpx.ConnectError("down")
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/activity/today")

    check(response, "/activity/today", "get")
    assert response.json() == {"items": [], "sources": {"crm": "ok", "erp": "unavailable"}}


# --- Уведомления ----------------------------------------------------------------------------------


def erp_notifications(fb: FeedBackends) -> None:
    m = fb.m
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    fb.state["notifications"]["results"] = [
        notification(
            1,
            "quote.submitted_for_review",
            "КП на согласовании",
            deal_id=5,
            created=m.ago(minutes=5),
        ),
        notification(
            2, "quote.viewed", "Клиент открыл КП", deal_id=5, read=True, created=m.ago(hours=1)
        ),
        notification(
            3, "integration.pairing_code_issued", "Выдан код сопряжения", created=m.ago(days=1)
        ),
        notification(4, "payment.recorded", "Платёж записан", deal_id=5, created=m.ago(minutes=40)),
    ]


async def test_notifications_come_from_erp_with_tabs_and_objects(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    erp_notifications(fb)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200
    check(response, "/notifications", "get")
    page = response.json()
    assert page["unread_count"] == 3
    assert page["sources"] == {"crm": "ok", "erp": "ok"}
    assert "next_cursor" not in page or page["next_cursor"] is None
    assert [n["id"] for n in page["items"]] == ["erp:1", "erp:4", "erp:2", "erp:3"]  # новые сверху
    by_id = {n["id"]: n for n in page["items"]}
    assert by_id["erp:1"]["tab"] == "decisions"
    assert by_id["erp:4"]["tab"] == "clients"
    assert by_id["erp:3"]["tab"] == "system"
    assert by_id["erp:2"]["read"] is True
    assert by_id["erp:1"]["object"]["number"] == "ЗВ-2027-005"
    assert by_id["erp:1"]["object"]["path"].endswith("panel=open&tab=documents")
    assert by_id["erp:1"]["subtitle"] == "ЗВ-2027-005 · ООО «Демо-Депо»"
    assert "object" not in by_id["erp:3"]  # системное событие без сделки — без объекта


async def test_notifications_tab_filter_and_pagination(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    erp_notifications(fb)
    await web.login(["DIRECTOR"])

    clients = await web.client.get("/api/v1/notifications", params={"tab": "clients"})
    check(clients, "/notifications", "get")
    assert [n["id"] for n in clients.json()["items"]] == ["erp:4", "erp:2"]
    assert clients.json()["unread_count"] == 3  # счётчик не зависит от вкладки

    first = await web.client.get("/api/v1/notifications", params={"limit": 3})
    cursor = first.json()["next_cursor"]
    assert [n["id"] for n in first.json()["items"]] == ["erp:1", "erp:4", "erp:2"]
    assert cursor
    second = await web.client.get("/api/v1/notifications", params={"limit": 3, "cursor": cursor})
    check(second, "/notifications", "get")
    assert [n["id"] for n in second.json()["items"]] == ["erp:3"]
    assert second.json().get("next_cursor") is None
    bad = await web.client.get("/api/v1/notifications", params={"cursor": "###"})
    assert [n["id"] for n in bad.json()["items"]][:1] == ["erp:1"]  # битый курсор — с начала


async def test_notifications_with_erp_down_return_what_there_is(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.erp_down = httpx.ConnectError("down")
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200
    check(response, "/notifications", "get")
    assert response.json() == {
        "items": [],
        "unread_count": 0,
        "sources": {"crm": "ok", "erp": "unavailable"},
    }


async def test_mark_read_goes_to_erp(web: Web, fb: FeedBackends, check: ContractChecker) -> None:
    await web.login(["DIRECTOR"])

    response = await web.send("POST", "/api/v1/notifications/erp:17/read")

    assert response.status_code == 204
    check(response, "/notifications/{id}/read", "post")
    assert str(fb.mark_read.calls.last.request.url).endswith("/api/v1/notifications/17/mark_read/")
    erp_token = web.redis.read_session(web.sid)["erp"]["access"]
    assert fb.mark_read.calls.last.request.headers["authorization"] == f"Bearer {erp_token}"


async def test_mark_read_unknown_and_crm_ids(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    crm = await web.send("POST", "/api/v1/notifications/crm:5/read")
    assert crm.status_code == 404  # уведомлений CRM нет до CRM-04
    check(crm, "/notifications/{id}/read", "post")

    fb.mark_read_status = 404
    missing = await web.send("POST", "/api/v1/notifications/erp:999/read")
    assert missing.status_code == 404
    check(missing, "/notifications/{id}/read", "post")

    malformed = await web.send("POST", "/api/v1/notifications/abc/read")
    assert malformed.status_code == 422


async def test_mark_read_requires_csrf_and_reports_erp_failure(web: Web, fb: FeedBackends) -> None:
    await web.login(["DIRECTOR"])

    no_csrf = await web.send("POST", "/api/v1/notifications/erp:1/read", csrf="wrong")
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"

    fb.erp_down = 503
    down = await web.send("POST", "/api/v1/notifications/erp:1/read")
    assert down.status_code == 503
    assert down.json()["source"] == "erp"


async def test_mark_all_read(web: Web, fb: FeedBackends, check: ContractChecker) -> None:
    await web.login(["DIRECTOR"])

    response = await web.send("POST", "/api/v1/notifications/read-all")

    assert response.status_code == 204
    check(response, "/notifications/read-all", "post")
    assert fb.calls(fb.mark_all) == 1

    # без доступа к ERP отмечать нечего: CRM-ленты пока нет
    await web.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": web.csrf})
    web.be.profile["platform_access"] = ["crm"]
    await web.login(["MANAGER"])
    again = await web.send("POST", "/api/v1/notifications/read-all")
    assert again.status_code == 204
    assert fb.calls(fb.mark_all) == 1


# --- Поиск ----------------------------------------------------------------------------------------


def search_data(fb: FeedBackends) -> None:
    fb.state["leads"] = {
        "items": [lead(2041, "ООО «Демо-Депо»", summary="Просит КП на стрелочные приводы")],
        "total": 1,
    }
    fb.state["clients"] = [
        {
            "id": 17,
            "name": "ООО «Демо-Депо»",
            "inn": "300000001",
            "segment": None,
            "owner_user_id": None,
            "is_active": True,
            "notes": None,
            "created_at": "2027-01-01T00:00:00Z",
            "open_deals": 1,
            "last_activity_at": None,
        }
    ]
    fb.state["deals"]["results"] = [
        deal(104, "SOURCING", title="Стрелочные приводы", created="2027-01-08T00:00:00Z"),
        deal(99, "CLOSED_WON", title="Рельсовые скрепления", company="АО «Демо-Рейл»"),
    ]
    fb.state["documents"] = {
        "results": [
            {
                "type": "quote",
                "id": 1,
                "label": "КП-2026/118",
                "status_code": "SENT",
                "date": "x",
                "deal": 104,
            },
            {
                "type": "invoice",
                "id": 2,
                "label": "СЧ-2026/142",
                "status_code": "ISSUED",
                "date": "x",
                "deal": 99,
            },
            {
                "type": "contract",
                "id": 3,
                "label": "ДОГ-2026/091",
                "status_code": "SIGNED",
                "date": "x",
                "deal": 99,
            },
            {
                "type": "receipt",
                "id": 4,
                "label": "Квитанция",
                "status_code": "X",
                "date": "x",
                "deal": 99,
            },
        ]
    }


async def test_search_merges_crm_and_erp_into_module_groups(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    search_data(fb)
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "Демо"})

    assert response.status_code == 200
    check(response, "/search", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok"}
    groups = {g["module"]: g["items"] for g in body["groups"]}
    assert list(groups) == ["crm", "eds"]
    assert [h["object"]["kind"] for h in groups["crm"]] == ["lead", "client", "request"]
    assert groups["crm"][0]["object"]["number"] == "L-2041"
    assert groups["crm"][1]["subtitle"] == "ИНН 300000001"
    assert fb.query(fb.crm["leads"])["q"] == "Демо"
    # из документов нашлись КП, счёт и договор; «Квитанция» Платформа не открывает
    assert {h["object"]["number"] for h in groups["eds"] if h["object"]["kind"] != "project"} == {
        "КП-2026/118",
        "СЧ-2026/142",
        "ДОГ-2026/091",
    }
    assert len(groups["eds"]) == 3 + 1  # и проект ПР-… (сделка с совпавшей компанией)


async def test_search_finds_a_deal_by_its_number(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    search_data(fb)
    fb.state["documents"] = {"results": []}
    fb.state["leads"] = {"items": [], "total": 0}
    fb.state["clients"] = []
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/search", params={"q": "зв-2027-104"})

    check(response, "/search", "get")
    hit = response.json()["groups"][0]["items"][0]
    assert response.json()["groups"][0]["module"] == "crm"
    assert hit["object"]["kind"] == "request"
    assert hit["object"]["number"] == "ЗВ-2027-104"
    assert hit["object"]["path"].startswith("/crm/requests?request=")
    assert hit["title"] == "ЗВ-2027-104 · Стрелочные приводы"
    assert hit["subtitle"] == "ООО «Демо-Депо» · Расчёт"


async def test_search_by_lead_number_asks_crm_for_that_lead(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["lead"] = (200, lead(2041, "Демо Клиентов"))
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/search", params={"q": "L-2041"})

    check(response, "/search", "get")
    assert response.json()["groups"][0]["items"][0]["object"]["number"] == "L-2041"
    assert str(fb.lead.calls.last.request.url).endswith("/api/v1/leads/2041")


async def test_search_hides_what_the_role_cannot_see(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    search_data(fb)
    await web.login(["ACCOUNTANT"])

    response = await web.client.get("/api/v1/search", params={"q": "Демо"})

    check(response, "/search", "get")
    groups = {g["module"]: g["items"] for g in response.json()["groups"]}
    # бухгалтеру закрыты лиды (CRM) и черновики КП; клиенты и проекты, счета, договоры — открыты
    assert fb.calls(fb.crm["leads"]) == 0
    assert "lead" not in {h["object"]["kind"] for h in groups["crm"]}
    assert "quote" not in {h["object"]["kind"] for h in groups["eds"]}
    assert {"invoice", "contract"} <= {h["object"]["kind"] for h in groups["eds"]}

    await web.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": web.csrf})
    await web.login(["ADMIN"])
    admin = await web.client.get("/api/v1/search", params={"q": "Демо"})
    assert admin.json()["groups"] == []  # у администратора нет ни CRM, ни EDS в матрице


async def test_search_with_erp_down_returns_crm_part(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    search_data(fb)
    fb.erp_down = httpx.ConnectError("down")
    await web.login(["MANAGER", "DIRECTOR"])

    response = await web.client.get("/api/v1/search", params={"q": "Демо"})

    assert response.status_code == 200
    check(response, "/search", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "unavailable"}
    assert [g["module"] for g in body["groups"]] == ["crm"]


async def test_search_validates_the_query(web: Web, check: ContractChecker) -> None:
    await web.login(["MANAGER"])

    short = await web.client.get("/api/v1/search", params={"q": "a"})
    assert short.status_code == 422
    check(short, "/search", "get")
    assert (await web.client.get("/api/v1/search")).status_code == 422
    assert (await web.client.get("/api/v1/search", params={"q": "x" * 101})).status_code == 422
