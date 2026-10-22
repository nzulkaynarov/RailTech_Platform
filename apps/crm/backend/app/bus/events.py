"""Публикация событий CRM на шину из сервисного слоя (CONTRACTS §9, правило кода «события только
через rt_bus»).

Каждая функция вызывается внутри транзакции изменения (`async with session.begin()`): строка outbox
пишется той же транзакцией, откат изменения откатывает и событие. Вне транзакции шина бросает
`NotInTransactionError`; ошибка схемы (`EventValidationError`) тоже не глотается — изменение
откатывается, а не уходит без события. Данные — снимок сущности (`app.bus.snapshots`), телефоны и
почта нормализованы до публикации.

Типы: `uz.railtech.crm.{client,contact,lead}.*.v1`, `uz.railtech.identity.user.*.v1`.
"""

from collections.abc import Iterable
from typing import Any

from rt_bus.errors import NotInTransactionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import snapshots
from app.bus.runtime import get_bus
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.leads import Lead
from app.security.audit import Actor

CLIENT_CREATED = "uz.railtech.crm.client.created.v1"
CLIENT_UPDATED = "uz.railtech.crm.client.updated.v1"
CONTACT_CREATED = "uz.railtech.crm.contact.created.v1"
CONTACT_UPDATED = "uz.railtech.crm.contact.updated.v1"
CONTACT_DELETED = "uz.railtech.crm.contact.deleted.v1"
LEAD_CREATED = "uz.railtech.crm.lead.created.v1"
LEAD_UPDATED = "uz.railtech.crm.lead.updated.v1"
LEAD_STAGE_CHANGED = "uz.railtech.crm.lead.stage_changed.v1"
USER_CREATED = "uz.railtech.identity.user.created.v1"
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
USER_DEACTIVATED = "uz.railtech.identity.user.deactivated.v1"


def _require_transaction(session: AsyncSession) -> None:
    """Событие — только внутри транзакции изменения. Проверка первой: построение снимка уже
    читает базу и само открыло бы транзакцию (autobegin), после чего проверка шины ничего не видит.
    """
    if not session.in_transaction():
        raise NotInTransactionError(
            "a bus event needs the transaction of the change: use `async with session.begin()`"
        )


def _internal(lead: Lead) -> bool:
    """Диалоги песочницы (тест бота админом) — не данные клиентов: на шину не уходят."""
    return lead.source == "sandbox"


def _changed(fields: Iterable[str]) -> dict[str, Any]:
    names = sorted(set(fields))
    return {"changed_fields": names} if names else {}


async def _publish(
    session: AsyncSession, event_type: str, data: dict[str, Any], subject: str
) -> None:
    await get_bus().publish(session, event_type, data, subject=subject)


async def client_created(session: AsyncSession, client: Client, actor: Actor) -> None:
    _require_transaction(session)
    data = {"client": await snapshots.client_snapshot(session, client)}
    data["actor"] = snapshots.actor_of(actor)
    await _publish(session, CLIENT_CREATED, data, f"client/{client.id}")


async def client_updated(
    session: AsyncSession, client: Client, actor: Actor, changed: Iterable[str] = ()
) -> None:
    _require_transaction(session)
    data = {
        "client": await snapshots.client_snapshot(session, client),
        **_changed(changed),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, CLIENT_UPDATED, data, f"client/{client.id}")


async def contact_created(session: AsyncSession, contact: ClientContact, actor: Actor) -> None:
    _require_transaction(session)
    data = {
        "contact": await snapshots.contact_snapshot(session, contact),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, CONTACT_CREATED, data, f"contact/{contact.id}")


async def contact_updated(session: AsyncSession, contact: ClientContact, actor: Actor) -> None:
    _require_transaction(session)
    data = {
        "contact": await snapshots.contact_snapshot(session, contact),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, CONTACT_UPDATED, data, f"contact/{contact.id}")


async def contact_deleted(
    session: AsyncSession,
    *,
    contact_id: int,
    client_id: int,
    erp_company_id: int | None,
    actor: Actor,
) -> None:
    """`deleted_at` — время базы (начало транзакции), как `updated_at` снимков: подписчик сравнивает
    их между собой, и часы приложения с часами базы смешивать нельзя.
    """
    _require_transaction(session)
    deleted_at = await snapshots.db_now(session)
    data = {
        "crm_contact_id": contact_id,
        "crm_client_id": client_id,
        "erp_company_id": erp_company_id,
        "deleted_at": snapshots.utc(deleted_at),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, CONTACT_DELETED, data, f"contact/{contact_id}")


async def lead_created(session: AsyncSession, lead: Lead, actor: Actor) -> None:
    _require_transaction(session)
    if _internal(lead):
        return
    data = {
        "lead": await snapshots.lead_snapshot(session, lead),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, LEAD_CREATED, data, f"lead/{lead.id}")


async def lead_updated(
    session: AsyncSession, lead: Lead, actor: Actor, changed: Iterable[str] = ()
) -> None:
    _require_transaction(session)
    if _internal(lead):
        return
    data = {
        "lead": await snapshots.lead_snapshot(session, lead),
        **_changed(changed),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, LEAD_UPDATED, data, f"lead/{lead.id}")


async def lead_stage_changed(
    session: AsyncSession,
    lead: Lead,
    *,
    from_stage: str,
    to_stage: str,
    actor: Actor,
    reason: str | None = None,
) -> None:
    _require_transaction(session)
    if _internal(lead):
        return
    data: dict[str, Any] = {
        "lead": await snapshots.lead_snapshot(session, lead),
        "from": from_stage,
        "to": to_stage,
    }
    text = snapshots.clip(reason, 500)
    if text is not None:
        data["reason"] = text
    data["actor"] = snapshots.actor_of(actor)
    await _publish(session, LEAD_STAGE_CHANGED, data, f"lead/{lead.id}")


async def user_created(session: AsyncSession, user: User, actor: Actor) -> None:
    _require_transaction(session)
    data = {
        "user": await snapshots.user_snapshot(session, user),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, USER_CREATED, data, f"user/{user.id}")


async def user_updated(
    session: AsyncSession, user: User, actor: Actor, changed: Iterable[str] = ()
) -> None:
    _require_transaction(session)
    data = {
        "user": await snapshots.user_snapshot(session, user),
        **_changed(changed),
        "actor": snapshots.actor_of(actor),
    }
    await _publish(session, USER_UPDATED, data, f"user/{user.id}")


async def user_deactivated(
    session: AsyncSession, user_id: int, actor: Actor, reason: str | None = None
) -> None:
    _require_transaction(session)
    data: dict[str, Any] = {"crm_user_id": user_id}
    text = snapshots.clip(reason, 500)
    if text is not None:
        data["reason"] = text
    data["actor"] = snapshots.actor_of(actor)
    await _publish(session, USER_DEACTIVATED, data, f"user/{user_id}")
