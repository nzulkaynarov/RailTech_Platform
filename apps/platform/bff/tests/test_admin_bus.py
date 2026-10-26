"""Admin · Журнал интеграций (W13-A2, контракт BFF 0.9.0): шина CRM, ERP и EDS в одном журнале.

Домены — на respx (`bus_journal_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что делает
BFF: раздел `admin: full` (директору и роли без раздела — 403 до доменов), токен сотрудника в
каждом домене (в EDS —
обмен SSO-токена CRM `aud=eds`), частичный ответ `sources`, состояние подписчика словом, слияние
страниц трёх доменов
и составной курсор, прокси повторов. Решения (что повторять, права) — за доменами.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.bus_journal_support import (
    BusDomainsFake,
    delivery,
    inbox_entry,
    overview,
    page,
    subscriber,
)
from tests.conftest import ContractChecker, Web
from tests.roles import Role

BASE = "/api/v1/admin/bus"
EVENT = "10000000-0000-4000-8000-000000000001"


@pytest.fixture
def domains(be: Backends) -> BusDomainsFake:
    return BusDomainsFake(be)


async def _admin(web: Web) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200


async def test_overview_aggregates_three_domains_with_state_words(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    domains.answer(
        "crm",
        "GET",
        "overview",
        overview(
            "crm",
            [
                subscriber("eds"),
                subscriber("erp", dead=3, consecutive_failures=0),
                subscriber("platform-bff", consecutive_failures=2, last_error="HTTP 503: x"),
            ],
            inbox_failed=1,
        ),
    )
    domains.answer(
        "erp",
        "GET",
        "overview",
        overview(
            "erp",
            [
                subscriber(
                    "crm", paused_until="2026-10-26T09:05:00Z", consecutive_failures=5, dead=1
                ),
                subscriber("eds", enabled=False, pending=12),
                subscriber("legacy", configured=False, endpoint=None, dead=2),
            ],
        ),
    )
    await _admin(web)
    response = check(await web.client.get(BASE), "/admin/bus", "get")
    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "ok"}
    assert [d["domain"] for d in body["domains"]] == ["crm", "erp", "eds"]
    states = {
        (d["domain"], s["name"]): s["state"] for d in body["domains"] for s in d["subscribers"]
    }
    assert states == {
        ("crm", "eds"): "ok",
        ("crm", "erp"): "dead_letters",
        ("crm", "platform-bff"): "failing",
        ("erp", "crm"): "paused",  # пауза важнее DLQ
        ("erp", "eds"): "disabled",
        ("erp", "legacy"): "removed",
        ("eds", "platform-bff"): "ok",
    }
    crm = body["domains"][0]
    assert (crm["dlq_size"], crm["inbox_failed"]) == (3, 1)
    # EDS — токен доступа EDS, полученный обменом SSO-токена CRM `aud=eds`; CRM и ERP — токены
    # сессии
    [eds_call] = domains.made("eds", "GET", "overview")
    assert eds_call.headers["authorization"] == "Bearer eds-access-1"
    assert json.loads(domains.exchange.calls.last.request.content) == {"token": "sso-eds-2"}
    assert domains.sso_auds == ["erp", "eds"]  # вход: ERP; журнал: EDS


async def test_eds_token_lives_in_the_session_and_is_renewed_after_15_minutes(
    web: Web, domains: BusDomainsFake
) -> None:
    await _admin(web)
    for _ in range(3):
        assert (await web.client.get(BASE)).status_code == 200
    assert domains.eds_issued == ["eds-access-1"]
    web.clock.advance(15 * 60)
    assert (await web.client.get(BASE)).status_code == 200
    assert domains.eds_issued == ["eds-access-1", "eds-access-2"]
    eds_calls = domains.made("eds", "GET", "overview")
    assert eds_calls[-1].headers["authorization"] == "Bearer eds-access-2"


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (
            lambda d: d.answer("erp", "GET", "overview", {"detail": "x"}, 503),
            {"erp": "unavailable"},
        ),
        (
            lambda d: d.answer("crm", "GET", "overview", {"code": "forbidden"}, 403),
            {"crm": "forbidden"},
        ),
        (lambda d: setattr(d, "eds_exchange_status", 500), {"eds": "unavailable"}),
        (lambda d: setattr(d, "eds_sso_status", 403), {"eds": "not_applicable"}),
        (lambda d: setattr(d, "eds_exchange_status", 403), {"eds": "not_applicable"}),
        (
            lambda d: d.answer("eds", "GET", "overview", {"code": "FORBIDDEN"}, 403),
            {"eds": "forbidden"},
        ),
        (
            lambda d: d.answer("eds", "GET", "overview", {"unexpected": True}),
            {"eds": "unavailable"},
        ),
    ],
    ids=[
        "erp-503",
        "crm-403",
        "eds-exchange-500",
        "eds-not-granted",
        "eds-not-provisioned",
        "eds-403",
        "eds-bad",
    ],
)
async def test_partial_answer_when_a_domain_fails(
    web: Web, domains: BusDomainsFake, check: ContractChecker, setup: Any, expected: dict[str, str]
) -> None:
    setup(domains)
    await _admin(web)
    response = check(await web.client.get(BASE), "/admin/bus", "get")
    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "ok", **expected}
    failed = set(expected)
    assert {d["domain"] for d in body["domains"]} == {"crm", "erp", "eds"} - failed


async def test_eds_failure_pauses_reconnect_and_keeps_the_session(
    web: Web, domains: BusDomainsFake
) -> None:
    domains.eds_exchange_status = 500
    await _admin(web)
    assert (await web.client.get(BASE)).json()["sources"]["eds"] == "unavailable"
    assert (await web.client.get(BASE)).json()["sources"]["eds"] == "unavailable"
    assert domains.exchange.call_count == 1  # пауза перед повторным входом в EDS
    domains.eds_exchange_status = 200
    web.clock.advance(20)
    assert (await web.client.get(BASE)).json()["sources"]["eds"] == "ok"
    assert (await web.client.get("/api/v1/me")).status_code == 200


async def test_employee_without_erp_access_sees_erp_as_not_applicable(
    web: Web, be: Backends, domains: BusDomainsFake
) -> None:
    be.profile["platform_access"] = ["crm"]
    await _admin(web)
    body = (await web.client.get(BASE)).json()
    assert body["sources"]["erp"] == "not_applicable"
    assert domains.made("erp", "GET", "overview") == []
    retry = await web.send("POST", f"{BASE}/erp/deliveries/5/retry")
    assert retry.status_code == 403
    assert retry.json()["details"]["reason"] == "erp_not_granted"


@pytest.mark.parametrize("roles", [["DIRECTOR"], ["MANAGER"], ["ACCOUNTANT"]])
async def test_without_admin_full_every_endpoint_is_403_before_the_domains(
    web: Web, domains: BusDomainsFake, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200
    for url in (BASE, f"{BASE}/deliveries", f"{BASE}/inbox"):
        response = await web.client.get(url)
        assert response.status_code == 403, url
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    for url, body in (
        (f"{BASE}/crm/deliveries/5/retry", None),
        (f"{BASE}/erp/deliveries/retry-dead", {"subscriber": "crm"}),
        (f"{BASE}/eds/inbox/{EVENT}/retry", None),
    ):
        assert (await web.send("POST", url, json=body)).status_code == 403, url
    assert domains.calls == []
    assert domains.exchange.call_count == 0


async def test_deliveries_merge_three_domains_by_time_and_page_with_one_cursor(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    def by_cursor(rows: list[dict[str, Any]]) -> Any:
        def answer(request: httpx.Request) -> httpx.Response:
            before = request.url.params.get("before_id")
            limit = int(request.url.params["limit"])
            tail = [r for r in rows if before is None or r["id"] < int(before)]
            return httpx.Response(200, json=page(tail[:limit], has_more=len(tail) > limit))

        return answer

    domains.answer_with(
        "crm",
        "GET",
        "deliveries",
        by_cursor([delivery(30, 50), delivery(20, 30), delivery(10, 10)]),
    )
    domains.answer_with("erp", "GET", "deliveries", by_cursor([delivery(9, 40), delivery(8, 20)]))
    domains.answer_with("eds", "GET", "deliveries", by_cursor([delivery(77, 55)]))
    await _admin(web)

    first = check(
        await web.client.get(f"{BASE}/deliveries", params={"limit": 3}),
        "/admin/bus/deliveries",
        "get",
    ).json()
    assert [(i["domain"], i["id"]) for i in first["items"]] == [
        ("eds", 77),
        ("crm", 30),
        ("erp", 9),
    ]
    assert first["next_cursor"]
    assert "envelope" not in first["items"][0]

    second = (
        await web.client.get(
            f"{BASE}/deliveries", params={"limit": 3, "cursor": first["next_cursor"]}
        )
    ).json()
    assert [(i["domain"], i["id"]) for i in second["items"]] == [
        ("crm", 20),
        ("erp", 8),
        ("crm", 10),
    ]
    assert second["next_cursor"] is None
    # EDS отдал всё на первой странице — на второй его не спрашивают; CRM и ERP — со своей позиции
    assert len(domains.made("eds", "GET", "deliveries")) == 1
    assert domains.made("crm", "GET", "deliveries")[-1].url.params["before_id"] == "30"
    assert domains.made("erp", "GET", "deliveries")[-1].url.params["before_id"] == "9"


async def test_delivery_filters_go_to_the_domains_and_domain_filter_narrows_the_scope(
    web: Web, domains: BusDomainsFake
) -> None:
    await _admin(web)
    params: dict[str, str | int] = {
        "domain": "erp",
        "status": "dead",
        "subscriber": "crm",
        "type": "quote.",
        "from": "2026-10-26T00:00:00Z",
        "to": "2026-10-27T00:00:00Z",
        "limit": 20,
    }
    body = (await web.client.get(f"{BASE}/deliveries", params=params)).json()
    assert body["sources"] == {"crm": "not_applicable", "erp": "ok", "eds": "not_applicable"}
    [call] = domains.made("erp", "GET", "deliveries")
    sent = dict(call.url.params)
    assert sent == {
        "status": "dead",
        "subscriber": "crm",
        "type": "quote.",
        "created_from": "2026-10-26T00:00:00+00:00",
        "created_to": "2026-10-27T00:00:00+00:00",
        "limit": "20",
    }
    assert domains.made("crm", "GET", "deliveries") == []
    assert domains.exchange.call_count == 0  # EDS вне фильтра — вход в EDS не нужен


async def test_inbox_with_errors_merges_by_received_time_and_keeps_ties_with_event_cursor(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    rows = [inbox_entry(3, 30), inbox_entry(1, 20), inbox_entry(2, 20)]

    def crm_inbox(request: httpx.Request) -> httpx.Response:
        assert request.url.params["errors"] == "true"
        before = request.url.params.get("before")
        if before is None:
            return httpx.Response(200, json=page(rows[:2], has_more=True))
        assert (before, request.url.params["before_event_id"]) == (
            "2026-10-26T09:20:00+00:00",
            rows[1]["event_id"],
        )
        return httpx.Response(200, json=page(rows[2:]))

    domains.answer_with("crm", "GET", "inbox", crm_inbox)
    domains.answer(
        "erp",
        "GET",
        "inbox",
        page([inbox_entry(9, 25, publisher="eds", type="uz.railtech.eds.letter.resolved.v1")]),
    )
    await _admin(web)
    first = check(
        await web.client.get(f"{BASE}/inbox", params={"errors": "true", "limit": 3}),
        "/admin/bus/inbox",
        "get",
    ).json()
    assert [(i["domain"], i["event_id"][-2:]) for i in first["items"]] == [
        ("crm", "03"),
        ("erp", "09"),
        ("crm", "01"),
    ]
    assert all(i["status"] == "failed" for i in first["items"])
    second = (
        await web.client.get(
            f"{BASE}/inbox", params={"errors": "true", "limit": 3, "cursor": first["next_cursor"]}
        )
    ).json()
    assert [(i["domain"], i["event_id"][-2:]) for i in second["items"]] == [("crm", "02")]
    assert second["next_cursor"] is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!",
        "eyJrIjoiaW5ib3giLCJwIjp7fX0",
        "eyJrIjoiZGVsaXZlcmllcyIsInAiOnsiY3JtIjp7ImJlZm9yZV9pZCI6IngifX19",
    ],
    ids=["garbage", "other-list", "bad-position"],
)
async def test_foreign_or_broken_cursor_is_422(
    web: Web, domains: BusDomainsFake, cursor: str
) -> None:
    await _admin(web)
    response = await web.client.get(f"{BASE}/deliveries", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["details"] == {"fields": ["cursor"]}
    assert domains.calls == []


async def test_retries_are_proxied_to_the_domain_with_the_employee_token(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    domains.answer("erp", "POST", "deliveries/retry-dead", {"retried": 4})
    domains.answer("eds", "POST", "deliveries/retry", {"retried": 0})
    await _admin(web)

    dead = await web.send("POST", f"{BASE}/erp/deliveries/retry-dead", json={"subscriber": "crm"})
    check(dead, "/admin/bus/{domain}/deliveries/retry-dead", "post")
    assert dead.json() == {"retried": 4}
    [call] = domains.made("erp", "POST", "deliveries/retry-dead")
    assert str(call.url).endswith("/api/v1/integration/bus/deliveries/retry-dead/")
    assert json.loads(call.content) == {"subscriber": "crm"}

    again = await web.send("POST", f"{BASE}/eds/deliveries/42/retry")
    check(again, "/admin/bus/{domain}/deliveries/{id}/retry", "post")
    assert again.json() == {"retried": 0}
    [eds_call] = domains.made("eds", "POST", "deliveries/retry")
    assert str(eds_call.url).endswith("/api/v1/bus/deliveries/42/retry")
    assert eds_call.headers["authorization"] == "Bearer eds-access-1"

    inbox = await web.send("POST", f"{BASE}/crm/inbox/{EVENT}/retry")
    check(inbox, "/admin/bus/{domain}/inbox/{event_id}/retry", "post")
    [crm_call] = domains.made("crm", "POST", "inbox/retry")
    assert str(crm_call.url).endswith(f"/api/v1/bus/inbox/{EVENT}/retry")


async def test_retry_errors_keep_the_error_format(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    domains.answer(
        "eds", "POST", "deliveries/retry-dead", {"code": "FORBIDDEN", "source": "eds"}, 403
    )
    domains.answer("crm", "POST", "deliveries/retry", {"code": "x"}, 503)
    await _admin(web)
    denied = await web.send("POST", f"{BASE}/eds/deliveries/retry-dead", json={"subscriber": "erp"})
    check(denied, "/admin/bus/{domain}/deliveries/retry-dead", "post")
    assert (denied.status_code, denied.json()["source"], denied.json()["code"]) == (
        403,
        "eds",
        "FORBIDDEN",
    )
    down = await web.send("POST", f"{BASE}/crm/deliveries/1/retry")
    check(down, "/admin/bus/{domain}/deliveries/{id}/retry", "post")
    assert (down.status_code, down.json()["source"]) == (503, "crm")
    for url, body in (
        (f"{BASE}/hr/deliveries/1/retry", None),
        (f"{BASE}/crm/deliveries/0/retry", None),
        (f"{BASE}/crm/deliveries/retry-dead", {"subscriber": "CRM!"}),
        (f"{BASE}/crm/inbox/not-a-uuid/retry", None),
    ):
        assert (await web.send("POST", url, json=body)).status_code == 422, url
    no_csrf = await web.client.post(f"{BASE}/crm/deliveries/1/retry")
    assert (no_csrf.status_code, no_csrf.json()["code"]) == (403, "CSRF_FAILED")
