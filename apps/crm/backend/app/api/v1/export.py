"""Экспорт CSV для админа (аудит 2026-10-12 §5): лиды, клиенты, сделки с фильтрами списков.

Колонки — те же, что видны в списках CRM (без телефонов, переписки и квалификации); формат —
`domain/csv_export.py` (UTF-8 с BOM, `;`, даты по Ташкенту). Аудит `export.<entity>` с числом строк.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import ContainerDep, require
from app.api.v1.deals import deal_rows, filtered
from app.domain import csv_export
from app.models.auth import User
from app.models.leads import Lead
from app.repositories import clients as clients_repo
from app.repositories import crm
from app.schemas.deals import DealStageName
from app.security import audit
from app.security.principal import Principal
from app.services.channel_texts import STAGE

router = APIRouter(prefix="/api/v1/export", tags=["export"])

Exporter = Annotated[Principal, Depends(require("export", "read"))]
# Потолок одной выгрузки: больше — сузьте фильтры (защита памяти API).
MAX_ROWS: Final = 10_000
_PAGE: Final = 500
DEAL_STAGE: Final = {"open": "Открыта", "won": "Выиграна", "lost": "Проиграна"}

LEAD_HEADERS: Final = (
    "ID",
    "Имя",
    "Язык",
    "Стадия",
    "Оценка",
    "Ответственный",
    "Клиент ID",
    "Потребность",
    "Интерес к продуктам",
    "Последнее сообщение",
    "Создан",
)
CLIENT_HEADERS: Final = (
    "ID",
    "Название",
    "ИНН",
    "Сегмент",
    "Ответственный",
    "Активен",
    "Открытых сделок",
    "Последняя активность",
    "Создан",
)
DEAL_HEADERS: Final = (
    "ID",
    "Название",
    "Клиент",
    "Продукт",
    "Сумма",
    "Валюта",
    "Стадия",
    "Ожидаемое закрытие",
    "Закрыта",
    "Причина отказа",
    "Ответственный",
    "Создана",
)


async def _csv(
    who: Principal,
    container: ContainerDep,
    entity: str,
    headers: Sequence[str],
    rows: list[Sequence[csv_export.Cell]],
    filters: Mapping[str, object],
) -> StreamingResponse:
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session,
            who.actor,
            f"export.{entity}",
            "export",
            entity,
            after={"rows": len(rows), "filters": {k: str(v) for k, v in filters.items() if v}},
        )
    stamp = datetime.now(csv_export.TASHKENT).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        csv_export.render(headers, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{entity}-{stamp}.csv"'},
    )


async def _names(container: ContainerDep, ids: Iterable[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    async with container.session_factory() as session:
        result = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
        return {user_id: name for user_id, name in result}  # noqa: C416 — Row, не кортеж


@router.get("/leads.csv", response_class=StreamingResponse)
async def export_leads(
    who: Exporter,
    container: ContainerDep,
    stage: str | None = None,
    owner: str | None = Query(default=None, pattern=r"^(me|none|\d+)$"),
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    language: str | None = Query(default=None, pattern="^(ru|uz|en)$"),
    q: Annotated[str | None, Query(max_length=100)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> StreamingResponse:
    """Лиды с фильтрами экрана «Лиды» (до 10 000 строк), CSV для Excel."""
    flt = crm.LeadFilter(stage, owner, min_score, language, q, created_from, created_to)
    leads: list[Lead] = []
    async with container.session_factory() as session:
        while len(leads) < MAX_ROWS:
            page, _ = await crm.list_leads(session, flt, who.user_id, _PAGE, len(leads), "created")
            leads.extend(page)
            if len(page) < _PAGE:
                break
        names = await crm.user_names(session, leads)
    rows: list[Sequence[csv_export.Cell]] = [
        (
            lead.id,
            lead.display_name,
            lead.language,
            STAGE.get(lead.stage, lead.stage),
            lead.score,
            names.get(lead.assigned_user_id) if lead.assigned_user_id else None,
            lead.client_id,
            lead.need_summary,
            list(lead.product_interest or []),
            lead.last_lead_msg_at,
            lead.created_at,
        )
        for lead in leads[:MAX_ROWS]
    ]
    filters = {"stage": stage, "owner": owner, "min_score": min_score, "language": language, "q": q}
    return await _csv(who, container, "leads", LEAD_HEADERS, rows, filters)


@router.get("/clients.csv", response_class=StreamingResponse)
async def export_clients(
    who: Exporter, container: ContainerDep, q: Annotated[str | None, Query(max_length=100)] = None
) -> StreamingResponse:
    """Клиенты (как в списке «Клиенты», до 10 000 строк), CSV для Excel."""
    async with container.session_factory() as session:
        found = await clients_repo.list_with_stats(session, q, MAX_ROWS)
    names = await _names(container, (c.owner_user_id for c, _, _ in found))
    rows: list[Sequence[csv_export.Cell]] = [
        (
            c.id,
            c.name,
            c.inn,
            c.segment,
            names.get(c.owner_user_id) if c.owner_user_id else None,
            c.is_active,
            open_deals,
            last,
            c.created_at,
        )
        for c, open_deals, last in found
    ]
    return await _csv(who, container, "clients", CLIENT_HEADERS, rows, {"q": q})


@router.get("/deals.csv", response_class=StreamingResponse)
async def export_deals(
    who: Exporter,
    container: ContainerDep,
    stage: DealStageName | None = None,
    owner_user_id: int | None = None,
    client_id: int | None = None,
    closed_from: date | None = None,
    closed_to: date | None = None,
) -> StreamingResponse:
    """Сделки с фильтрами экрана «Сделки» (до 10 000 строк), CSV для Excel."""
    stmt = filtered(stage, owner_user_id, client_id, closed_from, closed_to).limit(MAX_ROWS)
    async with container.session_factory() as session:
        deals = await deal_rows(session, stmt)
    rows: list[Sequence[csv_export.Cell]] = [
        (
            d.id,
            d.title,
            d.client_name,
            d.product_key,
            d.amount,
            d.currency,
            DEAL_STAGE.get(d.stage, d.stage),
            d.expected_close_date,
            d.closed_at,
            d.lost_reason,
            d.owner_name,
            d.created_at,
        )
        for d in deals
    ]
    filters = {
        "stage": stage,
        "owner_user_id": owner_user_id,
        "client_id": client_id,
        "closed_from": closed_from,
        "closed_to": closed_to,
    }
    return await _csv(who, container, "deals", DEAL_HEADERS, rows, filters)
