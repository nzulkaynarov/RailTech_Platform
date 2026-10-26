"""Admin · Журнал интеграций: шина `rt_bus` трёх доменов в одном журнале (W13-A2).

BFF не решает: сводку, доставки, inbox и повторы считает и пишет каждый домен (общий код `rt_bus`),
право — тоже домен (CRM `integrations:*`, ERP `team.manage`, EDS `bus.manage`). Здесь только:

* вызовы доменов от имени сотрудника, параллельно; домен, который не ответил или отказал, — в
  `sources` (`unavailable`, `forbidden`, `not_applicable`), ответ 200 с остальными;
* состояние подписчика словом (`subscriber_state`) — по фактам домена, без своих правил шины;
* слияние страниц трёх доменов по времени и составной непрозрачный курсор (`Pager`): у каждого
домена
  свой keyset (`before_id`; `before` + `before_event_id`), страница BFF берёт из доменов строки по
  порядку времени и запоминает, где остановилась в каждом.
"""

import asyncio
import base64
import binascii
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from app.deps import Authed
from app.errors import PlatformError
from app.schemas_bus import (
    DOMAINS,
    BusDomain,
    BusSources,
    BusSourceState,
    DomainSubscriber,
    SubscriberState,
)

log = structlog.get_logger()

Params = dict[str, Any]


def bus_path(domain: BusDomain, tail: str) -> str:
    """Путь журнала шины в домене: ERP — `/api/v1/integration/bus/…/` (DRF), CRM и EDS —
    `/api/v1/bus/…`."""
    if domain == "erp":
        return f"/api/v1/integration/bus/{tail}/"
    return f"/api/v1/bus/{tail}"


def subscriber_state(sub: DomainSubscriber) -> SubscriberState:
    """Состояние словом, по важности: убран из подписок, выключен, пауза, DLQ, ошибки подряд,
    работает."""
    if not sub.configured:
        return "removed"
    if not sub.enabled:
        return "disabled"
    if sub.paused_until is not None:
        return "paused"
    if sub.dead > 0:
        return "dead_letters"
    if sub.consecutive_failures > 0:
        return "failing"
    return "ok"


@dataclass
class Fetched:
    """Ответ домена или причина, почему его нет."""

    state: BusSourceState
    response: httpx.Response | None = None


async def fetch(
    authed: Authed,
    domain: BusDomain,
    method: str,
    path: str,
    *,
    params: Params | None = None,
    json_body: Any = None,
) -> Fetched:
    """Вызов домена от имени сотрудника. Сбой — `unavailable`, отказ домена — `forbidden`, нет
    доступа
    к домену у сотрудника — `not_applicable`; истёкшая сессия (401) поднимается дальше."""
    if domain == "erp" and authed.data.erp_state == "not_applicable":
        return Fetched("not_applicable")
    try:
        response = await authed.call(domain, method, path, params=params, json=json_body)
    except PlatformError as exc:
        if exc.status_code == 503:
            return Fetched("unavailable")
        reason = (exc.body.details or {}).get("reason")
        if exc.status_code == 403 and isinstance(reason, str) and reason.endswith("_not_granted"):
            return Fetched("not_applicable")
        raise
    if response.status_code == 403:
        return Fetched("forbidden")
    if response.status_code != 200:
        log.warning("bus_journal_domain_failed", domain=domain, status=response.status_code)
        return Fetched("unavailable")
    return Fetched("ok", response)


def parse[T: BaseModel](model: type[T], fetched: Fetched, domain: BusDomain) -> T | None:
    """Тело ответа домена по модели; нечитаемое — как недоступный домен (в лог без тела)."""
    if fetched.response is None:
        return None
    try:
        return model.model_validate(fetched.response.json())
    except (ValueError, ValidationError):
        log.warning("bus_journal_domain_unreadable", domain=domain)
        fetched.state = "unavailable"
        return None


def sources(states: dict[BusDomain, BusSourceState]) -> BusSources:
    return BusSources(**{d: states.get(d, "not_applicable") for d in DOMAINS})


# --- страницы трёх доменов ------------------------------------------------------------------------


def bad_cursor() -> PlatformError:
    return PlatformError(
        "VALIDATION_FAILED",
        "Проверьте заполнение полей.",
        status_code=422,
        details={"fields": ["cursor"]},
    )


def _encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> dict[str, Any]:
    try:
        raw = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (binascii.Error, ValueError) as exc:
        raise bad_cursor() from exc
    if not isinstance(raw, dict):
        raise bad_cursor()
    return raw


@dataclass(frozen=True)
class Keyset:
    """Как продолжить список домена: из последней показанной строки — параметры запроса домена."""

    kind: str
    time_of: Callable[[Any], datetime]
    params_of: Callable[[Any], Params]
    check: Callable[[Params], Params]


