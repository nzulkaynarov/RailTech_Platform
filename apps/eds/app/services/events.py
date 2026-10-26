"""Сборка и публикация событий EDS (`uz.railtech.eds.*.v1`): тела — по схемам `packages/contracts/events/eds/`.

Публикует только сервисный слой, в транзакции изменения (`AsyncBus.publish`, CONVENTIONS.md §2 п. 3):
откат — события нет. Тело проверяется библиотекой по схеме строго до записи в outbox.
"""

import uuid
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "uz.railtech.eds."


def actor(crm_user_id: int | None) -> dict[str, Any]:
    """`Actor` события: сотрудник или система EDS (обработчик шины, задача)."""
    if crm_user_id is None:
        return {"type": "system"}
    return {"type": "staff", "crm_user_id": crm_user_id}


def erp_links(
    *,
    erp_request_id: int | None,
    erp_deal_id: int | None,
    deal_number: str | None,
    crm_client_id: int | None,
    erp_company_id: int | None,
) -> dict[str, Any]:
    return {
        "erp_request_id": erp_request_id,
        "erp_deal_id": erp_deal_id,
        "deal_number": deal_number,
        "crm_client_id": crm_client_id,
        "erp_company_id": erp_company_id,
    }


async def publish(
    bus: AsyncBus, session: AsyncSession, name: str, data: dict[str, Any], *, subject: str | uuid.UUID
) -> None:
    """Событие `uz.railtech.eds.<name>.v1` в outbox транзакции `session`; `subject` — номер или id объекта."""
    await bus.publish(session, f"{PREFIX}{name}.v1", data, subject=str(subject))
