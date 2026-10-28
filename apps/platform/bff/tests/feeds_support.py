"""CRM и ERP на respx для Dashboard, уведомлений и поиска: управляемые ответы, вымышленные данные"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import respx

from tests.consts import CRM_URL, EDS_URL, ERP_URL
from tests.fakes import Clock

Handler = Callable[[httpx.Request], httpx.Response]


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class Moments:
    """Моменты времени относительно часов тестов (08:00 UTC = 13:00 в поясе компании)."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    @property
    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def ago(self, **delta: float) -> str:
        return iso(self.now - timedelta(**delta))

    def ahead(self, **delta: float) -> str:
        return iso(self.now + timedelta(**delta))


class FeedBackends:
    """Ответы CRM и ERP, которые тест подменяет: значение (200), `(статус, тело)` или сбой сети."""

    def __init__(self, router: respx.MockRouter, moments: Moments) -> None:
        self.m = moments
        self.state: dict[str, Any] = {
            "inbox": {"escalations": [], "mine": [], "unassigned": []},
            "covering": [],
            # on_behalf_of -> очередь замещаемого; значение-кортеж (код, тело) — отказ CRM
            "covered_inbox": {},
            "leads": {"items": [], "total": 0},
            "lead": (404, {"code": "not_found", "message": "x", "details": {}}),
            "clients": [],
            "approvals": {"count": 0, "next": None, "previous": None, "results": []},
            "deals": {"count": 0, "next": None, "previous": None, "results": []},
            "notifications": {"count": 0, "next": None, "previous": None, "results": []},
            # Лента CRM (`staff_notifications`, W15-H7): пустая, пока тест не положит строки
            "crm_notifications": {"items": [], "unread_count": 0},
            # Новые обращения сотрудников для «Моих задач» администратора (W15-H7)
            "crm_tickets": {
                "items": [],
                "total": 0,
                "counts": {"new": 0, "in_progress": 0, "resolved": 0},
            },
            "documents": {"results": []},
            "activity_logs": (403, {"detail": "PLATFORM_ADMIN_REQUIRED"}),
            "timeline": [],
            # EDS (D1-6): письма «Ждут резолюции», маршруты на моём шаге, реестр для поиска
            "letters": {"items": [], "next_cursor": None},
            "memos": {"items": [], "next_cursor": None},
            "registry": {"items": [], "next_cursor": None},
        }
        self.mark_read_status = 200
        self.mark_all_status = 200
        self.erp_down: Exception | int | None = None
        self.crm_down: Exception | int | None = None
        # EDS: сбой (исключение сети или статус) и отказ обмена токена («не заведён в EDS», 403)
        self.eds_down: Exception | int | None = None
        self.eds_exchange_status = 200
        self.crm = {
            "inbox": router.get(f"{CRM_URL}/api/v1/inbox").mock(side_effect=self._inbox),
            "covering": self._crm("covering", router.get(f"{CRM_URL}/api/v1/me/covering")),
            "leads": self._crm("leads", router.get(f"{CRM_URL}/api/v1/leads")),
            "clients": self._crm("clients", router.get(f"{CRM_URL}/api/v1/clients")),
            "notifications": self._crm(
                "crm_notifications", router.get(f"{CRM_URL}/api/v1/me/notifications")
            ),
            "tickets": self._crm("crm_tickets", router.get(f"{CRM_URL}/api/v1/staff-tickets")),
        }
        self.crm_read_status = 204
        self.crm_read = router.post(
            url__regex=re.compile(rf"^{CRM_URL}/api/v1/me/notifications/(\d+/read|read-all)$")
        ).mock(side_effect=lambda _r: httpx.Response(self.crm_read_status))
        self.lead = router.get(url__regex=re.compile(rf"^{CRM_URL}/api/v1/leads/\d+$")).mock(
            side_effect=lambda _r: self._respond("lead", self.crm_down)
        )
        base = f"{ERP_URL}/api/v1"
        self.erp = {
            "approvals": self._erp(
                "approvals", router.get(f"{base}/crm/quotes/my-approval-queue/")
            ),
            "deals": self._erp("deals", router.get(f"{base}/crm/deals/")),
            "notifications": self._erp("notifications", router.get(f"{base}/notifications/")),
            "documents": self._erp(
                "documents", router.get(f"{base}/crm/analytics/search-documents/")
            ),
            "activity_logs": self._erp("activity_logs", router.get(f"{base}/crm/activity-logs/")),
            "timeline": self._erp("timeline", router.get(f"{base}/crm/timeline/")),
        }
        self.eds = {
            "letters": self._eds("letters", router.get(f"{EDS_URL}/api/v1/letters")),
            "approvals": self._eds("memos", router.get(f"{EDS_URL}/api/v1/approvals")),
            "registry": self._eds("registry", router.get(f"{EDS_URL}/api/v1/registry")),
        }
        self.eds_exchange = router.post(f"{EDS_URL}/api/v1/auth/sso/exchange").mock(
            side_effect=self._eds_exchange
        )
        self.mark_read = router.patch(
            url__regex=re.compile(rf"^{ERP_URL}/api/v1/notifications/\d+/mark_read/$")
        ).mock(side_effect=lambda _r: self._respond_status(self.mark_read_status))
        self.mark_all = router.patch(f"{base}/notifications/mark_all_read/").mock(
            side_effect=lambda _r: self._respond_status(self.mark_all_status)
        )

    def _eds(self, key: str, route: respx.Route) -> respx.Route:
        return route.mock(side_effect=lambda _r: self._respond(key, self.eds_down))

    def _eds_exchange(self, request: httpx.Request) -> httpx.Response:
        if self.eds_exchange_status != 200:
            return httpx.Response(
                self.eds_exchange_status,
                json={"code": "USER_NOT_PROVISIONED", "message": "x", "source": "eds"},
            )
        return httpx.Response(
            200, json={"access_token": "eds-access-1", "token_type": "bearer", "expires_in": 900}
        )

    def _respond(self, key: str, down: Exception | int | None) -> httpx.Response:
        if isinstance(down, Exception):
            raise down
        if isinstance(down, int):
            return httpx.Response(down, json={"detail": "down"})
        value = self.state[key]
        if isinstance(value, tuple):
            status, body = value
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=value)

    def _inbox(self, request: httpx.Request) -> httpx.Response:
        """Своя очередь или (с `on_behalf_of`) очередь замещаемого."""
        behalf = request.url.params.get("on_behalf_of")
        if behalf is None:
            return self._respond("inbox", self.crm_down)
        value = self.state["covered_inbox"].get(int(behalf))
        if value is None:
            return httpx.Response(403, json={"code": "forbidden", "message": "x", "details": {}})
        if isinstance(value, tuple):
            return httpx.Response(value[0], json=value[1])
        return httpx.Response(200, json=value)

    def _respond_status(self, status: int) -> httpx.Response:
        if isinstance(self.erp_down, Exception):
            raise self.erp_down
        if isinstance(self.erp_down, int):
            return httpx.Response(self.erp_down, json={"detail": "down"})
        return httpx.Response(status, json={"status": "ok"})

    def _crm(self, key: str, route: respx.Route) -> respx.Route:
        return route.mock(side_effect=lambda _r: self._respond(key, self.crm_down))

    def _erp(self, key: str, route: respx.Route) -> respx.Route:
        return route.mock(side_effect=lambda _r: self._respond(key, self.erp_down))

    def calls(self, route: respx.Route) -> int:
        return len(route.calls)

    def query(self, route: respx.Route) -> dict[str, str]:
        return dict(route.calls.last.request.url.params)


