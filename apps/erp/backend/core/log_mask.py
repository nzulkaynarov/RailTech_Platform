"""Общая маска секретов для журнала и Sentry (FIX-66b).

Секрет в адресе, заголовке или теле не должен попасть ни в stdout, ни в Sentry, даже если библиотека на INFO/DEBUG
печатает запрос целиком: URL Bot API (`/bot<id>:<токен>`), подпись и ключ S3 в presigned URL, `Authorization: Bearer`,
ключ шлюза `sk-…`, логин:пароль в адресе, `token=`/`code=`/`key=` в строке запроса, JWT.

Модуль без зависимостей от Django: его импортируют настройки (`LOGGING`), сигналы Celery и хуки Sentry.
Зеркало для CRM — `apps/crm/backend/app/security/log_mask.py`; наборы правил держим одинаковыми.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

# Имена, чьё значение в строке запроса — секрет. Только после `?`/`&`: `code=` в тексте журнала («code=NOT_FOUND»)
# — это код ошибки, а не секрет.
_SECRET_QUERY_NAME = (
    r"(?:[\w.-]*(?:token|secret|passw(?:or)?d|signature|credential|api[_-]?key)[\w.-]*|code|key|sig|auth|pwd|otp)"
)

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Telegram Bot API: токен в пути (`/bot123456:ABC…/getMe`), с префиксом и без него.
    (re.compile(r"\bbot\d+:[\w-]+"), "bot" + REDACTED),
    (re.compile(r"(?<![\w:/.-])\d{6,}:[A-Za-z0-9_-]{30,}(?![\w-])"), REDACTED),
    # S3 presigned URL (SigV4): подпись, учётные данные, сессионный токен — где бы ни встретились.
    (re.compile(r"(?i)(X-Amz-(?:Signature|Credential|Security-Token)=)[^&\s\"'<>#]+"), r"\1" + REDACTED),
    # Заголовки с секретом: `Authorization: Bearer …`, `'Authorization': 'Bearer …'`, `X-Api-Key: …`.
    (
        re.compile(
            r"(?i)((?:proxy-)?authorization|x-api-key|api-key|x-signature|x-telegram-bot-api-secret-token)"
            r"([\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic|token)\s+)?[^\s\"',}&;]+"
        ),
        r"\1\2" + REDACTED,
    ),
    # `Bearer abc…` вне заголовка (текст ошибок клиентов).
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # Ключи шлюза LiteLLM/OpenAI: `sk-…`, `sk-proj-…`, `sk-ant-…`.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"), "sk-" + REDACTED),
    # JWT (SSO-токены, токены сессий).
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*"), REDACTED),
    # Логин:пароль и токен в адресе: `redis://:pass@host`, `https://user:pw@host`.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@\"'<>]+@"), r"\1" + REDACTED + "@"),
    # Секретные параметры строки запроса.
    (re.compile(rf"(?i)([?&]{_SECRET_QUERY_NAME}=)[^&\s\"'<>#]*"), r"\1" + REDACTED),
    # Секреты в JSON/repr тела: `"access_token": "…"`, `'password': '…'`.
    (
        re.compile(r"(?i)([\"'](?:[\w-]*(?:token|secret|passw(?:or)?d|api[_-]?key))[\"']\s*:\s*[\"'])[^\"']*"),
        r"\1" + REDACTED,
    ),
)

# Быстрая проверка до регулярных выражений: большинство строк журнала не содержит ни одного признака.
_HINTS = (
    "bot",
    ":",
    "amz-",
    "authorization",
    "api-key",
    "x-signature",
    "secret-token",
    "bearer",
    "basic ",
    "sk-",
    "eyj",
    "@",
    "?",
    "&",
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
)


def mask_secrets(text: str) -> str:
    """Возвращает текст с замаскированными секретами; строку без секретов — как есть (тот же объект)."""
    if not text:
        return text
    lowered = text.lower()
    if not any(hint in lowered for hint in _HINTS):
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


# Ключи словарей, значения-строки которых секретны целиком (`{"token": "…"}`, `{"Authorization": "…"}`).
_SECRET_KEY = re.compile(r"(?i)token|secret|passw(?:or)?d|api[_-]?key|authorization|signature|credential")
# Ключи, под которыми лежит строка запроса БЕЗ ведущего `?` (Sentry: `query_string`, `http.query`).
_QUERY_KEY = re.compile(r"(?i)(?:^|[._-])query(?:[._-]?string)?$")


def mask_query_string(query: str) -> str:
    """Строка запроса без ведущего `?` (`code=abc&page=1`): правило для `?`/`&` применимо и к первому параметру."""
    return mask_secrets("?" + query)[1:] if query else query


def mask_value(value):
    """Маска для вложенных структур (события Sentry, поля structlog): строки маскируются, остальное обходится."""
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {key: _mask_item(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(item) for item in value]
    return value


def _mask_item(key, item):
    if isinstance(item, str):
        if _SECRET_KEY.search(str(key)):
            return REDACTED
        if _QUERY_KEY.search(str(key)):
            return mask_query_string(item)
    return mask_value(item)


# Стандартные атрибуты LogRecord: всё остальное — `extra=` вызывающего (JSONFormatter кладёт их в запись).
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"request_id", "asctime", "message"}


class SecretMaskFilter(logging.Filter):
    """Фильтр обработчика: маскирует секреты в сообщении, трассировке и строковых `extra` записи.

    Вешается на обработчики (`LOGGING["handlers"][...]["filters"]`, сигналы Celery), а не на логгеры: фильтр логгера
    не видит записей дочерних логгеров. Никогда не отбрасывает запись и не бросает исключений.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._mask(record)
        except Exception:  # noqa: BLE001 — журнал важнее маски; сбой маски не должен ронять запрос
            pass
        return True

    @staticmethod
    def _mask(record: logging.LogRecord) -> None:
        message = record.getMessage()
        masked = mask_secrets(message)
        if masked is not message:
            record.msg, record.args = masked, ()
        if record.exc_info and not record.exc_text:
            # Трассировка форматируется один раз и кэшируется в `exc_text`; в ней же текст исключений
            # (`httpx.HTTPStatusError: … for url 'https://…/bot<токен>/…'`).
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = mask_secrets(record.stack_info)
        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                setattr(record, key, mask_secrets(value))


