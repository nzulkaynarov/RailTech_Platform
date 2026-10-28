"""Строка «Доработать» «Моей очереди» автора (D1-6b, контракт BFF 0.25.0).

Документ сотрудника (служебная записка, заявление, отчёт), который согласующий вернул на
доработку, — работа автора: без строки возврат директором был бы тупиком пути (SPEC-v3 §2.4,
«Возвращена на доработку» -> автор правит и отправляет снова). Источник — EDS по токену
сотрудника (`aud=eds`): `GET /documents?mine=true&status=returned` (только свои документы) и
карточка каждого возвращённого документа ради решения «Вернуть» (кто и что написал). Решает EDS:
что он вернул, то и строки; после повторной отправки статус меняется, и строка исчезает сама.
Строка открывает форму «Продолжить» (`/eds/new?draft=<id>`) — отдельного экрана нет.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed, rows
from app.feeds.models import ObjectRef, QueueItem
from app.feeds.text import ago, due_label, join, parse_deadline, parse_dt, short
from app.rbac import View

LIST_PATH = "/api/v1/documents"
# Документы, которые автор правит и отправляет снова; исходящие письма возвращаются иначе.
KINDS = ("memo", "application", "report")
# Возвратов у одного автора немного; запасной предел защищает EDS от выборки «всех документов».
LIMIT = 20
LIST_PARAMS: dict[str, Any] = {
    "mine": "true",
    "status": ["returned"],
    "kind": list(KINDS),
    "limit": LIMIT,
}


@dataclass
class Returned:
    """Возвращённый документ и его последнее решение «Вернуть» (`None` — карточку EDS не отдал)."""

    document: dict[str, Any]
    decision: dict[str, Any] | None = None


def wants_rework(view: View) -> bool:
    return view.wants("rework_document")


def _last_return(card: Any) -> dict[str, Any] | None:
    """Самое позднее решение «Вернуть» в карточке документа."""
    if not isinstance(card, dict):
        return None
    found = [
        d
        for d in card.get("decisions") or []
        if isinstance(d, dict) and d.get("decision") == "return"
    ]
    return max(found, key=lambda d: str(d.get("at") or ""), default=None)


async def load_rework(feed: Feed, view: View) -> list[Returned] | None:
    """Возвращённые документы автора; `None` — EDS не прочитан (нет доступа или не ответил):
    строк нет, остальная очередь собирается без него."""
    if not wants_rework(view):
        return None
    payload = await feed.get("eds", LIST_PATH, LIST_PARAMS, ttl=SNAPSHOT_TTL_SECONDS)
    if payload is None:
        return None
    documents = [d for d in rows(payload) if isinstance(d.get("id"), str)]
    if not documents:
        return []
    seen: list[str] = []

    async def card(document: dict[str, Any]) -> Returned:
        detail = await feed.get(
            "eds", f"{LIST_PATH}/{document['id']}", None, ttl=SNAPSHOT_TTL_SECONDS
        )
        seen.append(feed.states["eds"])
        return Returned(document, _last_return(detail))

    found = list(await asyncio.gather(*(card(d) for d in documents)))
    # Звонки идут параллельно, и состояние источника ставит последний: сбой любого из них важнее.
    if "unavailable" in seen:
        feed.states["eds"] = "unavailable"
    return found


def rework_item(
    entry: Returned, now: datetime, *, role_id: str
) -> tuple[QueueItem, datetime | None]:
    """Строка очереди и момент, с которого она ждёт (при равном сроке старшее — выше)."""
    document = entry.document
    subject = short(document.get("subject"), 90)
    number = document.get("number")
    number = number if isinstance(number, str) and number else subject or "документ"
    decision = entry.decision or {}
    by = decision.get("by")
    name = by.get("full_name") if isinstance(by, dict) else None
    who = name if isinstance(name, str) and name else None
    comment = short(decision.get("comment"), 140)
    returned_at = parse_dt(decision.get("at"))
    due_at = parse_deadline(document.get("due_date"))
    remark = f"Вернул {who}: {comment}" if who and comment else None
    remark = remark or (f"Вернул {who}" if who else "Возвращён на доработку")
    item = QueueItem(
        id=f"rework:{document['id']}",
        role_id=role_id,
        kind="rework_document",
        title=f"Доработать: {number}" + (f" · {subject}" if subject and subject != number else ""),
        subtitle=join(remark, ago(returned_at, now)),
        due_label=due_label(due_at, now, default="today"),
        due_at=due_at,
        object=ObjectRef(
            kind="memo",
            number=number,
            title=subject or None,
            path=f"/eds/new?draft={document['id']}",
        ),
    )
    return item, returned_at or parse_dt(document.get("created_at"))
