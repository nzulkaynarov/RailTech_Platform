"""Лента CRM в колокольчике и флаг первого входа (W15-H7, контракт 0.24.0)."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.feeds_support import FeedBackends, Moments, deal, notification
from tests.roles import custom


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def crm_note(
    note_id: int, kind: str, created: str, *, read: bool = False, **over: Any
) -> dict[str, Any]:
    return {
        "id": note_id,
        "kind": kind,
        "tab": "system",
        "title": "Ответ на обращение ОБР-0012",
        "subtitle": "Доступ выдан",
        "object_kind": "ticket",
        "object_id": "12",
        "object_number": "ОБР-0012",
        "created_at": created,
        "read": read,
        **over,
    }


async def test_crm_ticket_notifications_are_merged_with_erp_by_time(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    fb.state["notifications"]["results"] = [
        notification(1, "quote.viewed", "Клиент открыл КП", deal_id=5, created=m.ago(hours=2)),
    ]
    fb.state["crm_notifications"] = {
        "items": [
            crm_note(8, "ticket_reply", m.ago(minutes=3)),
            crm_note(
                7,
                "ticket_new",
                m.ago(hours=1),
                title="Новое обращение ОБР-0013",
                object_id="13",
                object_number="ОБР-0013",
            ),
            crm_note(
                6,
                "telegram_linked",
                m.ago(hours=3),
                read=True,
                title="К вашему профилю привязан Telegram @ivan",
                subtitle="Если это не вы — отвяжите его в профиле.",
                object_kind=None,
                object_id=None,
                object_number=None,
            ),
        ],
        "unread_count": 2,
    }
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200, response.text
    check(response, "/notifications", "get")
    page = response.json()
    assert [n["id"] for n in page["items"]] == ["crm:8", "crm:7", "erp:1", "crm:6"]
    assert page["unread_count"] == 3  # 1 непрочитанное ERP + 2 в CRM
    by_id = {n["id"]: n for n in page["items"]}
    assert by_id["crm:8"]["object"] == {
        "kind": "ticket",
        "number": "ОБР-0012",
        "path": "/help/requests/%D0%9E%D0%91%D0%A0-0012",
    }
    # Админу о новом обращении — в «Настройки · Обращения сотрудников», с карточкой в боковом окне.
    assert by_id["crm:7"]["object"]["path"] == (
        "/admin/tickets/%D0%9E%D0%91%D0%A0-0013?panel=open&tab=card"
    )
    assert "object" not in by_id["crm:6"]
    assert by_id["crm:6"]["read"] is True


async def test_employee_without_crm_sections_still_gets_crm_notifications(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["crm_notifications"] = {
        "items": [crm_note(8, "ticket_reply", fb.m.ago(minutes=3))],
        "unread_count": 1,
    }
    # Только «Счета и оплаты»: ни одного раздела, который даёт права в CRM.
    await web.login([custom(31, "Кассир", {"dashboard.queue": "read", "eds.payments": "full"})])

    response = await web.client.get("/api/v1/notifications")

    assert response.status_code == 200
    check(response, "/notifications", "get")
    assert [n["id"] for n in response.json()["items"]] == ["crm:8"]
    assert response.json()["sources"]["crm"] == "not_applicable"  # источник агрегатов — прежний


async def test_crm_down_leaves_the_erp_part_and_marks_the_source(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["deals"]["results"] = [deal(5, "QUOTE_SENT", title="Стрелочные приводы")]
    fb.state["notifications"]["results"] = [
        notification(1, "quote.viewed", "Клиент открыл КП", deal_id=5, created=m.ago(hours=2)),
    ]
    fb.crm_down = httpx.ConnectError("down")
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/notifications")

    check(response, "/notifications", "get")
    assert [n["id"] for n in response.json()["items"]] == ["erp:1"]
    assert response.json()["sources"] == {"crm": "unavailable", "erp": "ok"}


async def test_mark_read_goes_to_crm_for_crm_ids(web: Web, fb: FeedBackends) -> None:
    await web.login(["DIRECTOR"])

    response = await web.send("POST", "/api/v1/notifications/crm:8/read")

    assert response.status_code == 204
    request = fb.crm_read.calls.last.request
    assert request.method == "POST"
    assert str(request.url) == f"{CRM_URL}/api/v1/me/notifications/8/read"


async def test_read_all_marks_both_feeds(web: Web, fb: FeedBackends) -> None:
    await web.login(["DIRECTOR"])

    response = await web.send("POST", "/api/v1/notifications/read-all")

    assert response.status_code == 204
    assert len(fb.mark_all.calls) == 1
    assert str(fb.crm_read.calls.last.request.url) == f"{CRM_URL}/api/v1/me/notifications/read-all"


async def test_read_all_survives_one_source_down_and_fails_only_when_all_fail(
    web: Web, fb: FeedBackends
) -> None:
    await web.login(["DIRECTOR"])
    fb.crm_read_status = 502

    partial = await web.send("POST", "/api/v1/notifications/read-all")

    assert partial.status_code == 204, partial.text  # ERP отмечена, CRM недоступна
    assert len(fb.mark_all.calls) == 1

    fb.crm_read_status, fb.mark_all_status = 204, 502
    other_way = await web.send("POST", "/api/v1/notifications/read-all")
    assert other_way.status_code == 204, other_way.text  # CRM отмечена, ERP недоступна
    fb.crm_read_status = 502

    fb.mark_all_status = 502  # теперь и ERP недоступна
    both = await web.send("POST", "/api/v1/notifications/read-all")

    assert both.status_code >= 500


async def test_onboarding_flag_comes_from_crm_and_is_closed_through_it(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.profile["onboarding_done"] = False
    patches: list[dict[str, Any]] = []

    def patch_me(request: httpx.Request) -> httpx.Response:
        import json

        patches.append(json.loads(request.content))
        be.profile["onboarding_done"] = True
        return httpx.Response(200, json=be.profile)

    be.crm_patch_me.mock(side_effect=patch_me)
    login = await web.login(["MANAGER"])
    assert login.json()["me"]["onboarding_done"] is False

    me = await web.client.get("/api/v1/me")
    assert me.json()["onboarding_done"] is False

    done = await web.send("PUT", "/api/v1/me/onboarding")

    assert done.status_code == 200, done.text
    check(done, "/me/onboarding", "put")
    assert done.json()["onboarding_done"] is True
    assert patches == [{"onboarding_done": True}]
    assert (await web.client.get("/api/v1/me")).json()["onboarding_done"] is True


async def test_sessions_without_the_flag_do_not_see_the_welcome(web: Web) -> None:
    login = await web.login(["MANAGER"])  # профиль CRM без поля — карточку не показываем

    assert login.json()["me"]["onboarding_done"] is True


async def test_admin_queue_and_menu_counter_show_new_staff_tickets(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["crm_tickets"] = {
        "items": [
            {
                "id": 12,
                "number": "ОБР-0012",
                "subject": "access",
                "status": "new",
                "author_id": 7,
                "author_name": "Дильшод Т.",
                "preview": "Нужен доступ к «Расчёту»",
                "created_at": fb.m.ago(minutes=20),
                "updated_at": fb.m.ago(minutes=20),
            }
        ],
        "total": 3,
        "counts": {"new": 3, "in_progress": 0, "resolved": 0},
    }
    await web.login(["ADMIN"])

    queue = await web.client.get("/api/v1/queue")
    counters = await web.client.get("/api/v1/menu-counters")

    check(queue, "/queue", "get")
    check(counters, "/menu-counters", "get")
    [item] = [i for i in queue.json()["items"] if i["kind"] == "ticket"]
    assert item["title"] == "Ответить на обращение ОБР-0012"
    assert item["subtitle"].startswith("Дильшод Т. · доступ · Нужен доступ")
    assert item["object"] == {
        "kind": "ticket",
        "number": "ОБР-0012",
        "path": "/admin/tickets/%D0%9E%D0%91%D0%A0-0012?panel=open&tab=card",
    }
    assert {
        "module": "admin",
        "section": "tickets",
        "count": 3,
        "attention": True,
    } in counters.json()["items"]


async def test_manager_does_not_see_staff_tickets_in_the_queue(web: Web, fb: FeedBackends) -> None:
    fb.state["crm_tickets"] = {"items": [{"number": "ОБР-0001"}], "total": 1, "counts": {}}
    await web.login(["MANAGER"])

    queue = await web.client.get("/api/v1/queue")

    assert [i for i in queue.json()["items"] if i["kind"] == "ticket"] == []
    assert not any(
        c["section"] == "tickets"
        for c in (await web.client.get("/api/v1/menu-counters")).json()["items"]
    )