# Шумные клиентские библиотеки: на INFO/DEBUG пишут URL запроса целиком (в нём бывают токены и подписи).
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "botocore",
    "boto3",
    "s3transfer",
    "aiobotocore",
    "openai",
    "litellm",
    "LiteLLM",
    "hpack",
)


def quiet_noisy_loggers(level: int = logging.WARNING) -> None:
    """Поднимает уровень шумных библиотек не ниже `level` (повторный вызов безопасен)."""
    for name in NOISY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(max(level, logger.level))


# ─── Sentry ───────────────────────────────────────────────────────────────────────────────────────────────────────

# Заголовки запроса, которые в событие Sentry не должны попадать вовсе.
_SECRET_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-signature"}
    | {"x-telegram-bot-api-secret-token", "x-csrftoken"}
)


def _mask_headers(headers: Any) -> Any:
    if isinstance(headers, dict):
        return {k: (REDACTED if str(k).lower() in _SECRET_HEADERS else mask_value(v)) for k, v in headers.items()}
    if isinstance(headers, (list, tuple)):  # [(name, value), …]
        masked = []
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                masked.append([item[0], REDACTED if str(item[0]).lower() in _SECRET_HEADERS else mask_value(item[1])])
            else:
                masked.append(mask_value(item))
        return masked
    return mask_value(headers)


def _mask_exception_values(event: dict) -> None:
    exception = event.get("exception")
    values = exception.get("values") if isinstance(exception, dict) else None
    for item in values or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("value"), str):
            item["value"] = mask_secrets(item["value"])
        for frame in (item.get("stacktrace") or {}).get("frames") or []:
            if isinstance(frame, dict) and isinstance(frame.get("vars"), dict):
                frame["vars"] = mask_value(frame["vars"])


def mask_event(event: dict) -> dict:
    """Маска секретов в событии Sentry: адрес и строка запроса, заголовки, тело исключений, сообщение, extra, crumbs."""
    request = event.get("request")
    if isinstance(request, dict):
        if isinstance(request.get("url"), str):
            request["url"] = mask_secrets(request["url"])
        if "query_string" in request:
            request["query_string"] = (
                mask_query_string(request["query_string"])
                if isinstance(request["query_string"], str)
                else mask_value(request["query_string"])
            )
        if "headers" in request:
            request["headers"] = _mask_headers(request["headers"])
        for field in ("cookies", "env"):
            if field in request:
                request[field] = REDACTED if request[field] else request[field]
    _mask_exception_values(event)
    for field in ("message", "transaction", "culprit"):
        if isinstance(event.get(field), str):
            event[field] = mask_secrets(event[field])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        for field in ("message", "formatted"):
            if isinstance(logentry.get(field), str):
                logentry[field] = mask_secrets(logentry[field])
        if "params" in logentry:
            logentry["params"] = mask_value(logentry["params"])
    if "extra" in event:
        event["extra"] = mask_value(event["extra"])
    if "contexts" in event:
        event["contexts"] = mask_value(event["contexts"])
    breadcrumbs = event.get("breadcrumbs")
    crumbs = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    if isinstance(crumbs, list):
        for crumb in crumbs:
            mask_breadcrumb(crumb)
    return event


def mask_breadcrumb(crumb: Any, hint: Any = None) -> Any:
    """Sentry `before_breadcrumb`: httpx/requests/логгеры пишут URL и сообщение хлебной крошки — маскируем оба."""
    try:
        if isinstance(crumb, dict):
            if isinstance(crumb.get("message"), str):
                crumb["message"] = mask_secrets(crumb["message"])
            if "data" in crumb:
                crumb["data"] = mask_value(crumb["data"])
    except Exception:  # noqa: BLE001 — маска не должна терять крошку
        return crumb
    return crumb
