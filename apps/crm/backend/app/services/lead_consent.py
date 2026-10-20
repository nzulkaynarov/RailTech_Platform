"""«Согласие получено»: сотрудник отмечает согласие лида, заведённого вручную (FIX-57, D-8).

Лид из звонка, письма или рекомендации не пишет боту и согласия в боте не даст, а «Передать в
бэк-офис» без него — 422 `handoff_no_consent` (FIX-34, I-13). Право отметить — у тех, кто может
передавать в бэк-офис (`clients:write`; не ответственный за чужого лида — только админ), как
у «Передать в бэк-офис». «Правовое основание» (способ и комментарий) остаётся в аудите и в ленте
лида: кто, когда, как. Повторная отметка ничего не меняет — первое согласие и время сохраняются.
Согласие, данное лидом самим (бот, форма), не перезаписывается.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.consent import CONSENT_METHODS, MANUAL_CONSENT_VERSION
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    Reason,
    ValidationFailedError,
)
from app.domain.lead_sources import MANUAL_SOURCES
from app.repositories import events
from app.repositories import leads as leads_repo
from app.security import audit
from app.security.principal import Principal
from app.services import lead_parts

logger = structlog.get_logger(__name__)

# Подписи способов — в ленте лида (журнал для сотрудников, как «Передано коллеге» и т.п.).
_METHOD_LABELS = {
    "phone": "устно по телефону",
    "email": "письмом",
    "paper": "на бумаге",
}


class LeadConsentService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(
        self, who: Principal, lead_id: int, method: str, comment: str | None = None
    ) -> bool:
        """Отметить согласие: `True` — записано сейчас, `False` — оно уже есть (идемпотентно)."""
        if method not in CONSENT_METHODS:
            raise ValidationFailedError("unknown consent method", field="method")
        async with self._sessions() as session, session.begin():
            lead = await leads_repo.get_lead(session, lead_id, for_update=True)
            if lead is None or lead.erased_at is not None:
                raise NotFoundError("lead not found")
            if not who.is_admin and lead.assigned_user_id not in (None, who.user_id):
                raise ForbiddenError(
                    "only the lead owner or an admin can do this", reason=Reason.NOT_LEAD_OWNER
                )
            if lead.consent_given_at is not None:
                return False
            if lead.source not in MANUAL_SOURCES:
                # Лид из Telegram соглашается в боте — обход кнопки открыл бы ему диалог с ИИ.
                raise ConflictError(
                    "consent of a telegram lead is given in the bot",
                    reason=Reason.CONSENT_VIA_BOT,
                )
            moment = datetime.now(UTC)
            note = (comment or "").strip() or None
            lead.consent_given_at = moment
            lead.consent_version = MANUAL_CONSENT_VERSION
            lead.consent_method = method
            lead_parts.add_note(
                session,
                lead,
                who,
                "Согласие на обработку данных получено "
                f"{_METHOD_LABELS[method]}" + (f": {note}" if note else "."),
                visible_to_bot=False,
            )
            await audit.record(
                session,
                who.actor,
                "lead.consent_recorded",
                "lead",
                lead_id,
                before={"consent_given_at": None},
                after={
                    "consent_given_at": moment.isoformat(),
                    "consent_version": MANUAL_CONSENT_VERSION,
                    "consent_method": method,
                    "comment": note,
                },
            )
            await events.publish(session, "lead.updated", lead_id=lead_id)
        logger.info("lead_consent_recorded", lead_id=lead_id, user_id=who.user_id, method=method)
        return True
