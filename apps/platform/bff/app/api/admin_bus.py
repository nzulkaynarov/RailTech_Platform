"""Admin · Журнал интеграций (контракт: tag `bus`, 0.9.0; W13-A2) — шина `rt_bus` CRM, ERP и EDS.

Только раздел `admin` уровня `full` (директору — 403 в BFF, до доменов). Чтение — сводка, доставки,
принятые события — сводится из трёх доменов (`app.bus_journal`), повторы — прокси к домену, который
пишет повтор в свой журнал с автором. Всё — с токеном сотрудника; в EDS — токен доступа, полученный
обменом SSO-токена CRM (`app.auth`).
"""

import asyncio
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.bus_journal import (
    DELIVERIES,
    INBOX,
    Fetched,
    Pager,
    bus_path,
    fetch,
    gather_pages,
    parse,
    sources,
    subscriber_state,
)
from app.deps import Authed, require
from app.errors import PlatformError, backend_unavailable, from_backend
from app.schemas_bus import (
    DOMAINS,
    SUBSCRIBER_PATTERN,
    BusDelivery,
    BusDeliveryPage,
    BusDomain,
    BusDomainOverview,
    BusInboxEntry,
    BusInboxPage,
    BusJournal,
    BusRetryDeadIn,
    BusRetryResult,
    BusSourceState,
    BusSubscriber,
    DeliveryStatus,
    DomainDeliveryPage,
    DomainInboxPage,
    DomainOverview,
    DomainRetry,
    InboxStatus,
)

router = APIRouter(prefix="/admin/bus", tags=["bus"])

Admin = Annotated[Authed, Depends(require("admin", "full"))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=2000)]
TypeQuery = Annotated[str | None, Query(min_length=1, max_length=200)]


def _scope(domain: BusDomain | None) -> tuple[BusDomain, ...]:
    return DOMAINS if domain is None else (domain,)


def _states(scope: tuple[BusDomain, ...]) -> dict[BusDomain, BusSourceState]:
    """Домены вне фильтра — `not_applicable`; дошедшие до конца на прошлых страницах — `ok`."""
    return {d: "ok" if d in scope else "not_applicable" for d in DOMAINS}


@router.get("", response_model=BusJournal, operation_id="getBusJournal")
async def journal(authed: Admin) -> BusJournal:
    async def one(domain: BusDomain) -> tuple[BusDomain, Fetched]:
        return domain, await fetch(authed, domain, "GET", bus_path(domain, "overview"))

    states = _states(DOMAINS)
    domains: list[BusDomainOverview] = []
    for domain, fetched in await asyncio.gather(*(one(d) for d in DOMAINS)):
        overview = parse(DomainOverview, fetched, domain)
        states[domain] = fetched.state
        if overview is None:
            continue
        subscribers = [
            BusSubscriber(**s.model_dump(), state=subscriber_state(s)) for s in overview.subscribers
        ]
        domains.append(
            BusDomainOverview(
                domain=domain,
                **overview.model_dump(exclude={"subscribers"}),
                subscribers=subscribers,
            )
        )
    return BusJournal(domains=domains, sources=sources(states))


@router.get("/deliveries", response_model=BusDeliveryPage, operation_id="listBusDeliveries")
async def deliveries(
    authed: Admin,
    domain: BusDomain | None = None,
    status: DeliveryStatus | None = None,
    subscriber: Annotated[str | None, Query(pattern=SUBSCRIBER_PATTERN)] = None,
    type: TypeQuery = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> BusDeliveryPage:
    scope = _scope(domain)
    pager = Pager.start(DELIVERIES, scope, cursor)
    filters: dict[str, Any] = {
        "status": status,
        "subscriber": subscriber,
        "type": type,
        "created_from": from_.isoformat() if from_ else None,
        "created_to": to.isoformat() if to else None,
    }
    states = _states(scope)
    pages = await gather_pages(
        authed,
        pager,
        "deliveries",
        {k: v for k, v in filters.items() if v is not None},
        limit,
        DomainDeliveryPage,
        states,
    )
    items = [BusDelivery(**row.model_dump(), domain=d) for d, row in pager.take(pages, limit)]
    return BusDeliveryPage(items=items, next_cursor=pager.next_cursor(), sources=sources(states))


@router.get("/inbox", response_model=BusInboxPage, operation_id="listBusInbox")
async def inbox(
    authed: Admin,
    domain: BusDomain | None = None,
    errors: bool = False,
    status: InboxStatus | None = None,
    type: TypeQuery = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> BusInboxPage:
    scope = _scope(domain)
    pager = Pager.start(INBOX, scope, cursor)
    filters: dict[str, Any] = {"errors": "true" if errors else None, "status": status, "type": type}
    states = _states(scope)
    pages = await gather_pages(
        authed,
        pager,
        "inbox",
        {k: v for k, v in filters.items() if v is not None},
        limit,
        DomainInboxPage,
        states,
    )
    items = [BusInboxEntry(**row.model_dump(), domain=d) for d, row in pager.take(pages, limit)]
    return BusInboxPage(items=items, next_cursor=pager.next_cursor(), sources=sources(states))


async def _retry(authed: Authed, domain: BusDomain, tail: str, body: Any = None) -> BusRetryResult:
    """Повтор в домене: отказ домена — 403 с его кодом, сбой — 503; ответ — сколько поставлено."""
    response = await authed.call(domain, "POST", bus_path(domain, tail), json=body)
    if response.status_code != 200:
        raise from_backend(domain, response)
    try:
        result = DomainRetry.model_validate(response.json())
    except ValueError as exc:
        raise backend_unavailable(domain, "bad_retry_response") from exc
    return BusRetryResult(retried=result.retried)


def _forbid_erp_without_access(authed: Authed, domain: BusDomain) -> None:
    if domain == "erp" and authed.data.erp_state == "not_applicable":
        raise PlatformError(
            "FORBIDDEN",
            "Нет доступа к ERP.",
            status_code=403,
            source="erp",
            details={"reason": "erp_not_granted"},
        )


@router.post(
    "/{domain}/deliveries/{id}/retry",
    response_model=BusRetryResult,
    operation_id="retryBusDelivery",
)
async def retry_delivery(
    domain: BusDomain, id: Annotated[int, Path(ge=1)], authed: Admin
) -> BusRetryResult:
    _forbid_erp_without_access(authed, domain)
    return await _retry(authed, domain, f"deliveries/{id}/retry")


@router.post(
    "/{domain}/deliveries/retry-dead",
    response_model=BusRetryResult,
    operation_id="retryBusDeadLetters",
)
async def retry_dead(domain: BusDomain, body: BusRetryDeadIn, authed: Admin) -> BusRetryResult:
    _forbid_erp_without_access(authed, domain)
    return await _retry(authed, domain, "deliveries/retry-dead", {"subscriber": body.subscriber})


@router.post(
    "/{domain}/inbox/{event_id}/retry",
    response_model=BusRetryResult,
    operation_id="retryBusInbox",
)
async def retry_inbox(domain: BusDomain, event_id: uuid.UUID, authed: Admin) -> BusRetryResult:
    _forbid_erp_without_access(authed, domain)
    return await _retry(authed, domain, f"inbox/{event_id}/retry")
