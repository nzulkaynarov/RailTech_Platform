"""Журнал шины трёх доменов для тестов Admin · Журнал интеграций (W13-A2): CRM, ERP и EDS на respx.

Ответы — в форме `crm.yaml` (`BusOverviewOut`…), `erp-internal.yaml` и `eds.yaml` (`BusOverview`…):
поля у всех трёх одни (общий код `rt_bus`). EDS принимает только свой токен доступа — его BFF
получает обменом SSO-токена CRM `aud=eds`. Данные выдуманы.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL, EDS_URL, ERP_URL

DOMAIN_URL = {"crm": CRM_URL, "erp": ERP_URL, "eds": EDS_URL}
EDS_TOKEN = "eds-access-"


def bus_url(domain: str, tail: str) -> str:
    if domain == "erp":
        return f"{ERP_URL}/api/v1/integration/bus/{tail}/"
    return f"{DOMAIN_URL[domain]}/api/v1/bus/{tail}"


def subscriber(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "configured": True,
        "enabled": True,
        "drop": False,
        "endpoint": f"http://{name}:8000/bus/v1/events",
        "pending": 0,
        "in_flight": 0,
        "dead": 0,
        "oldest_undelivered_age_seconds": None,
        "consecutive_failures": 0,
        "paused_until": None,
        "last_failure_at": None,
        "last_success_at": "2026-10-26T08:59:00Z",
        "last_error": None,
        **over,
    }


def overview(service: str, subscribers: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    return {
        "service": service,
        "outbox_pending": 0,
        "oldest_undelivered_age_seconds": None,
        "dlq_size": sum(s["dead"] for s in subscribers),
        "inbox_received": 0,
        "inbox_retrying": 0,
        "inbox_failed": 0,
        "subscribers": subscribers,
        **over,
    }


def delivery(row_id: int, minute: int, **over: Any) -> dict[str, Any]:
    return {
        "id": row_id,
        "event_id": f"00000000-0000-4000-8000-{row_id:012d}",
        "event_type": "uz.railtech.erp.quote.sent.v1",
        "subscriber": "crm",
        "status": "dead",
        "attempts": 1,
        "next_attempt_at": None,
        "last_attempt_at": f"2026-10-26T09:{minute:02d}:00Z",
        "last_status_code": 404,
        "last_error": "HTTP 404: not found",
        "delivered_at": None,
        "created_at": f"2026-10-26T09:{minute:02d}:00Z",
        "subject": "КП-2026-017",
        "correlation_id": f"req-{row_id}",
        "event_created_at": f"2026-10-26T09:{minute:02d}:00Z",
        **over,
    }


def inbox_entry(event_no: int, minute: int, **over: Any) -> dict[str, Any]:
    return {
        "event_id": f"10000000-0000-4000-8000-{event_no:012d}",
        "type": "uz.railtech.crm.client.updated.v1",
        "source": "rt://crm",
        "publisher": "crm",
        "subject": "client/7",
        "correlation_id": f"req-in-{event_no}",
        "status": "failed",
        "attempts": 4,
        "error": "ValueError: company is not known",
        "received_at": f"2026-10-26T09:{minute:02d}:00Z",
        "processed_at": None,
        **over,
    }


def page(items: list[dict[str, Any]], has_more: bool = False) -> dict[str, Any]:
    return {"items": items, "has_more": has_more}


Answer = Callable[[httpx.Request], httpx.Response]


class BusDomainsFake:
    """Журнал шины CRM, ERP и EDS; EDS — с входом по SSO-токену CRM `aud=eds` (обмен в EDS)."""

    def __init__(self, be: Backends) -> None:
        self.be = be
        self.eds_sso_status = 200
        self.eds_exchange_status = 200
        self.eds_issued: list[str] = []
        self.sso_auds: list[str] = []
        self.answers: dict[tuple[str, str, str], Answer] = {}
        self.calls: list[tuple[str, str, str, httpx.Request]] = []
        be.crm_sso.side_effect = self._sso
        self.exchange = be.router.post(f"{EDS_URL}/api/v1/auth/sso/exchange").mock(
            side_effect=self._exchange
        )
        for domain in DOMAIN_URL:
            for tail in ("overview", "deliveries", "inbox"):
                be.router.get(bus_url(domain, tail)).mock(
                    side_effect=self._route(domain, "GET", tail)
                )
            be.router.post(bus_url(domain, "deliveries/retry-dead")).mock(
                side_effect=self._route(domain, "POST", "deliveries/retry-dead")
            )
            base = "integration/bus" if domain == "erp" else "bus"
            prefix = re.escape(f"{DOMAIN_URL[domain]}/api/v1/{base}")
            be.router.post(url__regex=rf"^{prefix}/deliveries/\d+/retry/?$").mock(
                side_effect=self._route(domain, "POST", "deliveries/retry")
            )
            be.router.post(url__regex=rf"^{prefix}/inbox/[0-9a-f-]+/retry/?$").mock(
                side_effect=self._route(domain, "POST", "inbox/retry")
            )
        for domain, service in (("crm", "crm"), ("erp", "erp"), ("eds", "eds")):
            self.answer(domain, "GET", "overview", overview(service, [subscriber("platform-bff")]))
            self.answer(domain, "GET", "deliveries", page([]))
            self.answer(domain, "GET", "inbox", page([]))
            for tail in ("deliveries/retry-dead", "deliveries/retry", "inbox/retry"):
                self.answer(domain, "POST", tail, {"retried": 1})

    def answer(self, domain: str, method: str, tail: str, body: Any, status: int = 200) -> None:
        self.answers[(domain, method, tail)] = lambda _: httpx.Response(status, json=body)

    def answer_with(self, domain: str, method: str, tail: str, func: Answer) -> None:
        self.answers[(domain, method, tail)] = func

    def made(self, domain: str, method: str, tail: str) -> list[httpx.Request]:
        return [r for d, m, t, r in self.calls if (d, m, t) == (domain, method, tail)]

    # --- вход в EDS ---
    def _sso(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        aud = body.get("aud", "erp")
        self.sso_auds.append(aud)
        if aud != "eds":
            return httpx.Response(
                200, json={"token": "sso-token-1", "redirect_url": "http://erp.test/sso"}
            )
        if self.eds_sso_status != 200:
            return httpx.Response(
                self.eds_sso_status,
                json={
                    "code": "forbidden",
                    "message": "x",
                    "details": {"reason": "eds_access_denied"},
                },
            )
        return httpx.Response(
            200, json={"token": f"sso-eds-{len(self.sso_auds)}", "redirect_url": ""}
        )

    def exchange_response(self, request: httpx.Request) -> httpx.Response:
        """Ответ обмена в EDS (тест может обернуть его, например, задержкой)."""
        return self._exchange(request)

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        if self.eds_exchange_status != 200:
            return httpx.Response(
                self.eds_exchange_status,
                json={"code": "USER_NOT_PROVISIONED", "message": "x", "source": "eds"},
            )
        token = f"{EDS_TOKEN}{len(self.eds_issued) + 1}"
        self.eds_issued.append(token)
        return httpx.Response(
            200, json={"access_token": token, "token_type": "bearer", "expires_in": 900}
        )

    # --- журнал ---
    def _route(self, domain: str, method: str, tail: str) -> Answer:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append((domain, method, tail, request))
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            if domain == "eds" and bearer not in self.eds_issued:
                return httpx.Response(
                    401, json={"code": "UNAUTHORIZED", "message": "x", "source": "eds"}
                )
            if domain == "crm" and bearer not in self.be.crm_valid_access:
                return httpx.Response(
                    401, json={"code": "auth_failed", "message": "x", "details": {}}
                )
            return self.answers[(domain, method, tail)](request)

        return handle
