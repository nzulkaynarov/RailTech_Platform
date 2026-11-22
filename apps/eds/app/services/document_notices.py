"""Уведомления по документам без входящего письма (СЦ-9): кто узнаёт о передаче работы, не заглядывая в журнал.

EDS сама сотрудникам не пишет: текст (RU) готовит она, событие `document.notice_requested` доставляет CRM
(колокольчик и Telegram). Публикация — в транзакции изменения документа (CONVENTIONS.md §2 п. 3); получателей нет —
события нет. Автору о собственном действии не сообщаем: решает и платит порой тот же человек.

* служебка, заявление, отчёт: решение директора (`memo_decided`) и оплата (`memo_paid`) — автору;
  возврат на доработку не дублируем: он остаётся строкой «Доработать» в «Моих задачах»;
* исходящее письмо: передан проект — подписанту (`letter_sign_requested`) или, если подписать некому, держателям
  `signing.manage` (`letter_signer_missing`); подписал другой сотрудник — автору (`letter_signed`).
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.schemas.documents import DocumentKind, DocumentStatus
from app.services import events, signing_reminders, signing_resolve
from app.services.people import load_directory

_KIND_WORD = {
    DocumentKind.MEMO.value: "Служебка",
    DocumentKind.APPLICATION.value: "Заявление",
    DocumentKind.REPORT.value: "Отчёт",
    DocumentKind.LETTER_OUT.value: "Письмо",
}
# Согласие и отказ по роду документа: «Служебка согласована», «Заявление согласовано», «Отчёт согласован».
_DECIDED = {
    DocumentKind.MEMO.value: ("согласована", "отклонена"),
    DocumentKind.APPLICATION.value: ("согласовано", "отклонено"),
    DocumentKind.REPORT.value: ("согласован", "отклонён"),
}


def _name(document: Document) -> str:
    """«Служебка MEMO-2026/014»; у документа без номера — одно слово."""
    word = _KIND_WORD.get(document.kind, "Документ")
    return f"{word} {document.number}" if document.number else word


async def _publish(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    kind: str,
    key: str,
    recipients: Iterable[int | None],
    title: str,
    subtitle: str | None,
    actor_id: int,
) -> None:
    people = list(dict.fromkeys(uid for uid in recipients if uid is not None))
    if not people:
        return
    data: dict[str, Any] = {
        "notice_key": key,
        "kind": kind,
        "recipients": people,
        "title": title[:200],
        "subtitle": subtitle[:200] if subtitle else None,
        "document": {
            "eds_document_id": str(document.id),
            "number": document.number,
            "subject": document.subject[:300],
        },
        "actor": events.actor(actor_id),
    }
    await events.publish(bus, session, "document.notice_requested", data, subject=f"document/{document.id}")


async def memo_decided(
    session: AsyncSession, bus: AsyncBus, document: Document, *, round_: int, comment: str | None, actor_id: int
) -> None:
    """Директор согласовал или отклонил: автору. Статус `paid` и `returned` сюда не попадают (оплата — `memo_paid`)."""
    words = _DECIDED.get(document.kind)
    if words is None:  # письмо и прочее: решение директора — не про автора записки
        return
    approved_word, rejected_word = words
    status = document.status
    if status == DocumentStatus.REJECTED.value:
        title, subtitle = f"{_name(document)} {rejected_word}", comment or document.subject
    elif status == DocumentStatus.TO_ACCOUNTANT.value:
        title, subtitle = f"{_name(document)} {approved_word}", f"Передана на оплату · {document.subject}"
    elif status == DocumentStatus.APPROVED.value:
        title, subtitle = f"{_name(document)} {approved_word}", document.subject
    else:
        return
    await _publish(
        session,
        bus,
        document,
        kind="memo_decided",
        key=f"document:{document.id}:r{round_}:memo_decided:{status}",
        recipients=[document.author_crm_user_id] if document.author_crm_user_id != actor_id else [],
        title=title,
        subtitle=subtitle,
        actor_id=actor_id,
    )


async def memo_paid(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    paid_on: date,
    amount: Decimal,
    currency: str,
    actor_id: int,
) -> None:
    """Оплата отмечена: автору записки."""
    await _publish(
        session,
        bus,
        document,
        kind="memo_paid",
        key=f"document:{document.id}:memo_paid",
        recipients=[document.author_crm_user_id] if document.author_crm_user_id != actor_id else [],
        title=f"{_name(document)} оплачена",
        subtitle=f"{paid_on:%d.%m.%Y} · {amount:.2f} {currency}",
        actor_id=actor_id,
    )


async def letter_handed_over(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    today: date,
    actor_id: int,
) -> None:
    """Проект письма передан: подписанту (по замещению — с пометкой «за …»); подписать некому — держателям
    `signing.manage`."""
    signer = await signing_resolve.letter_signer(session, document, today)
    directory = await load_directory(session, [document.author_crm_user_id])
    if signer is None:
        await _publish(
            session,
            bus,
            document,
            kind="letter_signer_missing",
            key=f"document:{document.id}:letter_signer_missing",
            recipients=await signing_reminders.manage_holder_ids(session),
            title="Подписать некому",
            subtitle=f"Настройки → Права подписи · {document.subject}"[:200],
            actor_id=actor_id,
        )
        return
    who = signer.signer.crm_user_id
    if who == actor_id:
        return
    behalf = "" if not signer.acting_for else " · за " + ", ".join(p.full_name for p in signer.acting_for)
    await _publish(
        session,
        bus,
        document,
        kind="letter_sign_requested",
        key=f"document:{document.id}:letter_sign_requested:{who}",
        recipients=[who],
        title="Подпишите исходящее",
        subtitle=f"{document.subject} · {directory.name(document.author_crm_user_id)}{behalf}",
        actor_id=actor_id,
    )


async def letter_signed(
    session: AsyncSession, bus: AsyncBus, document: Document, *, signer_id: int, signer_name: str
) -> None:
    """Письмо подписал другой сотрудник: автору. Ответ на входящее уже получает `reply.notify_registered`."""
    if document.in_reply_to is not None or document.author_crm_user_id == signer_id:
        return
    await _publish(
        session,
        bus,
        document,
        kind="letter_signed",
        key=f"document:{document.id}:letter_signed",
        recipients=[document.author_crm_user_id],
        title=f"{_name(document)} подписано",
        subtitle=f"{document.subject} · {signer_name}",
        actor_id=signer_id,
    )


publish_notice = _publish  # public name for the waiting reminders (ГЛ-1)

__all__ = ["letter_handed_over", "letter_signed", "memo_decided", "memo_paid"]
