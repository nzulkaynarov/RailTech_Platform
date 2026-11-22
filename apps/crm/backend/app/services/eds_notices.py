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
# v2 (задача «Н», 2026-11-13): номер документа с обозначением из настроек нумерации; данные те же.
NOTICE_TYPE_V2: Final = "uz.railtech.eds.notice.requested.v2"
# SIGN-2 (ADR-0024 п. 1): полномочие подписи скоро истекает — тот же путь доставки, своя схема.
SIGNING_EXPIRING_TYPE: Final = "uz.railtech.eds.signing_authority.expiring.v1"
SIGNING_EXPIRING_KIND: Final = "signing_authority_expiring"
# СЦ-9: уведомления по документам без входящего письма (служебка, подпись письма) — тот же путь.
DOCUMENT_NOTICE_TYPE: Final = "uz.railtech.eds.document.notice_requested.v1"
# ГЛ-2: новые виды (задачи «Главной», КП, резолюция, шаги маршрута, подпись, виза, доработка) — v2.
DOCUMENT_NOTICE_TYPE_V2: Final = "uz.railtech.eds.document.notice_requested.v2"
# «Подписать некому» ведёт держателя права в Настройки, а не к документу, которого он не видит.
_SETTINGS_KIND: Final = "letter_signer_missing"
# Вкладка колокольчика: от сотрудника ждут действия — «Решения»; остальное — «Система».
_DECISIONS: Final = frozenset(
    {
        "instruction_assigned",
        "instruction_reminder",
        "instruction_overdue",
        "extension_requested",
        "acquaint_requested",
        "letter_sign_requested",
        "letter_signer_missing",
        "approve_quote",
        "resolve_letter",
        "approve_memo",
        "pay_memo",
        "sign_commercial",
        "visa_commercial",
        "rework_document",
    }
)
# ГЛ-2: Telegram — только решения (подписать, согласовать, резолюция, оплата, виза):
# их переключатель `notify_decisions`. Прочие задачи и итоги — `notify_tasks` (по умолчанию
# выключено); «Доработать» — только колокольчик.
_TELEGRAM_DECISIONS: Final = frozenset(
    {
        "letter_sign_requested",
        "letter_signer_missing",
        "extension_requested",
        "approve_quote",
        "resolve_letter",
        "approve_memo",
        "pay_memo",
        "sign_commercial",
        "visa_commercial",
        SIGNING_EXPIRING_KIND,
    }
)
_BELL_ONLY: Final = frozenset({"rework_document"})


def tab_of(kind: str) -> str:
    return "decisions" if kind in _DECISIONS else "system"


