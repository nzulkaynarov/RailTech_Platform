"""CRM и ERP на respx для Dashboard, уведомлений и поиска: управляемые ответы, вымышленные данные"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
            # КП на одобрении на моём шаге (D26G-4): строки `quote()`; мок EDS отдаёт их маршрутами
            # (`GET /approvals?template=quote`) и снимками карточек (`GET /approvals/{id}`)
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
            # Просроченные заказы поставщикам (ERP `stock/overdue`, D2-2): пусто, пока нет строк
            "overdue": {"results": []},
            "activity_logs": (403, {"detail": "PLATFORM_ADMIN_REQUIRED"}),
            "timeline": [],
            # EDS (D1-6): письма «Ждут резолюции», маршруты на моём шаге, реестр для поиска
            "letters": {"items": [], "next_cursor": None},
            "memos": {"items": [], "next_cursor": None},
            "registry": {"items": [], "next_cursor": None},
            # EDS (P8b): мои поручения, переносы на решение и ознакомления
            "letter_tasks": {"instructions": [], "extensions": [], "acquaintances": []},
            # D2-8, работа ERP: мои задания на расчёт, доска счетов по вкладкам, проекты по шагам
            "calc_tasks": {"results": []},
            "receivables": {"proofs": [], "to_issue": []},
            "receivable_counts": {"to_issue": 0, "awaiting": 0, "proofs": 0, "overdue": 0},
            "projects": {"CONTRACT": [], "PAYMENT": []},
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
            # Старый источник строк КП (до D26G-4): BFF его больше не зовёт — тесты проверяют ноль
            "approvals": self._erp(
                "approvals", router.get(f"{base}/crm/quotes/my-approval-queue/")
            ),
            "deals": router.get(f"{base}/crm/deals/").mock(side_effect=self._deals),
            "notifications": self._erp("notifications", router.get(f"{base}/notifications/")),
            "documents": self._erp(
                "documents", router.get(f"{base}/crm/analytics/search-documents/")
            ),
            "activity_logs": self._erp("activity_logs", router.get(f"{base}/crm/activity-logs/")),
            "timeline": self._erp("timeline", router.get(f"{base}/crm/timeline/")),
            "overdue": self._erp("overdue", router.get(f"{base}/stock/overdue/")),
            "calc_tasks": self._erp("calc_tasks", router.get(f"{base}/calc/tasks/")),
            "receivables": router.get(f"{base}/finance/receivables/").mock(
                side_effect=self._receivables
            ),
            "projects": router.get(f"{base}/crm/projects/").mock(side_effect=self._projects),
        }
        self.deal_by_id = router.get(
            url__regex=re.compile(rf"^{ERP_URL}/api/v1/crm/deals/\d+/$")
        ).mock(side_effect=self._deal)
        self.eds = {
            "letters": self._eds("letters", router.get(f"{EDS_URL}/api/v1/letters")),
            "approvals": router.get(f"{EDS_URL}/api/v1/approvals").mock(
                side_effect=self._approvals
            ),
            "approval": router.get(
                url__regex=re.compile(rf"^{EDS_URL}/api/v1/approvals/[0-9a-f-]+$")
            ).mock(side_effect=self._approval),
            "registry": self._eds("registry", router.get(f"{EDS_URL}/api/v1/registry")),
            "letter_tasks": self._eds("letter_tasks", router.get(f"{EDS_URL}/api/v1/letter-tasks")),
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
        # EDS (D1-6b): возвращённые документы автора и карточки с решением «Вернуть»
        self.state["returned"] = {"items": [], "next_cursor": None}
        self.cards: dict[str, Any] = {}
        self.eds["returned"] = self._eds("returned", router.get(f"{EDS_URL}/api/v1/documents"))
        self.eds["card"] = router.get(
            url__regex=re.compile(rf"^{EDS_URL}/api/v1/documents/[0-9a-f-]+$")
        ).mock(side_effect=self._card)

    def _approvals(self, request: httpx.Request) -> httpx.Response:
        """EDS `GET /approvals`: КП (`template=quote`) — из `state["approvals"]`, иначе служебки."""
        if "quote" not in request.url.params.get_list("template"):
            return self._respond("memos", self.eds_down)
        if self.eds_down is not None:
            return self._respond("approvals", self.eds_down)
        raw = self.state["approvals"]
        if isinstance(raw, tuple):
            return httpx.Response(raw[0], json=raw[1])
        items = [quote_route(q) for q in raw["results"]]
        more = int(raw.get("count") or 0) > len(items)
        return httpx.Response(200, json={"items": items, "next_cursor": "c2" if more else None})

    def _approval(self, request: httpx.Request) -> httpx.Response:
        """EDS `GET /approvals/{id}`: снимок КП решающему шаг (без снимка — 404, строка без
        суммы)."""
        if self.eds_down is not None:
            return self._respond("approvals", self.eds_down)
        route_id = request.url.path.rsplit("/", 1)[-1]
        raw = self.state["approvals"]
        for q in raw["results"] if isinstance(raw, dict) else []:
            if quote_route_id(q["id"]) == route_id and q.get("snapshot", True):
                return httpx.Response(200, json={"id": route_id, "quote": quote_snapshot(q)})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "x", "source": "eds"})

    def quote_lists(self) -> int:
        """Сколько раз BFF читал КП на моём шаге из EDS."""
        return sum(
            1
            for call in self.eds["approvals"].calls
            if "quote" in call.request.url.params.get_list("template")
        )

    def _card(self, request: httpx.Request) -> httpx.Response:
        if self.eds_down is not None:
            return self._respond("returned", self.eds_down)
        found = self.cards.get(request.url.path.rsplit("/", 1)[-1])
        if found is None:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": "x", "source": "eds"})
        return httpx.Response(200, json=found)

    def _deals(self, request: httpx.Request) -> httpx.Response:
        """Список сделок ERP; с `?search=` — как ERP-09: номер (латиница и пробелы допустимы,
        NNN под любым префиксом), название и компания; страница — `page_size`."""
        response = self._respond("deals", self.erp_down)
        term = request.url.params.get("search")
        if term is None or response.status_code != 200:
            return response
        body = json.loads(response.content)
        found = [d for d in body["results"] if deal_matches(d, term)]
        size = request.url.params.get("page_size")
        page = found[: int(size)] if size else found
        return httpx.Response(200, json={**body, "count": len(found), "results": page})

    def _receivables(self, request: httpx.Request) -> httpx.Response:
        """Доска счетов ERP: строки вкладки `tab` и числа всех вкладок (`counts`)."""
        if self.erp_down is not None:
            return self._respond("receivables", self.erp_down)
        tab = request.url.params.get("tab", "awaiting")
        items = self.state["receivables"].get(tab, [])
        body = {
            "tab": tab,
            "count": len(items),
            "counts": self.state["receivable_counts"],
            "results": items,
        }
        return httpx.Response(200, json=body)

    def _projects(self, request: httpx.Request) -> httpx.Response:
        """Проекты ERP по шагу `step`."""
        if self.erp_down is not None:
            return self._respond("projects", self.erp_down)
        items = self.state["projects"].get(request.url.params.get("step", ""), [])
        return httpx.Response(200, json={"count": len(items), "results": items})

    def _deal(self, request: httpx.Request) -> httpx.Response:
        """Сделка по id (`/crm/deals/{id}/`)."""
        deal_id = int(request.url.path.rstrip("/").rsplit("/", 1)[1])
        for item in self.state["deals"]["results"]:
            if item["id"] == deal_id:
                return httpx.Response(200, json=item)
        return httpx.Response(404, json={"detail": "Not found."})

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


_PROJECT_STAGES = ("CONTRACT_SIGNED", "CLOSED_WON")


def deal_number_of(deal_id: int, stage: str, created: str, complete: bool) -> str:
    """Номер, который выдал бы ERP: `ЗВ-ГГГГ-NNN`, у проекта (договор подписан) — `ПР-`."""
    prefix = "ПР" if complete or stage in _PROJECT_STAGES else "ЗВ"
    return f"{prefix}-{created[:4]}-{deal_id:03d}"


def _normal(text: str) -> str:
    folded = text.casefold().replace("zv", "зв").replace("pr", "пр")
    return "".join(ch for ch in folded if ch not in " -–—/")


def deal_matches(deal: dict[str, Any], term: str) -> bool:
    """Поиск сделок ERP-09: номер (латиница ZV/PR и пробелы допустимы), название, компания."""
    needle = _normal(term)
    number = _normal(str(deal.get("number") or ""))
    title = str(deal.get("title") or "").casefold()
    company = str(deal.get("company_name") or "").casefold()
    return bool(needle) and (
        needle in number or term.strip().casefold() in title or term.strip().casefold() in company
    )


def deal(
    deal_id: int,
    stage: str,
    *,
    title: str = "",
    company: str | None = "ООО «Демо-Депо»",
    created: str = "2027-01-10T08:00:00Z",
    complete: bool = False,
    number: str | Literal["auto"] | None = "auto",
) -> dict[str, Any]:
    """Сделка ERP со «служебными» полями, которые Платформа не должна показывать. `number` —
    номер ERP (`auto` — как выдал бы ERP; `None` — ERP номера не отдал)."""
    return {
        "id": deal_id,
        "number": deal_number_of(deal_id, stage, created, complete) if number == "auto" else number,
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
    client_name: str | None = None,
    deal_number: str | None = None,
    snapshot: bool = True,
) -> dict[str, Any]:
    """КП на одобрении (D26G-4: источник — маршрут EDS, см. `quote_route` и `quote_snapshot`)."""
    return {
        "client_name": client_name,
        "deal_number": deal_number,
        "snapshot": snapshot,
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


def quote_route_id(quote_id: int) -> str:
    return f"50000000-0000-4000-8000-{quote_id:012d}"


def quote_route(q: dict[str, Any]) -> dict[str, Any]:
    """Строка `quote()` как маршрут EDS на моём шаге (`ApprovalListItem`)."""
    return {
        "id": quote_route_id(q["id"]),
        "template": "quote",
        "title": f"{q['number'] or 'КП'} v{q['version']}",
        "object": {
            "kind": "quote",
            "erp_quote_id": q["id"],
            "quote_number": q["number"],
            "quote_version": q["version"],
            "erp_deal_id": q["deal"],
            "deal_number": q.get("deal_number"),
        },
        "status": "open",
        "round": 1,
        "current_step": {
            "index": 0,
            "label": "Директор",
            "assignee": {"crm_user_id": None, "permission": "approvals.decide"},
            "status": "current",
        },
        "created_at": q["created_at"],
    }


def quote_snapshot(q: dict[str, Any]) -> dict[str, Any]:
    """Снимок КП карточки маршрута EDS (решающему — с экономикой, BFF её не показывает)."""
    return {
        "erp_quote_id": q["id"],
        "number": q["number"] or "",
        "version": q["version"],
        "client_name": q.get("client_name"),
        "total": q["total_incl_vat"],
        "currency": q["quote_currency"],
        "cost": "9000000.00",
        "margin_amount": "2000000.00",
        "margin_pct": "23.40",
        "valid_until": q["valid_until"],
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
