"""Состояние внешних сервисов ERP (M3-ERP-06, ORCHESTRATOR §3.13): метки, счётчики за 24 ч, выключатели.

Что здесь: `record_success` / `record_failure` — лёгкая отметка в кэше (Redis) в местах настоящего вызова сервиса:
метка последнего успеха и ошибки и счётчики по часовым корзинам (окно 24 ч = текущий и 23 прошлых часа, корзина живёт
26 ч). `external_call(code)` — обёртка вокруг вызова: проверяет выключатель, отмечает исход. `is_enabled` / `set_enabled` —
выключатель из CRM: строка `ExternalServiceSwitch` в базе (источник истины), копия в кэше на 5 минут.

Принципы: отметка никогда не ломает вызывающего (сбой кэша — предупреждение в лог); текст ошибки короткий и без
секретов (`short_error`); сам `GET /health` сюда только читает и сервисов не вызывает (`integration.services.externals`).
Почту (EmailLog) и модели (ai.AICall) ведут свои журналы — для них здесь только выключатель.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Iterator

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

#: Коды сервисов — те же, что в контракте (`ExternalServiceCode`).
CODES: tuple[str, ...] = ("cbu_rates", "customs_tariff", "mail", "litellm", "s3", "sentry")
#: Sentry выключить нельзя: перехватчик ошибок приложения не вызывается «по требованию» — выключать нечего.
SWITCHABLE: frozenset[str] = frozenset(CODES) - {"sentry"}
WINDOW_HOURS = 24
BUCKET_TTL_S = 26 * 3600
MARK_TTL_S = 90 * 24 * 3600
SWITCH_CACHE_TTL_S = 300
ERROR_MAX_LEN = 200
#: Начало `EmailLog.error` у письма, не отправленного из-за выключателя: это не сбой почты.
SWITCHED_OFF_MARK = "SWITCHED_OFF"


class ExternalSwitchedOff(Exception):
    """Сервис выключен из CRM — вызов не выполняется."""

    def __init__(self, code: str):
        super().__init__(f"{SWITCHED_OFF_MARK}: {code}")
        self.code = code


class NotSwitchable(Exception):
    """У сервиса нет выключателя (Sentry)."""


def _check(code: str) -> str:
    if code not in CODES:
        raise KeyError(f"unknown external service: {code!r}")
    return code


# ── Текст ошибки без секретов ───────────────────────────────────────────────────────────────────────

_URL = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*)://(?:[^/\s'\"@]*@)?(?P<host>[^/\s'\"?#]+)[^\s'\"]*", re.IGNORECASE)
_KEY_VALUE = re.compile(
    r"(?P<key>pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|bearer|credential[s]?)"
    r"(?P<sep>\s*[=:]\s*|\s+)(?P<value>\S+)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_TOKEN = re.compile(r"\b(?=[A-Za-z_\-]*\d)[A-Za-z0-9_\-]{20,}\b")


def short_error(error: object) -> str:
    """Короткий (≤ 200 знаков) текст ошибки: класс и сообщение; адреса сведены к хосту, учётные данные, ключи, токены
    и e-mail скрыты. Ничего из тела ответа сервиса сюда не попадает."""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error or "")
    text = _URL.sub(lambda m: f"{m.group('scheme')}://{m.group('host')}", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group('key')}{m.group('sep')}[скрыто]", text)
    text = _EMAIL.sub("[e-mail]", text)
    text = _LONG_TOKEN.sub("[скрыто]", text)
    text = " ".join(text.split())
    if not text:
        return "Error"
    return text if len(text) <= ERROR_MAX_LEN else text[: ERROR_MAX_LEN - 1].rstrip() + "…"


# ── Метки и счётчики (кэш) ──────────────────────────────────────────────────────────────────────────


def _hour(moment: datetime) -> int:
    return int(moment.timestamp() // 3600)


def _bucket_key(code: str, kind: str, hour: int) -> str:
    return f"ext:{code}:{kind}:{hour}"


def _bump(code: str, kind: str, moment: datetime) -> None:
    key = _bucket_key(code, kind, _hour(moment))
    cache.add(key, 0, BUCKET_TTL_S)
    cache.incr(key)


def record_success(code: str, *, at: datetime | None = None) -> None:
    """Отметить удачный вызов сервиса. Сбой кэша вызывающего не трогает."""
    _check(code)
    moment = at or timezone.now()
    try:
        _bump(code, "ok", moment)
        previous = _read_mark(code, "last_ok")
        if previous is None or previous < moment:
            cache.set(f"ext:{code}:last_ok", moment.isoformat(), MARK_TTL_S)
    except Exception:  # noqa: BLE001 — отметка статуса не должна ронять вызов сервиса
        logger.warning("external status: cannot record success for %s", code, exc_info=True)


def record_failure(code: str, error: object, *, at: datetime | None = None) -> None:
    """Отметить неудачный вызов сервиса; `error` — исключение или текст (в метку идёт `short_error`)."""
    _check(code)
    moment = at or timezone.now()
    try:
        _bump(code, "err", moment)
        previous = _read_mark(code, "last_err")
        if previous is None or previous < moment:
            cache.set(f"ext:{code}:last_err", moment.isoformat(), MARK_TTL_S)
            cache.set(f"ext:{code}:last_err_text", short_error(error), MARK_TTL_S)
    except Exception:  # noqa: BLE001
        logger.warning("external status: cannot record failure for %s", code, exc_info=True)


def _read_mark(code: str, name: str) -> datetime | None:
    raw = cache.get(f"ext:{code}:{name}")
    parsed = parse_datetime(raw) if isinstance(raw, str) else None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def counts(code: str, *, now: datetime | None = None) -> tuple[int, int]:
    """(успехи, ошибки) за последние 24 ч по отметкам кэша; нет кэша — (0, 0)."""
    _check(code)
    now = now or timezone.now()
    hours = [_hour(now) - offset for offset in range(WINDOW_HOURS)]
    keys = [_bucket_key(code, kind, hour) for kind in ("ok", "err") for hour in hours]
    try:
        found = cache.get_many(keys)
    except Exception:  # noqa: BLE001
        logger.warning("external status: cannot read counters for %s", code, exc_info=True)
        return 0, 0
    ok = sum(int(found.get(_bucket_key(code, "ok", hour)) or 0) for hour in hours)
    err = sum(int(found.get(_bucket_key(code, "err", hour)) or 0) for hour in hours)
    return ok, err


def last_marks(code: str) -> tuple[datetime | None, datetime | None, str | None]:
    """(последний успех, последняя ошибка, текст последней ошибки) по отметкам кэша."""
    _check(code)
    try:
        return _read_mark(code, "last_ok"), _read_mark(code, "last_err"), cache.get(f"ext:{code}:last_err_text")
    except Exception:  # noqa: BLE001
        logger.warning("external status: cannot read marks for %s", code, exc_info=True)
        return None, None, None


# ── Выключатель ─────────────────────────────────────────────────────────────────────────────────────


def _switch_key(code: str) -> str:
    return f"ext:{code}:enabled"


def is_enabled(code: str) -> bool:
    """Включён ли сервис. Нет строки в базе — включён; сбой чтения не выключает сервис."""
    _check(code)
    try:
        cached = cache.get(_switch_key(code))
        if isinstance(cached, bool):
            return cached
    except Exception:  # noqa: BLE001
        logger.warning("external status: cannot read switch cache for %s", code, exc_info=True)
    try:
        from core.models import ExternalServiceSwitch

        row = ExternalServiceSwitch.objects.filter(code=code).first()
    except Exception:  # noqa: BLE001 — таблицы нет (миграции) или база недоступна: не выключаем сервис
        logger.warning("external status: cannot read switch for %s", code, exc_info=True)
        return True
    enabled = True if row is None else row.enabled
    try:
        cache.set(_switch_key(code), enabled, SWITCH_CACHE_TTL_S)
    except Exception:  # noqa: BLE001
        pass
    return enabled


def set_enabled(code: str, enabled: bool, reason: str = ""):
    """Включить или выключить сервис (идемпотентно). Возвращает строку `ExternalServiceSwitch`."""
    _check(code)
    if code not in SWITCHABLE:
        raise NotSwitchable(code)
    from core.models import ExternalServiceSwitch

    cleaned = " ".join((reason or "").split())[:200] if not enabled else ""
    row, _ = ExternalServiceSwitch.objects.update_or_create(code=code, defaults={"enabled": enabled, "reason": cleaned})
    try:
        cache.set(_switch_key(code), enabled, SWITCH_CACHE_TTL_S)
    except Exception:  # noqa: BLE001
        logger.warning("external status: cannot cache switch for %s", code, exc_info=True)
    logger.warning("external service %s switched %s (reason: %s)", code, "ON" if enabled else "OFF", cleaned or "-")
    return row


@contextmanager
def external_call(code: str) -> Iterator[None]:
    """Вокруг настоящего вызова сервиса: выключен — `ExternalSwitchedOff`, иначе исход отмечается (успех/ошибка)."""
    if not is_enabled(code):
        raise ExternalSwitchedOff(code)
    try:
        yield
    except Exception as exc:
        record_failure(code, exc)
        raise
    record_success(code)


def window_start(now: datetime | None = None) -> datetime:
    """Начало окна 24 ч для запросов к журналам (EmailLog, AICall)."""
    return (now or timezone.now()) - timedelta(hours=WINDOW_HOURS)