def telegram_class(kind: str) -> str | None:
    """Чей переключатель ведает Telegram: `decisions`, `tasks` или `None` (только колокольчик)."""
    if kind in _BELL_ONLY:
        return None
    return "decisions" if kind in _TELEGRAM_DECISIONS else "tasks"


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

    def _signing_link(self) -> str | None:
        """Страница Настроек «Права подписи»."""
        return None if self._platform_url is None else f"{self._platform_url}/admin/signing"

    def _approval_link(self, approval: dict[str, Any]) -> str | None:
        """КП — вкладка «Одобрение» черновика; подпись документа — блок «Подписи» в «Задачах»."""
        if self._platform_url is None:
            return None
        if approval.get("template") == "quote":
            number = quote(str(approval["number"]), safe="")
            return f"{self._platform_url}/eds/drafts/{number}?panel=open&tab=approve"
        route = quote(str(approval["eds_approval_id"]), safe="")
        return f"{self._platform_url}/dashboard/queue?signing={route}"

    def _link(self, letter_id: str, document_id: str | None = None) -> str | None:
        """Рабочий экран письма по UUID: реестра (поиск по номеру) у исполнителя может не быть.
        Ответ на письмо (EDS-REPLY-1, `document`) — карточка исходящего."""
        if self._platform_url is None:
            return None
        if document_id is not None:
            doc = quote(document_id, safe="")
            return f"{self._platform_url}/eds/documents?doc={doc}&panel=open"
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

    @staticmethod
    async def _telegram_recipients(
        session: AsyncSession, recipients: Sequence[int], kind: str
    ) -> list[int]:
        """Кому из получателей колокольчика писать в Telegram: по переключателю в профиле."""
        which = telegram_class(kind)
        if which is None or not recipients:
            return []
        flag = User.notify_decisions if which == "decisions" else User.notify_tasks
        rows = await session.scalars(
            select(User.id).where(User.id.in_(list(recipients)), flag.is_(True))
        )
        wanted = set(rows.all())
        return [uid for uid in recipients if uid in wanted]

    async def _telegram(
        self,
        session: AsyncSession,
        event: Event,
        recipients: Sequence[int],
        kind: str,
        text: str,
    ) -> None:
        people = await self._telegram_recipients(session, recipients, kind)
        if people:
            self._notices.add(
                session,
                str(event.id),
                [{"kind": "staff", "user_id": uid, "text": text} for uid in people],
            )

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
        document = data.get("document")
        document_id = str(document["eds_document_id"]) if isinstance(document, dict) else None
        object_number = (
            str(document.get("number") or number) if isinstance(document, dict) else number
        )
        staff_notifications.add_in(
            session,
            recipients,
            kind=f"eds.{kind}"[:40],
            tab=tab_of(kind),
            title=title,
            subtitle=subtitle,
            object_kind="document" if document_id else "letter",
            object_id=document_id or str(letter["eds_letter_id"]),
            object_number=object_number,
        )
        text = telegram_text(title, subtitle, self._link(str(letter["eds_letter_id"]), document_id))
        await self._telegram(session, event, recipients, kind, text)
        logger.info(
            "eds_notice_accepted",
            kind=kind,
            number=number,
            notice_key=data.get("notice_key"),
            recipients=len(recipients),
            skipped=skipped,
        )
        return len(recipients)

    async def accept_signing_expiring(self, session: AsyncSession, event: Event) -> int:
        """Окончание полномочия подписи: колокольчик («Решения», без объекта) и Telegram."""
        data: dict[str, Any] = dict(event.data)
        title = str(data["title"])
        subtitle = data.get("subtitle")
        subtitle = str(subtitle) if subtitle else None
        recipients = await self._active(session, data.get("recipients") or [])
        if not recipients:
            logger.info("eds_signing_notice_no_recipients", notice_key=data.get("notice_key"))
            return 0
        staff_notifications.add_in(
            session,
            recipients,
            kind=f"eds.{SIGNING_EXPIRING_KIND}"[:40],
            tab="decisions",
            title=title,
            subtitle=subtitle,
        )
        text = telegram_text(title, subtitle, self._signing_link())
        await self._telegram(session, event, recipients, SIGNING_EXPIRING_KIND, text)
        logger.info(
            "eds_signing_notice_accepted",
            notice_key=data.get("notice_key"),
            recipients=len(recipients),
        )
        return len(recipients)

    async def accept_document(self, session: AsyncSession, event: Event) -> int:
        """Уведомление по документу EDS (СЦ-9): колокольчик с карточкой и Telegram со ссылкой."""
        data: dict[str, Any] = dict(event.data)
        kind = str(data["kind"])
        title = str(data["title"])
        subtitle = data.get("subtitle")
        subtitle = str(subtitle) if subtitle else None
        recipients = await self._active(session, data.get("recipients") or [])
        if not recipients:
            logger.info(
                "eds_document_notice_no_recipients", kind=kind, notice_key=data.get("notice_key")
            )
            return 0
        to_settings = kind == _SETTINGS_KIND
        obj_kind: str | None
        obj_id: str | None
        label: str | None
        if isinstance(data.get("document"), dict):
            document: dict[str, Any] = dict(data["document"])
            obj_kind, obj_id = "document", str(document["eds_document_id"])
            # Черновик письма без номера: подписью в колокольчике служит тема (поле 40 знаков).
            label = str(document.get("number") or document.get("subject") or "")[:40] or None
            link = self._link("", obj_id)
        elif isinstance(data.get("letter"), dict):  # ГЛ-2: входящее письмо ждёт резолюции
            letter: dict[str, Any] = dict(data["letter"])
            obj_kind, obj_id, label = "letter", str(letter["eds_letter_id"]), str(letter["number"])
            link = self._link(obj_id)
        else:  # ГЛ-2: КП или коммерческий документ — маршрут без документа EDS
            approval: dict[str, Any] = dict(data["approval"])
            obj_kind, obj_id = "approval", str(approval["eds_approval_id"])
            label = str(approval["number"])[:40]
            link = self._approval_link(approval)
        if to_settings:
            obj_kind, obj_id, label, link = None, None, None, self._signing_link()
        staff_notifications.add_in(
            session,
            recipients,
            kind=f"eds.{kind}"[:40],
            tab=tab_of(kind),
            title=title,
            subtitle=subtitle,
            object_kind=obj_kind,
            object_id=obj_id,
            object_number=label,
        )
        text = telegram_text(title, subtitle, link)
        await self._telegram(session, event, recipients, kind, text)
        logger.info(
            "eds_document_notice_accepted",
            kind=kind,
            notice_key=data.get("notice_key"),
            recipients=len(recipients),
        )
        return len(recipients)
