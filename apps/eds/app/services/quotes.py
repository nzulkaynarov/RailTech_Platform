"""КП на одобрение директором (EDS-03): `erp.quote.ready_for_approval` → маршрут «КП» с чек-листом.

Идемпотентно по (КП, версия): повтор события не открывает второй маршрут. Новая версия после возврата — новое событие
ERP с `version + 1` и новый круг маршрута. Снимок КП хранится в маршруте только для показа и чек-листа; коммерческого
содержания сверх снимка у EDS нет.
"""

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_snapshots import QuoteReady
from app.models import ApprovalRoute
from app.schemas.approvals import ApprovalTemplate
from app.services import approvals

log = structlog.get_logger(__name__)


async def open_for_quote(session: AsyncSession, bus: AsyncBus, data: QuoteReady) -> ApprovalRoute | None:
    """Открыть маршрут одобрения КП. При повторе — существующий; `None` — событие устарело (есть версия новее)."""
    quote = data.payload
    same_quote = ApprovalRoute.erp_quote_id == quote.erp_quote_id
    existing = (
        await session.execute(select(ApprovalRoute).where(same_quote, ApprovalRoute.quote_version == quote.version))
    ).scalar_one_or_none()
    if existing is not None:
        log.info("quote_route_exists", quote=quote.number, version=quote.version)
        return existing
    newest = (await session.execute(select(func.max(ApprovalRoute.quote_version)).where(same_quote))).scalar_one()
    if newest is not None and newest > quote.version:
        log.warning("quote_event_stale", quote=quote.number, version=quote.version, newest=newest)
        return None
    rounds = (await session.execute(select(func.count()).select_from(ApprovalRoute).where(same_quote))).scalar_one()
    fields = {
        "erp_quote_id": quote.erp_quote_id,
        "quote_number": quote.number,
        "quote_version": quote.version,
        "erp_deal_id": data.deal.erp_deal_id,
        "deal_number": data.deal.number,
        "crm_client_id": data.crm_client_id,
        "erp_company_id": data.erp_company_id,
        "eds_letter_id": quote.eds_letter_id,
        "quote_snapshot": quote.model_dump(mode="json", exclude={"eds_letter_id"}),
    }
    return await approvals.open_route(
        session,
        bus,
        template=ApprovalTemplate.QUOTE,
        title=f"{quote.number} v{quote.version} · {data.deal.number}",
        steps=approvals.steps_for(ApprovalTemplate.QUOTE),
        actor_id=None,
        round_no=int(rounds) + 1,
        fields=fields,
    )
