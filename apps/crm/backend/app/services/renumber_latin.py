"""Одноразовая перенумерация в латиницу (СЦ-5): копии номеров в таблицах CRM по общему маппингу.

Маппинг — плоский JSON `{"ВХ-001/26": "IN-001/26", "ЗВ-2026-002": "PRJ-2026-002", ...}`, один на все
системы. CRM меняет только свои копии: `deals.erp_number`, `inbound_mail.eds_letter_number`,
`staff_notifications.object_number` и `.title`, текст сообщений в `erp_event_notices.items`.
История (шина, журналы, отправленные письма) не трогается. Номер здесь — непрозрачная строка: ничего
не выводится из префикса, замена идёт только по ключам маппинга. Повтор безопасен: после замены
старых номеров в данных нет, второй прогон ничего не меняет.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deals import Deal
from app.models.inbound_mail import InboundMail
from app.models.integrations import ErpEventNotice
from app.models.staff_tickets import StaffNotification

# Границы номера в тексте: перед и после — не буква, цифра, `-` или `/`, чтобы `ВХ-001/26` не
# совпал внутри `ВХ-001/260`.
_EDGE_BEFORE = r"(?<![\w/-])"
_EDGE_AFTER = r"(?![\w/-])"


@dataclass(frozen=True, slots=True)
class Change:
    field: str  # `таблица.колонка`
    row_id: str
    before: str
    after: str

    def line(self) -> str:
        return f"{self.field} {self.row_id}: {_short(self.before)} → {_short(self.after)}"


def _short(text: str, limit: int = 120) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def parse_mapping(raw: str) -> dict[str, str]:
    """JSON-объект `{старый: новый}`; пустые строки, не строки и тождественные пары — ошибка."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("mapping must be a JSON object {old: new}")
    out: dict[str, str] = {}
    for old, new in data.items():
        if not isinstance(new, str) or not old.strip() or not new.strip():
            raise ValueError(f"bad mapping entry: {old!r}")
        if old == new:
            raise ValueError(f"mapping entry does not change the number: {old!r}")
        out[old] = new
    return out


def replace_numbers(text: str, mapping: Mapping[str, str]) -> str:
    """Меняет в тексте номера по маппингу за один проход (цепочки a→b→c не возникают)."""
    if not mapping or not text:
        return text
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(
        _EDGE_BEFORE + "(" + "|".join(re.escape(k) for k in keys) + ")" + _EDGE_AFTER
    )
    return pattern.sub(lambda m: mapping[m.group(1)], text)


async def plan(session: AsyncSession, mapping: Mapping[str, str]) -> list[Change]:
    """Что изменится: по строке на каждое поле каждой записи."""
    changes: list[Change] = []
    keys = list(mapping)
    for deal_id, number in (
        await session.execute(select(Deal.id, Deal.erp_number).where(Deal.erp_number.in_(keys)))
    ).all():
        if number is not None and number in mapping:
            changes.append(Change("deals.erp_number", str(deal_id), number, mapping[number]))
    for mail_id, number in (
        await session.execute(
            select(InboundMail.id, InboundMail.eds_letter_number).where(
                InboundMail.eds_letter_number.in_(keys)
            )
        )
    ).all():
        if number is not None and number in mapping:
            changes.append(
                Change("inbound_mail.eds_letter_number", str(mail_id), number, mapping[number])
            )
    for note_id, number, title in (
        await session.execute(
            select(
                StaffNotification.id, StaffNotification.object_number, StaffNotification.title
            ).order_by(StaffNotification.id)
        )
    ).all():
        if number is not None and number in mapping:
            changes.append(
                Change("staff_notifications.object_number", str(note_id), number, mapping[number])
            )
        renamed = replace_numbers(title, mapping)
        if renamed != title:
            changes.append(Change("staff_notifications.title", str(note_id), title, renamed))
    for event_id, items in (
        await session.execute(select(ErpEventNotice.event_id, ErpEventNotice.items))
    ).all():
        for index, item in enumerate(items):
            text = item.get("text")
            if not isinstance(text, str):
                continue
            renamed = replace_numbers(text, mapping)
            if renamed != text:
                changes.append(
                    Change(f"erp_event_notices.items[{index}].text", str(event_id), text, renamed)
                )
    return changes


async def apply(session: AsyncSession, mapping: Mapping[str, str]) -> int:
    """Применяет маппинг к тем же полям; вызывающий открывает транзакцию (всё или ничего)."""
    changes = await plan(session, mapping)
    keys = list(mapping)
    for deal in (await session.scalars(select(Deal).where(Deal.erp_number.in_(keys)))).all():
        if deal.erp_number is not None and deal.erp_number in mapping:
            deal.erp_number = mapping[deal.erp_number]
    for mail in (
        await session.scalars(select(InboundMail).where(InboundMail.eds_letter_number.in_(keys)))
    ).all():
        if mail.eds_letter_number is not None and mail.eds_letter_number in mapping:
            mail.eds_letter_number = mapping[mail.eds_letter_number]
    for note in (await session.scalars(select(StaffNotification))).all():
        if note.object_number is not None and note.object_number in mapping:
            note.object_number = mapping[note.object_number]
        note.title = replace_numbers(note.title, mapping)
    for notice in (await session.scalars(select(ErpEventNotice))).all():
        notice.items = _items_renamed(notice.items, mapping)
    await session.flush()
    return len(changes)


def _items_renamed(items: list[dict[str, Any]], mapping: Mapping[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        text = item.get("text")
        out.append(
            {**item, "text": replace_numbers(text, mapping)} if isinstance(text, str) else item
        )
    return out
