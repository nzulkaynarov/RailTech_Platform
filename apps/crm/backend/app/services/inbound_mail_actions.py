"""Действия по типу письма (MAIL-TYPES): сменить тип, «прайс загружен», передать, «подозрительное».

Основная кнопка карточки — действие по умолчанию типа (`domain/mail_types.ACTIONS`); сами действия
делает код, тип только выбирает кнопку. Каждое действие, как и прежние («лид», «архив»), берёт
письмо в работу, работает под блокировкой строки и заканчивает письмо: «Разобрано» с итогом
(`price`) или уход из «Новых» — к бухгалтеру («В работе» у него) или в «Подозрительные». Решение
человека — в журнал ИИ.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.repositories import inbound_mail_views as views
from app.repositories import mail_types as types_repo
from app.schemas import mail_types as dto
from app.security import audit
from app.security.principal import Principal
from app.services import inbound_mail_work as work
from app.services.inbound_mail_assist import record_decision

logger = structlog.get_logger(__name__)


class InboundMailActions:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def set_type(self, who: Principal, mail_id: int, type_code: str | None) -> None:
        """Человек меняет тип одним щелчком (или снимает): запись в журнал письма, ИИ и
        правило уступают.

        Письмо не берётся в работу и не закрывается: тип — метка, не действие.
        """
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            found = None
            if type_code is not None:
                found = await types_repo.get_type(session, type_code)
                if found is None:
                    raise ValidationFailedError("unknown type", field="type_code")
                if not found.active and row.type_code != type_code:
                    raise ConflictError("type is hidden", reason=Reason.MAIL_TYPE_INACTIVE)
            before = row.type_code
            row.type_code = found.code if found else None
            row.type_source = "manual" if found else None
            await audit.record(
                session,
                who.actor,
                "inbound_mail.type",
                "inbound_mail",
                row.id,
                before={"type": before},
                after={"type": row.type_code, "type_name": found.name_ru if found else "—"},
            )
        logger.info("inbound_mail_type_set", mail_id=mail_id, type=type_code)

    async def supplier_price(self, who: Principal, mail_id: int) -> None:
        """«Прайс загружен»: человек загрузил прайс или КП в каталоге (CAT-1) и закрывает письмо."""
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            await work.claim(session, row, who, now)
            work.finish(row, "price", who, now)
            await record_decision(session, row, "supplier_price", who.actor)
            await audit.record(
                session, who.actor, "inbound_mail.price", "inbound_mail", row.id, after={}
            )
        logger.info("inbound_mail_price_done", mail_id=mail_id)

    async def handover_targets(self, purpose: str = "payments") -> dto.InboundMailHandoverTargets:
        async with self._sessions() as session:
            found = await types_repo.handover_targets(session, purpose)
        return dto.InboundMailHandoverTargets(
            items=[dto.InboundMailHandoverTarget(id=i, name=n) for i, n in found]
        )

    async def handover(
        self, who: Principal, mail_id: int, user_id: int, purpose: str = "payments"
    ) -> None:
        """«Передать бухгалтеру»: письмо «В работе» у выбранного сотрудника — из «Новых» оно
        уходит, у него появляется в «Моих задачах». Адресат — только из тех, кто
        подтверждает оплату (данные ролей).
        """
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            await work.claim(session, row, who, now)
            if user_id not in {i for i, _ in await types_repo.handover_targets(session, purpose)}:
                raise ConflictError("no such colleague", reason=Reason.MAIL_NO_HANDOVER_TARGET)
            names = await views.user_names(session, [user_id])
            row.status, row.assignee_id, row.assigned_at = "in_work", user_id, now
            await record_decision(
                session,
                row,
                "to_accountant" if purpose == "payments" else "supplier_price",
                who.actor,
            )
            await audit.record(
                session,
                who.actor,
                "inbound_mail.handover",
                "inbound_mail",
                row.id,
                after={
                    "assignee_id": user_id,
                    "type_name": names.get(user_id, ""),
                    "purpose": purpose,
                },
            )
        logger.info("inbound_mail_handed_over", mail_id=mail_id, to=user_id)

    async def suspicious(self, who: Principal, mail_id: int) -> None:
        """«В „Подозрительные“»: письмо уходит из очереди во вкладку, где его можно вернуть
        («Не спам»).
        """
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await work.lock(session, mail_id)
            await work.claim(session, row, who, now)
            row.status = "spam"
            row.assignee_id = row.assigned_at = None
            row.thread_reply = False
            await record_decision(session, row, "suspicious", who.actor)
            await audit.record(
                session, who.actor, "inbound_mail.suspicious", "inbound_mail", row.id, after={}
            )
        logger.info("inbound_mail_to_spam", mail_id=mail_id)