def _delivery_params(params: Params) -> Params:
    before_id = params.get("before_id")
    if set(params) != {"before_id"} or not isinstance(before_id, int) or before_id < 1:
        raise bad_cursor()
    return {"before_id": before_id}


def _inbox_params(params: Params) -> Params:
    if set(params) != {"before", "before_event_id"}:
        raise bad_cursor()
    try:
        before = datetime.fromisoformat(str(params["before"]))
        event_id = uuid.UUID(str(params["before_event_id"]))
    except ValueError as exc:
        raise bad_cursor() from exc
    return {"before": before.isoformat(), "before_event_id": str(event_id)}


DELIVERIES = Keyset(
    kind="deliveries",
    time_of=lambda row: row.created_at,
    params_of=lambda row: {"before_id": row.id},
    check=_delivery_params,
)
INBOX = Keyset(
    kind="inbox",
    time_of=lambda row: row.received_at,
    params_of=lambda row: {"before": row.received_at.isoformat(), "before_event_id": row.event_id},
    check=_inbox_params,
)


@dataclass
class Pager:
    """Составной курсор: для каждого домена — где продолжить (`{}` — с начала) или `None` (дошли до
    конца)."""

    keyset: Keyset
    positions: dict[BusDomain, Params | None] = field(default_factory=dict)

    @classmethod
    def start(cls, keyset: Keyset, domains: Sequence[BusDomain], cursor: str | None) -> "Pager":
        if cursor is None:
            return cls(keyset, {d: {} for d in domains})
        raw = _decode(cursor)
        if raw.get("k") != keyset.kind or not isinstance(raw.get("p"), dict):
            raise bad_cursor()
        positions: dict[BusDomain, Params | None] = {}
        for domain, params in raw["p"].items():
            if domain not in domains:
                raise bad_cursor()
            if params is not None and not isinstance(params, dict):
                raise bad_cursor()
            positions[domain] = None if params is None else (params and keyset.check(params))
        return cls(keyset, positions)

    def pending(self) -> list[BusDomain]:
        """Домены, у которых ещё есть строки (по порядку DOMAINS)."""
        return [d for d in DOMAINS if d in self.positions and self.positions[d] is not None]

    def take(
        self, pages: dict[BusDomain, tuple[list[Any], bool]], limit: int
    ) -> list[tuple[BusDomain, Any]]:
        """Слить страницы доменов по времени (новые сверху) и сдвинуть позиции на показанное.

        Домен без ответа (нет в `pages`) считается дошедшим до конца: страница и так неполная
        (`sources`), а «Показать ещё» не крутится вхолостую по недоступному домену.
        """
        heads = dict.fromkeys(pages, 0)
        merged: list[tuple[BusDomain, Any]] = []
        while len(merged) < limit:
            best: BusDomain | None = None
            for domain, (rows, _more) in pages.items():
                if heads[domain] >= len(rows):
                    continue
                candidate = rows[heads[domain]]
                if best is None or self.keyset.time_of(candidate) > self.keyset.time_of(
                    pages[best][0][heads[best]]
                ):
                    best = domain
            if best is None:
                break
            merged.append((best, pages[best][0][heads[best]]))
            heads[best] += 1
        for domain in self.pending():
            if domain not in pages:
                self.positions[domain] = None
                continue
            rows, more = pages[domain]
            used = heads[domain]
            if used:
                self.positions[domain] = self.keyset.params_of(rows[used - 1])
            if used == len(rows) and not more:
                self.positions[domain] = None
        return merged

    def next_cursor(self) -> str | None:
        if not self.pending():
            return None
        return _encode({"k": self.keyset.kind, "p": dict(self.positions)})


async def gather_pages[T: BaseModel](
    authed: Authed,
    pager: Pager,
    tail: str,
    filters: Params,
    limit: int,
    page_model: type[T],
    states: dict[BusDomain, BusSourceState],
) -> dict[BusDomain, tuple[list[Any], bool]]:
    """Параллельно по доменам, у которых ещё есть строки: страница `limit` с позиции домена."""
    domains = pager.pending()

    async def one(domain: BusDomain) -> tuple[BusDomain, Fetched]:
        params = {**filters, **(pager.positions[domain] or {}), "limit": limit}
        return domain, await fetch(authed, domain, "GET", bus_path(domain, tail), params=params)

    pages: dict[BusDomain, tuple[list[Any], bool]] = {}
    for domain, fetched in await asyncio.gather(*(one(d) for d in domains)):
        page = parse(page_model, fetched, domain)
        states[domain] = fetched.state
        if page is not None:
            pages[domain] = (list(page.items), bool(page.has_more))  # type: ignore[attr-defined]
    return pages
