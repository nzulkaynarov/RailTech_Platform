"""Что делать со строкой предметной области, когда зависшая задача «повтор опасен» снята (ЗАВИС-1).

Снятие переводит в `failed` только задание очереди. Если задача заранее записала в предметной строке
«в очереди» или «уже напомнили», экран продолжал бы это говорить. Для каждой задачи `once` здесь
либо хук (строка получает правдивый статус), либо запись в `NO_DOMAIN_ROW` с причиной, почему строка
застрять не может. Тест требует одно из двух для каждой такой задачи: новая задача без решения
не пройдёт.
"""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.email import EmailLog
from app.models.leads import Conversation, Lead, Message
from app.models.notices import ClientNotice
from app.models.qualification import Escalation
from app.services.client_notices import NOTICE_REF_KIND, WEB_CONFIRMATION

Sessions = async_sessionmaker[AsyncSession]
# (сессии, аргументы задачи, когда она стартовала — None, если неизвестно)
Hook = Callable[[Sessions, Mapping[str, Any], datetime | None], Awaitable[None]]

INTERRUPTED: Final = "interrupted"  # коды причин — `domain/notice_errors.ERRORS`
UNCONFIRMED: Final = "delivery_unconfirmed"


async def fail_client_notice(
    sessions: Sessions, kwargs: Mapping[str, Any], started_at: datetime | None = None
) -> None:
    """Сообщение клиенту «в очереди», доставка которого прервана: статус по фактам, без догадок.

    - письмо уже есть в журнале (связь `ref` пишется вместе со строкой) — его статус ведёт почтовая
      очередь, сообщение остаётся «в очереди» и привязывается к письму;
    - сообщение бота записано в переписку после отправки в Telegram — «отправлено»;
    - письма нет, канал письмо — ничего не ушло: «не отправлено», можно повторить;
    - канал Telegram, следов нет — между отправкой и записью следа задачу могли остановить, узнать
      нельзя: «не удалось подтвердить» без призыва повторить (второе сообщение клиенту хуже).
    """
    notice_id = int(kwargs["notice_id"])
    async with sessions() as session, session.begin():
        notice = await session.get(ClientNotice, notice_id, with_for_update=True)
        if notice is None or notice.status != "queued":
            return
        if notice.email_log_id is None:
            logged = await session.scalar(
                select(EmailLog.id).where(
                    EmailLog.ref_kind == NOTICE_REF_KIND, EmailLog.ref_id == str(notice_id)
                )
            )
            if logged is not None:
                notice.channel, notice.email_log_id = "email", logged
                return
        else:
            return
        if notice.channel != "telegram":
            notice.status, notice.error = "failed", INTERRUPTED
            return
        message = await _confirmation_message_at(session, notice)
        if message is not None:
            notice.status, notice.sent_at, notice.error = "sent", message, None
        else:
            notice.status, notice.error = "failed", UNCONFIRMED


async def _confirmation_message_at(session: AsyncSession, notice: ClientNotice) -> datetime | None:
    """Когда бот записал подтверждение в переписку лида (после этого уведомления); иначе None."""
    if notice.lead_id is None:
        return None
    return await session.scalar(
        select(func.min(Message.created_at))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.lead_id == notice.lead_id,
            Message.role == "bot",
            Message.meta["notice"].astext == WEB_CONFIRMATION,
            Message.created_at >= notice.created_at,
        )
    )


def _set_by_this_run(mark: datetime | None, started_at: datetime | None) -> bool:
    """Отметку поставила прерванная задача: она не раньше старта. Старт неизвестен или отметка
    старше — её поставил другой проход (периодический), её не трогаем."""
    return mark is not None and started_at is not None and mark >= started_at


async def reopen_web_lead_reminder(
    sessions: Sessions, kwargs: Mapping[str, Any], started_at: datetime | None = None
) -> None:
    """Отметка «о просрочке напомнили» ставится до отправки: снимаем, и периодический проход
    `web_lead_sla_sweep` напомнит снова (пока запрос никто не взял)."""
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, int(kwargs["lead_id"]), with_for_update=True)
        if (
            lead is not None
            and lead.assigned_user_id is None
            and _set_by_this_run(lead.first_response_notified_at, started_at)
        ):
            lead.first_response_notified_at = None


async def reopen_escalation_reminder(
    sessions: Sessions, kwargs: Mapping[str, Any], started_at: datetime | None = None
) -> None:
    """Отметка «срок реакции истёк, напомнили» ставится до отправки: снимаем и ставим проверку
    заново (отметка защищает от второго напоминания, пока эскалацию не забрали)."""
    escalation_id = int(kwargs["escalation_id"])
    async with sessions() as session, session.begin():
        row = await session.get(Escalation, escalation_id, with_for_update=True)
        if (
            row is None
            or row.status != "open"
            or not _set_by_this_run(row.sla_notified_at, started_at)
        ):
            return
        row.sla_notified_at = None
    from app.tasks.notify import escalation_sla_check

    await escalation_sla_check.defer_async(escalation_id=escalation_id)


HOOKS: Final[dict[str, Hook]] = {
    "deliver_client_notice": fail_client_notice,
    "web_lead_sla_check": reopen_web_lead_reminder,
    "escalation_sla_check": reopen_escalation_reminder,
}

# Задачи `once` без предметной строки, которая могла бы остаться с ложным статусом.
NO_DOMAIN_ROW: Final[dict[str, str]] = {
    "send_email": "строка остаётся `queued`, `email_queue_sweep` отправит её снова: статус правдив",
    "notify_web_lead": "только сообщение менеджерам, статуса не пишет",
    "notify_lead_message": "отметка времени пишется после отправки, до неё строка не меняется",
    "escalation_reminder": "только напоминание в канал, статус эскалации не меняет",
    "lead_handed_over": "передача уже записана действием пользователя; задача лишь уведомляет",
    "refresh_chat_menu": "только меню чата Telegram, статуса нет",
    "sync_escalation_post": "обновляет карточку в канале, статус эскалации не меняет",
    "qualify_lead": "`qualifier_runs` пишется после ответа модели; новое сообщение ставит заново",
}
