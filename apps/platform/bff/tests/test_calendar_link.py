"""Личный календарь по секретной ссылке: выдача, лента без сессии, смена, отключение.

Лента — проекция «Моей очереди» (`GET /queue`): те же строки со сроком, без сумм и подписей.
CRM — на respx (хеш токена живёт в CRM), очередь — те же ответы, что в test_queue_erp_work.
"""

import hashlib
import json
from typing import Any

import httpx
import pytest
from icalendar import Calendar

from tests.bus_support import CRM_SECRET, SECRET, delivery, envelope
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.feeds_support import FeedBackends, Moments
from tests.test_queue_erp_work import morning, queue_of

ORIGIN = "https://platform.example.org"
LINK = f"{CRM_URL}/api/v1/me/calendar-link"


@pytest.fixture(autouse=True)
def pair_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_ERP_PLATFORM_BFF", SECRET)
    monkeypatch.setenv("RT_BUS_SECRET_CRM_PLATFORM_BFF", CRM_SECRET)


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


@pytest.fixture
def crm_tokens(web: Web) -> list[str]:
    """CRM выдаёт новый токен на каждый вызов; список — выданные по порядку."""
    issued: list[str] = []

    def issue(_: httpx.Request) -> httpx.Response:
        token = f"tok-{len(issued) + 1}-".ljust(43, "x")
        issued.append(token)
        return httpx.Response(200, json={"token": token, "issued_at": "2027-01-10T08:00:00Z"})

    web.be.router.post(LINK).mock(side_effect=issue)
    return issued


async def issue(web: Web) -> dict[str, Any]:
    response = await web.client.post(
        "/api/v1/me/calendar-link",
        headers={"x-csrf-token": web.csrf, "origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def feed(web: Web, path: str) -> httpx.Response:
    """Календарный клиент: без cookie и без сессии."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web.app, raise_app_exceptions=False),
        base_url="https://bff.test",
    ) as anonymous:
        return await anonymous.get(path)


def events(response: httpx.Response) -> list[Any]:
    return list(Calendar.from_ical(response.content).walk("VEVENT"))


async def test_feed_has_the_same_dated_items_as_the_queue_and_no_money(
    web: Web, fb: FeedBackends, crm_tokens: list[str], check: ContractChecker
) -> None:
    morning(fb)
    await web.login(["MANAGER_ALL"])
    link = check(
        await web.client.get("/api/v1/me/calendar-link"), "/me/calendar-link", "get"
    ).json()
    assert link == {"active": False, "issued_at": None}

    issued = await issue(web)
    assert issued["url"] == f"{ORIGIN}{issued['path']}"
    assert (await web.client.get("/api/v1/me/calendar-link")).json()["active"] is True
    queue = await queue_of(web)  # разбор очереди обновляет снимок

    response = await feed(web, issued["path"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "max-age=300" in response.headers["cache-control"]
    calendar = Calendar.from_ical(response.content)
    assert str(calendar["X-WR-CALNAME"]) == "RailTech — сроки"
    dated = [i for i in queue if i.get("due_at")]
    assert dated, "в очереди должна быть строка со сроком"
    shown = events(response)
    assert sorted(str(e["SUMMARY"]) for e in shown) == sorted(i["title"] for i in dated)
    for item in dated:
        event = next(e for e in shown if str(e["SUMMARY"]) == item["title"])
        assert str(event["URL"]) == f"{ORIGIN}{item['object']['path']}"
        assert event["DTSTART"].dt.isoformat() == item["due_at"][:10]
    # ни подписей строк (клиент, сумма), ни сумм счёта
    text = response.text
    for forbidden in (
        "28000000",
        "28 000 000",
        "Демо-Депо",
        "Север-Путь",
        *(i["subtitle"] for i in queue if i["subtitle"]),
    ):
        assert forbidden not in text


async def test_token_is_stored_only_as_a_hash(
    web: Web, fb: FeedBackends, crm_tokens: list[str]
) -> None:
    await web.login(["MANAGER_ALL"])
    issued = await issue(web)

    token = crm_tokens[0]
    assert issued["path"] == f"/api/v1/calendar/{token}.ics"
    stored = json.dumps(web.redis.values, ensure_ascii=False)
    assert token not in stored
    assert hashlib.sha256(token.encode()).hexdigest() in stored


async def test_new_link_replaces_the_old_one(
    web: Web, fb: FeedBackends, crm_tokens: list[str]
) -> None:
    morning(fb)
    await web.login(["MANAGER_ALL"])
    first = await issue(web)
    await queue_of(web)
    assert (await feed(web, first["path"])).status_code == 200

    second = await issue(web)

    assert second["path"] != first["path"]
    assert (await feed(web, first["path"])).status_code == 404
    again = await feed(web, second["path"])
    assert again.status_code == 200
    assert events(again)  # снимок сотрудника остался: новая ссылка не пустая


async def test_unknown_tokens_are_404_and_repeated_misses_are_limited(web: Web) -> None:
    response = await feed(web, "/api/v1/calendar/" + "z" * 43 + ".ics")
    assert response.status_code == 404
    assert (await feed(web, "/api/v1/calendar/short.ics")).status_code == 404
    assert (await feed(web, "/api/v1/calendar/" + "z" * 43)).status_code == 404  # без .ics

    last = response
    for _ in range(70):
        last = await feed(web, "/api/v1/calendar/" + "y" * 43 + ".ics")
    assert last.status_code == 429


async def test_deactivated_employee_loses_the_link(
    web: Web, fb: FeedBackends, crm_tokens: list[str]
) -> None:
    morning(fb)
    await web.login(["MANAGER_ALL"])  # id сотрудника — 7, как в примере события шины
    issued = await issue(web)
    await queue_of(web)
    assert (await feed(web, issued["path"])).status_code == 200

    headers, raw = delivery(
        envelope("identity", "user.deactivated"), publisher="crm", secret=CRM_SECRET
    )
    done = await web.client.post("/bus/v1/events", content=raw, headers=headers)
    assert done.status_code == 200, done.text

    assert (await feed(web, issued["path"])).status_code == 404
    assert (await web.client.get("/api/v1/me/calendar-link")).json()["active"] is False
    assert not [k for k in web.redis.values if k.startswith("cal:")]


async def test_queue_without_a_link_writes_nothing_and_a_partial_queue_keeps_the_snapshot(
    web: Web, fb: FeedBackends, crm_tokens: list[str]
) -> None:
    morning(fb)
    await web.login(["MANAGER_ALL"])
    await queue_of(web)
    assert not [k for k in web.redis.values if k.startswith("cal:")]

    issued = await issue(web)
    await queue_of(web)
    before = len(events(await feed(web, issued["path"])))
    assert before

    fb.erp_down = httpx.ConnectError("erp down")
    web.clock.advance(60)  # снимок источников живёт 8 с
    await queue_of(web)  # ERP не ответил: срок не должен пропасть из календаря

    assert len(events(await feed(web, issued["path"]))) == before
