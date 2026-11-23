"""Проекция реквизитов компании ERP у клиента CRM (ADR-0028 п. 6, СУЩ-2.7).

Владелец названия, ИНН, страны и рег. номера компании-контрагента — ERP: при их изменении ERP
публикует снимок `uz.railtech.erp.company.updated.v1`, CRM переписывает эти поля у клиентов со
ссылкой `erp_company_id` и публикует `client.updated`, чтобы проекции клиента у других систем не
отстали. Порядок — по `company.updated_at`: более старый снимок не применяется
(`clients.erp_requisites_at`), повтор того же — без изменений. Клиента с такой ссылкой нет — не
ошибка (компания ещё не связана с CRM). Сегмент, ответственный и прочее своё CRM не трогает.
"""

from datetime import datetime
from typing import Final

import structlog
from pydantic import ValidationError
from rt_bus import Event
from rt_contracts.events.erp import Company as CompanySnapshot
from rt_contracts.events.erp import CompanyUpdatedV1
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.models.clients import Client
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

COMPANY_UPDATED: Final = "uz.railtech.erp.company.updated.v1"


class CompanySnapshotError(Exception):
    """Снимок не читается: шина повторит обработку, затем пометит запись `failed`."""


def _apply_do_not_work(client: Client, snapshot: CompanySnapshot) -> None:
    """Х-8: отметка «Не работать» — факты из снимка; поля нет (прежний издатель) — не меняется."""
    if "do_not_work" not in snapshot.model_fields_set:
        return
    mark = snapshot.do_not_work
    client.do_not_work_reason = mark.reason.strip()[:1000] if mark else None
    client.do_not_work_by = (mark.set_by or "").strip()[:255] or None if mark else None
    client.do_not_work_at = mark.set_at if mark else None
    client.do_not_work_until = mark.until if mark else None


async def apply(session: AsyncSession, event: Event) -> int:
    """Применить снимок в транзакции inbox; возвращает число изменённых клиентов."""
    try:
        data = CompanyUpdatedV1.model_validate(event.data)
    except ValidationError as exc:
        raise CompanySnapshotError(f"invalid {event.type}: {exc.error_count()} errors") from None
    snapshot = data.company
    at: datetime = snapshot.updated_at
    clients = (
        await session.scalars(
            select(Client).where(Client.erp_company_id == data.erp_company_id).with_for_update()
        )
    ).all()
    changed_total = 0
    for client in clients:
        if client.erp_requisites_at is not None and client.erp_requisites_at >= at:
            logger.info(
                "company_snapshot_stale",
                event_id=event.id,
                client_id=client.id,
                applied_at=client.erp_requisites_at.isoformat(),
            )
            continue
        wanted = {
            "name": snapshot.name.strip()[:255],
            "inn": (snapshot.inn or "").strip()[:32] or None,
            "country": snapshot.country,
            "registration_number": (snapshot.registration_number or "").strip()[:64] or None,
        }
        changed = [field for field, value in wanted.items() if getattr(client, field) != value]
        for field in changed:
            setattr(client, field, wanted[field])
        _apply_do_not_work(client, snapshot)
        client.erp_requisites_at = at
        if changed:
            changed_total += 1
            await session.flush()
            await bus_events.client_updated(session, client, Actor.system(), changed)
    logger.info(
        "company_snapshot_applied",
        event_id=event.id,
        erp_company_id=data.erp_company_id,
        clients=len(clients),
        changed=changed_total,
    )
    return changed_total
