"""Замещение в «Моей очереди» (W15-H6): заместитель видит очередь замещаемого строками «за {имя}».

Права заместителя BFF не расширяет: очередь замещаемого отдаёт CRM (только назначенному в период),
BFF добавляет её строки к своей и ничего не вычисляет.
"""

import pytest

from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, escalation, lead


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def covering(user_id: int = 12, name: str = "Мадина Р.") -> dict[str, object]:
    return {
        "user_id": user_id,
        "full_name": name,
        "date_from": "2026-10-20",
        "date_to": "2026-11-02",
    }


async def test_deputy_sees_the_absent_colleague_queue_marked(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    m = fb.m
    fb.state["inbox"] = {
        "escalations": [],
        "mine": [lead(2050, "Мой клиент", unread=True, last_msg=m.ago(hours=1))],
        "unassigned": [],
    }
    fb.state["covering"] = [covering()]
    fb.state["covered_inbox"] = {
        12: {
            "escalations": [
                lead(
                    2071,
                    "Взят Мадиной",
                    escalation=escalation(taken_by=12, sla_due_at=m.ahead(hours=1)),
                    last_msg=m.ago(minutes=10),
                ),
                # передача, которую взял кто-то другой, и свободная передача — не её очередь
                lead(2072, "Чужая", escalation=escalation(taken_by=99)),
                lead(2073, "Свободная", escalation=escalation()),
            ],
            "mine": [
                lead(2060, "Ждёт Мадину", unread=True, last_msg=m.ago(hours=3)),
                lead(2061, "Без новостей", unread=False),
                lead(2050, "Пересечение с моими", unread=True),
            ],
            "unassigned": [lead(2099, "Свободный лид")],
        }
    }
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    items = response.json()["items"]
    mine = [i for i in items if "on_behalf_of" not in i]
    behalf = [i for i in items if "on_behalf_of" in i]
    assert [i["object"]["number"] for i in mine] == ["L-2050"]
    assert sorted(i["object"]["number"] for i in behalf) == ["L-2060", "L-2071"]
    assert all(i["on_behalf_of"] == {"id": "12", "name": "Мадина Р."} for i in behalf)
    assert all(i["kind"] == "answer_lead" for i in behalf)
    assert len({i["id"] for i in items}) == len(items)  # ключи строк не пересекаются
    # В CRM ушёл именно запрос за коллегу, под токеном заместителя.
    assert fb.crm["inbox"].calls.last.request.url.params["on_behalf_of"] == "12"


async def test_no_covering_means_no_extra_calls(web: Web, fb: FeedBackends) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get("/api/v1/queue")).status_code == 200
    params = [dict(c.request.url.params) for c in fb.crm["inbox"].calls]
    assert params == [{}]


async def test_refused_covering_queue_is_skipped_not_fatal(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["covering"] = [covering()]
    fb.state["covered_inbox"] = {12: (403, {"code": "forbidden", "message": "x", "details": {}})}
    fb.state["inbox"] = {
        "escalations": [],
        "mine": [lead(2050, "Мой", unread=True)],
        "unassigned": [],
    }
    await web.login(["MANAGER"])
    response = await web.client.get("/api/v1/queue")
    assert response.status_code == 200
    check(response, "/queue", "get")
    assert [i["object"]["number"] for i in response.json()["items"]] == ["L-2050"]


async def test_cards_and_crm_badge_count_only_own_work(web: Web, fb: FeedBackends) -> None:
    fb.state["inbox"] = {
        "escalations": [],
        "mine": [lead(2050, "Мой", unread=True)],
        "unassigned": [],
    }
    fb.state["covering"] = [covering()]
    fb.state["covered_inbox"] = {
        12: {
            "escalations": [],
            "mine": [lead(2060, "Чужой", unread=True), lead(2061, "Ещё чужой", unread=True)],
            "unassigned": [],
        }
    }
    await web.login(["MANAGER"])

    queue = (await web.client.get("/api/v1/queue")).json()["items"]
    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]
    counters = (await web.client.get("/api/v1/menu-counters")).json()["items"]

    assert len(queue) == 3
    assert {c["key"]: c["count"] for c in cards}["leads_without_answer"] == 1
    crm_badge = next(c for c in counters if c["module"] == "crm" and c["section"] == "messages")
    assert crm_badge["count"] == 1
    queue_badge = next(
        c for c in counters if c["module"] == "dashboard" and c["section"] == "queue"
    )
    assert queue_badge["count"] == 3


async def test_covering_is_limited_to_a_few_colleagues(web: Web, fb: FeedBackends) -> None:
    fb.state["covering"] = [covering(user_id=20 + n, name=f"Коллега {n}") for n in range(9)]
    fb.state["covered_inbox"] = {
        20 + n: {"escalations": [], "mine": [lead(3000 + n, "Лид", unread=True)], "unassigned": []}
        for n in range(9)
    }
    await web.login(["MANAGER"])
    items = (await web.client.get("/api/v1/queue")).json()["items"]
    assert len(items) == 5
