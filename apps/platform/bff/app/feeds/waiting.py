"""«Вы ждёте других» (ГЛ-1): что сотрудник передал и ждёт от другого, с «Напомнить».

Строки вычисляет EDS (`GET /waiting`): письмо на подписи, мои служебки и заявления на согласовании,
выданные мной поручения. BFF даёт им адрес объекта и подпись «у кого · сколько ждёт»; «ждёт» —
возраст передачи, а не выдуманный срок. Напоминание — EDS `POST /waiting/{kind}/{id}/remind`
(не чаще раза в час на объект).
"""

from typing import Any

from app.feeds.feed import SNAPSHOT_TTL_SECONDS, Feed
from app.feeds.models import ObjectRef, WaitingRow
from app.feeds.numbers import letter_ref, memo_ref, outgoing_document_path
from app.feeds.text import join, parse_deadline, parse_dt, short

WAITING_PATH = "/api/v1/waiting"
_KINDS = ("letter_signature", "approval", "instruction")


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _object(kind: str, object_id: str, number: str | None, title: str | None) -> ObjectRef:
    if kind == "letter_signature":
        return ObjectRef(
            kind="memo",
            number=number or title or "Исходящее",
            title=title,
            path=outgoing_document_path(object_id),
        )
    if kind == "instruction" and number:
        return letter_ref(number, title)
    return memo_ref(number or title or "Документ", title)


def _row(entry: dict[str, Any]) -> WaitingRow | None:
    kind, object_id = entry.get("kind"), _text(entry.get("object_id"))
    since = parse_dt(entry.get("since"))
    if kind not in _KINDS or object_id is None or since is None:
        return None
    title = short(entry.get("title"), 90) or ""
    number = _text(entry.get("number"))
    person = entry.get("waiting_on")
    waiting_on = None
    if isinstance(person, dict) and isinstance(person.get("crm_user_id"), int):
        name = _text(person.get("full_name"))
        if name:
            waiting_on = {"id": str(person["crm_user_id"]), "name": name}
    available = parse_dt(entry.get("remind_available_at"))
    return WaitingRow(
        id=f"{kind}:{object_id}",
        kind=kind,
        object_id=object_id,
        title=join(number, title) if kind != "letter_signature" else title or number or "Письмо",
        waiting_on=waiting_on,
        waiting_label=_text(entry.get("waiting_label")),
        since=since,
        due_at=parse_deadline(entry.get("due")),
        remindable=entry.get("remindable") is True,
        remind_available_at=available,
        object=_object(kind, object_id, number, title or None),
    )


async def load_waiting(feed: Feed) -> tuple[list[WaitingRow], bool]:
    """Строки и признак «показаны не все»; EDS не ответил — пусто (источник помечен в `sources`)."""
    if not feed.usable("eds"):
        return [], False
    payload = await feed.get("eds", WAITING_PATH, ttl=SNAPSHOT_TTL_SECONDS)
    if not isinstance(payload, dict):
        return [], False
    items = payload.get("items")
    rows = [
        row
        for entry in (items if isinstance(items, list) else [])
        if isinstance(entry, dict) and (row := _row(entry)) is not None
    ]
    return rows, payload.get("more") is True
