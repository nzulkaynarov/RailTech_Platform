"""Уведомления сотрудникам по поручениям входящих писем EDS (P8b, SPEC-v3 §3.2a п. 2–5).

EDS сама сотрудникам не пишет: текст (RU) готовит EDS и публикует
`uz.railtech.eds.notice.requested.v1`; CRM доставляет его теми же путями, что и свои уведомления:

* строка колокольчика каждому получателю (`staff_notifications`, лента `crm:<id>` Платформы;
  объект — письмо `letter`, адрес рабочего экрана строит BFF) — в транзакции записи inbox;
* сообщение в Telegram тем, у кого он привязан (элементы `staff` в `erp_event_notices`, отправка —
  после коммита обработки, как сообщения сотрудникам по событиям ERP; досылает сборщик).

Повтор доставки того же события — один эффект (inbox шины). Получатель, которого нет в CRM или
который отключён, пропускается без ошибки: колокольчик и Telegram — подсказка, не условие процесса.
"""

from collections.abc import Sequence
from typing import Any, Final
from urllib.parse import quote

import structlog
from rt_bus import Event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.notices import ErpEventNotices
from app.models.auth import User
from app.services import staff_notifications

logger = structlog.get_logger(__name__)

NOTICE_TYPE: Final = "uz.railtech.eds.notice.requested.v1"
# Вкладка колокольчика: от сотрудника ждут действия — «Решения»; остальное — «Система».
_DECISIONS: Final = frozenset(
    {
        "instruction_assigned",
        "instruction_reminder",
        "instruction_overdue",
        "extension_requested",
        "acquaint_requested",
    }
)


def tab_of(kind: str) -> str:
    return "decisions" if kind in _DECISIONS else "system"


def telegram_text(title: str, subtitle: str | None, link: str | None) -> str:
    """Сообщение бота: заголовок, вторая строка и ссылка на рабочий экран письма."""
    lines = [title]
    if subtitle:
        lines.append(subtitle)
    if link:
        lines.append(link)
    return "\n".join(lines)


class EdsNoticeService:
    def __init__(self, notices: ErpEventNotices, platform_url: str | None = None) -> None:
        self._notices = notices
        self._platform_url = (platform_url or "").rstrip("/") or None

    def _link(self, letter_id: str) -> str | None:
        """Рабочий экран письма по UUID: реестра (поиск по номеру) у исполнителя может не быть."""
        if self._platform_url is None:
            return None
        return f"{self._platform_url}/eds/tasks/{quote(letter_id, safe='')}"

    @staticmethod
    async def _active(session: AsyncSession, ids: Sequence[int]) -> list[int]:
        """Получатели, которые есть в CRM и активны, — в порядке события, без повторов."""
        wanted = list(dict.fromkeys(int(i) for i in ids))
        if not wanted:
            return []
        rows = await session.scalars(
            select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))
        )
        found = set(rows.all())
        return [uid for uid in wanted if uid in found]

    async def accept(self, session: AsyncSession, event: Event) -> int:
        """Колокольчик и Telegram получателям (в транзакции inbox). Возвращает число получателей."""
        data: dict[str, Any] = dict(event.data)
        kind = str(data["kind"])
        letter: dict[str, Any] = dict(data["letter"])
        number = str(letter["number"])
        title = str(data["title"])
        subtitle = data.get("subtitle")
        subtitle = str(subtitle) if subtitle else None
        recipients = await self._active(session, data.get("recipients") or [])
        skipped = len(set(data.get("recipients") or [])) - len(recipients)
        if not recipients:
            logger.info("eds_notice_no_recipients", kind=kind, number=number, skipped=skipped)
            return 0
        staff_notifications.add_in(
            session,
            recipients,
            kind=f"eds.{kind}"[:40],
            tab=tab_of(kind),
            title=title,
            subtitle=subtitle,
            object_kind="letter",
            object_id=str(letter["eds_letter_id"]),
            object_number=number,
        )
        text = telegram_text(title, subtitle, self._link(str(letter["eds_letter_id"])))
        self._notices.add(
            session,
            str(event.id),
            [{"kind": "staff", "user_id": uid, "text": text} for uid in recipients],
        )
        logger.info(
            "eds_notice_accepted",
            kind=kind,
            number=number,
            notice_key=data.get("notice_key"),
            recipients=len(recipients),
            skipped=skipped,
        )
        return len(recipients)
