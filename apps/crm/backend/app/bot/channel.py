"""Кнопка «Забрать» в канале команды (SPEC §9.1): те же правила, что «Забрать» в CRM.

Кнопка несёт id передачи (`take:e<id>`): нажатие на устаревшую карточку (передача уже
забрана/закрыта, или старая кнопка `take:<id лида>`) отвечает «Карточка устарела» и обновляет
пост. Лида, которого ведёт другой сотрудник, кнопка не перехватывает даже у админа —
передача только в CRM («Передать коллеге»).
"""

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import DomainError
from app.domain.stages import OwnerMode
from app.models.auth import User
from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import platform_roles as platform_roles_repo
from app.repositories import users as users_repo
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services import channel_texts as tx
from app.services.channel_card import TAKE_PREFIX, parse_take
from app.services.leads import LeadService

logger = structlog.get_logger(__name__)
router = Router(name="team-channel")
TAKEABLE = ("open", "snoozed")


@router.callback_query(F.data.startswith(TAKE_PREFIX))
async def on_take(
    query: CallbackQuery,
    sessions: async_sessionmaker[AsyncSession],
    leads: LeadService,
    rbac: Rbac,
) -> None:
    parsed = parse_take(query.data or "")
    if parsed is None:
        await query.answer()
        return
    async with sessions() as session:
        escalation = await _escalation(session, *parsed)
        user = await users_repo.by_tg_user_id(session, query.from_user.id)
        roles = await users_repo.roles_of(session, user.id) if user else []
        role_ids = await platform_roles_repo.rbac_identity(session, user.id) if user else ()
        holder = await _holder(session, escalation.lead_id, user) if escalation else None
    if escalation is None or parsed[0] == "lead" or escalation.status not in TAKEABLE:
        await query.answer(tx.STALE_CARD, show_alert=True)
        if escalation is not None:
            await _resync(escalation.id)
        return
    if user is None:
        await query.answer(tx.NOT_LINKED.format(tg_id=query.from_user.id), show_alert=True)
        return
    principal = Principal(
        user.id,
        user.full_name,
        tuple(roles),
        user.must_change_password,
        platform_role_ids=role_ids,
    )
    if principal.must_change_password:
        await query.answer(tx.TEMPORARY_CREDENTIALS_HINT, show_alert=True)
        return
    if not rbac.allowed(principal.rbac_roles, "leads", "take", principal.platform_role_ids):
        await query.answer(tx.NO_RIGHTS, show_alert=True)
        return
    if holder is not None:
        await query.answer(tx.HELD_BY_OTHER.format(name=holder), show_alert=True)
        return
    try:
        await leads.take(principal, escalation.lead_id)
    except DomainError as exc:
        logger.info("channel_take_rejected", lead_id=escalation.lead_id, code=exc.code)
        await query.answer(_rejected(exc), show_alert=True)
        return
    await query.answer(tx.TAKEN)


async def _escalation(session: AsyncSession, kind: str, ident: int) -> Escalation | None:
    if kind == "escalation":
        return await session.get(Escalation, ident)
    # Старая кнопка с id лида: его открытая передача (чтобы обновить карточку).
    stmt = (
        select(Escalation)
        .where(Escalation.lead_id == ident, Escalation.status.in_(TAKEABLE))
        .order_by(Escalation.id.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def _holder(session: AsyncSession, lead_id: int, user: User | None) -> str | None:
    """Имя другого сотрудника, который уже ведёт лида; None — лида можно забрать."""
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.owner_mode != OwnerMode.HUMAN or lead.assigned_user_id is None:
        return None
    if user is not None and lead.assigned_user_id == user.id:
        return None
    holder = await session.get(User, lead.assigned_user_id)
    return holder.full_name if holder else None


async def _resync(escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    try:
        await enqueue_escalation(escalation_id, new=False)
    except Exception as exc:  # noqa: BLE001 — очередь недоступна; карточку обновит следующий sync
        logger.warning("channel_resync_failed", escalation_id=escalation_id, error=repr(exc))


def _rejected(exc: DomainError) -> str:
    """Почему «Забрать» не сработало; неизвестная ошибка — не «нет прав», а «откройте CRM»."""
    name = exc.details.get("assigned_user_name")
    if exc.details.get("reason") == "lead_taken" and isinstance(name, str) and name:
        return tx.TAKEN_BY_OTHER.format(name=name)
    return tx.REJECTED.get(exc.code, tx.TAKE_FAILED)
