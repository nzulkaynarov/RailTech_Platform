"""Личный календарь сотрудника по секретной ссылке (iCal-подписка, ADR-0015: у BFF нет своей базы
и служебных ключей к данным).

Календарный клиент приходит без сессии, поэтому ничего «вживую» из CRM, ERP и EDS BFF собрать не
может: их токены лежат только в сессии сотрудника. Лента — проекция его «Моей очереди»: пока он
работает в Платформе, каждый разбор очереди обновляет в Redis снимок (название, срок, адрес
объекта; без сумм, цен и условий сделок). Что хранится, `TTL` 30 дней от последнего обновления:

- `cal:tok:<sha256 токена>` -> id сотрудника: по ней публичный маршрут находит владельца;
- `cal:user:<id>` -> {hash, issued_at, origin}: действующая ссылка сотрудника (одна);
- `cal:snap:<id>` -> список строк снимка.

Сам токен нигде не хранится (его хеш — ещё и в CRM, `users.calendar_token_hash`). Отключение
сотрудника (событие шины `identity.user.deactivated`) стирает все три ключа.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
from redis.asyncio import Redis

from app.feeds.models import QueueItem

TTL_SECONDS = 30 * 24 * 3600
COMPANY_TZ = ZoneInfo("Asia/Tashkent")
CALENDAR_NAME = "RailTech — сроки"
MAX_EVENTS = 300
# Календарные клиенты опрашивают раз в час-сутки; кэш на минуту гасит лишние повторы
CACHE_CONTROL = "private, max-age=300"
FAILURE_LIMIT_PER_HOUR = 60


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def _tok(digest: str) -> str:
    return f"cal:tok:{digest}"


def _user(user_id: int | str) -> str:
    return f"cal:user:{user_id}"


def _snap(user_id: int | str) -> str:
    return f"cal:snap:{user_id}"


@dataclass(frozen=True)
class LinkState:
    active: bool
    issued_at: str | None = None


async def activate(redis: Redis, user_id: int, token: str, issued_at: str, origin: str) -> None:
    """Новая ссылка вместо прежней: старый токен перестаёт находиться."""
    await _drop_tokens(redis, user_id)
    digest = hash_token(token)
    await redis.set(_tok(digest), str(user_id), ex=TTL_SECONDS)
    record = {"hash": digest, "issued_at": issued_at, "origin": origin}
    await redis.set(_user(user_id), json.dumps(record), ex=TTL_SECONDS)


async def _record(redis: Redis, user_id: int) -> dict[str, Any] | None:
    raw = await redis.get(_user(user_id))
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


async def _drop_tokens(redis: Redis, user_id: int) -> None:
    record = await _record(redis, user_id)
    if record is not None and isinstance(record.get("hash"), str):
        await redis.delete(_tok(record["hash"]))


async def revoke_user(redis: Redis, user_id: int) -> None:
    """Ссылка и снимок сотрудника стираются (отключение сотрудника)."""
    await _drop_tokens(redis, user_id)
    await redis.delete(_user(user_id), _snap(user_id))


async def state(redis: Redis, user_id: int) -> LinkState:
    record = await _record(redis, user_id)
    if record is None:
        return LinkState(False)
    issued = record.get("issued_at")
    return LinkState(True, issued if isinstance(issued, str) else None)


def _projection(items: list[QueueItem]) -> list[dict[str, str]]:
    """Только то, что видно в календаре: id, название, срок, вид и адрес объекта."""
    rows = []
    for item in items:
        if item.due_at is None:
            continue
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "due": item.due_at.astimezone(COMPANY_TZ).date().isoformat(),
                "kind": item.kind,
                "path": item.object.path,
            }
        )
        if len(rows) >= MAX_EVENTS:
            break
    return rows


async def store_snapshot(redis: Redis, user_id: int, items: list[QueueItem], now: float) -> None:
    """Обновить снимок, если у сотрудника есть ссылка; срок ссылки продлевается вместе с ним."""
    record = await _record(redis, user_id)
    if record is None:
        return
    body = {"at": now, "events": _projection(items)}
    await redis.set(_snap(user_id), json.dumps(body, ensure_ascii=False), ex=TTL_SECONDS)
    await redis.expire(_user(user_id), TTL_SECONDS)
    if isinstance(record.get("hash"), str):
        await redis.expire(_tok(record["hash"]), TTL_SECONDS)


async def render(redis: Redis, token: str) -> bytes | None:
    """iCal по токену; неизвестный, заменённый или просроченный токен — `None`."""
    raw_owner = await redis.get(_tok(hash_token(token)))
    if raw_owner is None:
        return None
    owner = str(raw_owner)
    record = await _record(redis, int(owner)) if owner.isdigit() else None
    if record is None or record.get("hash") != hash_token(token):
        return None
    origin = str(record.get("origin") or "")
    raw_snap = await redis.get(_snap(owner))
    snap: dict[str, Any] = {}
    if raw_snap is not None:
        try:
            snap = json.loads(raw_snap)
        except ValueError:
            snap = {}
    return build_ics(snap.get("events") or [], origin, float(snap.get("at") or 0))


def build_ics(events: list[dict[str, str]], origin: str, stamp: float) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//RailTech Platform//calendar//RU")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", CALENDAR_NAME)
    calendar.add("x-published-ttl", "PT1H")
    calendar.add("refresh-interval", timedelta(hours=1), parameters={"VALUE": "DURATION"})
    moment = datetime.fromtimestamp(stamp, UTC)
    for row in events:
        event = Event()
        event.add("uid", f"{row['id']}@calendar.rt-platform")
        event.add("dtstamp", moment)
        event.add("dtstart", datetime.fromisoformat(row["due"]).date())
        event.add("summary", row["title"])
        event.add("categories", [row["kind"]])
        if origin:
            event.add("url", f"{origin}{row['path']}")
        calendar.add_component(event)
    return bytes(calendar.to_ical())