def lead(
    lead_id: int,
    name: str,
    *,
    summary: str | None = None,
    unread: bool = False,
    escalation: dict[str, Any] | None = None,
    last_msg: str | None = None,
    created: str = "2027-01-14T08:00:00Z",
) -> dict[str, Any]:
    return {
        "id": lead_id,
        "display_name": name,
        "language": "ru",
        "stage": "handoff",
        "score": 50,
        "owner_mode": "human",
        "assigned_user_id": None,
        "need_summary": summary,
        "product_interest": [],
        "last_lead_msg_at": last_msg,
        "created_at": created,
        "unread": unread,
        "escalation": escalation,
    }


def escalation(
    *,
    taken_by: int | None = None,
    sla_due_at: str | None = None,
    snoozed_until: str | None = None,
    status: str = "open",
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": 1,
        "priority": "high",
        "status": status,
        "reason_codes": [],
        "reason_text": reason,
        "recommendation": None,
        "taken_by_user_id": taken_by,
        "taken_at": None,
        "sla_due_at": sla_due_at,
        "snoozed_until": snoozed_until,
        "created_at": "2027-01-14T08:00:00Z",
    }


def deal(
    deal_id: int,
    stage: str,
    *,
    title: str = "",
    company: str | None = "ООО «Демо-Депо»",
    created: str = "2027-01-10T08:00:00Z",
    complete: bool = False,
) -> dict[str, Any]:
    """Сделка ERP со «служебными» полями, которые Платформа не должна показывать."""
    return {
        "id": deal_id,
        "title": title,
        "company": 1,
        "company_name": company,
        "stage": 1,
        "stage_code": stage,
        "stage_name": stage,
        "total_value": "1000000.00",
        "execution_complete": complete,
        "created_at": created,
        "active_quote": {
            "id": deal_id * 10,
            "margin_percent": "23.40",
            "economics": {"gross_profit": "230000.00"},
            "charges": [{"name": "Логистика", "amount": "5000"}],
        },
    }


def quote(
    quote_id: int,
    deal_id: int,
    *,
    number: str | None,
    version: int = 1,
    total: str = "12450000.00",
    valid_until: str | None = None,
    created: str = "2027-01-14T08:00:00Z",
) -> dict[str, Any]:
    return {
        "id": quote_id,
        "deal": deal_id,
        "version": version,
        "number": number,
        "status_code": "PENDING_APPROVAL",
        "quote_currency": "UZS",
        "total_incl_vat": total,
        "valid_until": valid_until,
        "created_at": created,
        "margin_percent": "23.40",
        "economics": {"gross_profit": "2000000.00"},
    }


def notification(
    note_id: int,
    event: str,
    title: str,
    *,
    deal_id: int | None = None,
    read: bool = False,
    created: str = "2027-01-15T07:55:00Z",
    message: str = "",
) -> dict[str, Any]:
    return {
        "id": note_id,
        "user": 1,
        "type": 1,
        "type_code": "INFO",
        "type_name": "Info",
        "title": title,
        "message": message or title,
        "event_code": event,
        "event_params": {},
        "link": "",
        "deal": deal_id,
        "is_read": read,
        "created_at": created,
    }


def body(response: httpx.Response) -> Any:
    return json.loads(response.content)
