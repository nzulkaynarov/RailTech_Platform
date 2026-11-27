"""Что делать со строкой предметной области, когда зависшая задача «повтор опасен» снята (ЗАВИС-1).

Снятие переводит в `failed` только задание очереди. Если задача заранее записала в предметной строке
«в очереди» или «уже напомнили», экран продолжал бы это говорить. Для каждой задачи `once` здесь
либо хук (строка получает правдивый статус), либо запись в `NO_DOMAIN_ROW` с причиной, почему строка
застрять не может. Тест требует одно из двух для каждой такой задачи: новая задача без решения
не пройдёт.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.leads import Lead
from app.models.notices import ClientNotice
from app.models.qualification import Escalation

Sessions = async_sessionmaker[AsyncSession]
Hook = Callable[[Sessions, Mapping[str, Any]], Awaitable[None]]

INTERRUPTED: Final = "interrupted"  # код причины в `domain/notice_errors.ERRORS`


async def fail_client_notice(sessions: Sessions, kwargs: Mapping[str, Any]) -> None:
    """Сообщение клиенту «в очереди», которое уже не уйдёт: «не отправлено» с причиной.

    Письмо, уже переданное почтовой очереди (`email_log_id`), не трогаем: его статус ведёт она.
    """
    async with sessions() as session, session.begin():
        notice = await session.get(ClientNotice, int(kwargs["notice_id"]), with_for_update=True)
        if notice is None or notice.status != "queued" or notice.email_log_id is not None:
            return
        notice.status, notice.error = "failed", INTERRUPTED


async def reopen_web_lead_reminder(sessions: Sessions, kwargs: Mapping[str, Any]) -> None:
    """Отметка «о просрочке напомнили» ставится до отправки: снимаем, и периодический проход
    `web_lead_sla_sweep` напомнит снова (пока запрос никто не взял)."""
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, int(kwargs["lead_id"]), with_for_update=True)
        if lead is not None and lead.assigned_user_id is None:
            lead.first_response_notified_at = None


async def reopen_escalation_reminder(sessions: Sessions, kwargs: Mapping[str, Any]) -> None:
    """Отметка «срок реакции истёк, напомнили» ставится до отправки: снимаем и ставим проверку
    заново (отметка защищает от второго напоминания, пока эскалацию не забрали)."""
    escalation_id = int(kwargs["escalation_id"])
    async with sessions() as session, session.begin():
        row = await session.get(Escalation, escalation_id, with_for_update=True)
        if row is None or row.status != "open" or row.sla_notified_at is None:
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
