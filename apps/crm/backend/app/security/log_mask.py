"""Общая маска секретов для журнала и Sentry (FIX-66b).

Секрет в адресе, заголовке или теле не должен попасть ни в stdout, ни в Sentry, даже если
библиотека на INFO/DEBUG печатает запрос целиком: URL Bot API (`/bot<id>:<токен>`), подпись и
ключ S3 в presigned URL, `Authorization: Bearer`, ключ шлюза `sk-…`, логин:пароль в адресе,
`token=`/`code=`/`key=` в строке запроса, JWT.

Зеркало ERP — `apps/erp/backend/core/log_mask.py`; наборы правил держим одинаковыми. Отдельный
от `app/log.py` модуль: `log.py` лишь подключает процессор.
"""

import contextlib
import logging
import re
from collections.abc import MutableMapping
from typing import Any, Final

REDACTED: Final = "[REDACTED]"

# Имена, чьё значение в строке запроса — секрет. Только после `?`/`&`: `code=` в тексте журнала
# («code=NOT_FOUND») — это код ошибки, а не секрет.
_SENSITIVE_PARAM: Final = (
    r"(?:[\w.-]*(?:token|secret|passw(?:or)?d|signature|credential|api[_-]?key)[\w.-]*"
    r"|code|key|sig|auth|pwd|otp)"
)

_RULES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Telegram Bot API: токен в пути (`/bot123456:ABC…/getMe`), с префиксом и без него.
    (re.compile(r"\bbot\d+:[\w-]+"), "bot" + REDACTED),
    (re.compile(r"(?<![\w:/.-])\d{6,}:[A-Za-z0-9_-]{30,}(?![\w-])"), REDACTED),
    # S3 presigned URL (SigV4): подпись, учётные данные, сессионный токен — где бы ни встретились.
    (
        re.compile(r"(?i)(X-Amz-(?:Signature|Credential|Security-Token)=)[^&\s\"'<>#]+"),
        r"\1" + REDACTED,
    ),
    # Заголовки с секретом: `Authorization: Bearer …`, `'Authorization': 'Bearer …'`, `X-Api-Key`.
    (
        re.compile(
            r"(?i)((?:proxy-)?authorization|x-api-key|api-key|x-signature|x-pairing-proof|x-telegram-bot-api-secret-token)"
            r"([\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic|token)\s+)?[^\s\"',}&;]+"
        ),
        r"\1\2" + REDACTED,
    ),
    # `Bearer abc…` вне заголовка (текст ошибок клиентов). `Basic` тут нельзя:
    # «Basic configuration» — обычная фраза; его ловит правило заголовка Authorization.
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # Ключи шлюза LiteLLM/OpenAI: `sk-…`, `sk-proj-…`, `sk-ant-…`.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"), "sk-" + REDACTED),
    # JWT (SSO-токены, токены сессий).
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*"), REDACTED),
    # Логин:пароль и токен в адресе: `redis://:pass@host`, `https://user:pw@host`.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@\"'<>]+@"), r"\1" + REDACTED + "@"),
    # Секретные параметры строки запроса.
    (re.compile(rf"(?i)([?&]{_SENSITIVE_PARAM}=)[^&\s\"'<>#]*"), r"\1" + REDACTED),
    # Секреты в JSON/repr тела: `"access_token": "…"`, `'password': '…'`.
    (
        re.compile(
            r"(?i)([\"'](?:[\w-]*(?:token|secret|passw(?:or)?d|api[_-]?key))[\"']\s*:\s*[\"'])[^\"']*"
        ),
        r"\1" + REDACTED,
    ),
)

# Быстрая проверка до регулярных выражений: большинство строк журнала не содержит признаков.
_HINTS: Final = (
    "bot",
    ":",
    "amz-",
    "authorization",
    "api-key",
    "x-signature",
    "x-pairing-proof",
    "secret-token",
    "bearer",
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
    """Текст с замаскированными секретами; строка без секретов — тот же объект."""
    if not text:
        return text
    lowered = text.lower()
    if not any(hint in lowered for hint in _HINTS):
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


# Ключи словарей, чьи строковые значения секретны целиком (`token`, `Authorization`, …).
_SECRET_KEY = re.compile(
    r"(?i)token|secret|passw(?:or)?d|api[_-]?key|authorization|signature|credential"
)
# Ключи со строкой запроса БЕЗ ведущего `?` (Sentry: `query_string`, `http.query`).
_QUERY_KEY = re.compile(r"(?i)(?:^|[._-])query(?:[._-]?string)?$")


def mask_query_string(query: str) -> str:
    """Строка запроса без ведущего `?` (`code=abc&page=1`): правило `?` ловит и первый параметр."""
    return mask_secrets("?" + query)[1:] if query else query


def mask_value(value: Any) -> Any:
    """Маска для вложенных структур (события Sentry, поля structlog): строки маскируются."""
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {key: _mask_item(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_value(item) for item in value]
    if isinstance(value, tuple):
        # Тип сохраняем: `exc_info=(type, exc, tb)` в list `format_exc_info` не узнаёт.
        return tuple(mask_value(item) for item in value)
    return value


def _mask_item(key: Any, item: Any) -> Any:
    if isinstance(item, str):
        if _SECRET_KEY.search(str(key)):
            return REDACTED
        if _QUERY_KEY.search(str(key)):
            return mask_query_string(item)
    return mask_value(item)


# ─── stdlib / structlog ─────────────────────────────────────────────────────────────────────

# Стандартные атрибуты LogRecord: всё остальное — `extra=` вызывающего.
_RESERVED: Final = frozenset(vars(logging.makeLogRecord({})).keys()) | {"asctime", "message"}


class SecretMaskFilter(logging.Filter):
    """Фильтр обработчика stdlib: секреты в сообщении, трассировке и строковых `extra` записи.

    Вешается на обработчики, а не на логгеры: фильтр логгера не видит записей дочерних логгеров.
    Никогда не отбрасывает запись и не бросает исключений.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Журнал важнее маски: сбой маски не должен ронять запрос.
        with contextlib.suppress(Exception):
            self._mask(record)
        return True

    @staticmethod
    def _mask(record: logging.LogRecord) -> None:
        message = record.getMessage()
        masked = mask_secrets(message)
        if masked is not message:
            record.msg, record.args = masked, ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = mask_secrets(record.stack_info)
        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                setattr(record, key, mask_secrets(value))


# Служебные ключи structlog: не текст, а объекты (кортеж/исключение для `format_exc_info`, запись
# stdlib). Текст исключения маскируется уже после `format_exc_info` (процессор в `app/log.py`).
_STRUCTLOG_SERVICE_KEYS: Final = frozenset({"exc_info", "stack_info", "_record", "_from_structlog"})


def structlog_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Процессор structlog: маска во ВСЕХ полях, включая `event` и `exception`.

    В `pii` эти ключи «безопасные», поэтому тексты исключений и стдлиб-сообщений шли как есть.
    После `format_exc_info` трассировка уже строка.
    """
    for key, value in list(event_dict.items()):
        if key in _STRUCTLOG_SERVICE_KEYS:
            continue
        event_dict[key] = _mask_item(key, value)
    return event_dict


# Шумные клиентские библиотеки: на INFO/DEBUG пишут URL запроса целиком (токены, подписи).
NOISY_LOGGERS: Final = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "botocore",
    "boto3",
    "s3transfer",
    "aiobotocore",
    "aiohttp.client",
    "aiogram.client",
    "openai",
    "litellm",
    "LiteLLM",
    "hpack",
)


def quiet_noisy_loggers(level: int = logging.WARNING) -> None:
    """Поднимает уровень шумных библиотек не ниже `level` (повтор безопасен)."""
    for name in NOISY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(max(level, logger.level))


# ─── Sentry: хуки (sentry-sdk в CRM не подключён; при подключении — в `sentry_sdk.init`) ───────

_SECRET_HEADERS: Final = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-signature"}
    | {"x-telegram-bot-api-secret-token", "x-pairing-proof"}
)


def _mask_headers(headers: Any) -> Any:
    if isinstance(headers, dict):
        return {
            k: (REDACTED if str(k).lower() in _SECRET_HEADERS else mask_value(v))
            for k, v in headers.items()
        }
    if isinstance(headers, list | tuple):  # [(name, value), …]
        masked: list[Any] = []
        for item in headers:
            if isinstance(item, list | tuple) and len(item) == 2:
                masked.append(
                    [
                        item[0],
                        REDACTED
                        if str(item[0]).lower() in _SECRET_HEADERS
                        else mask_value(item[1]),
                    ]
                )
            else:
                masked.append(mask_value(item))
        return masked
    return mask_value(headers)


def _mask_exception_values(event: dict[str, Any]) -> None:
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


def mask_breadcrumb(crumb: Any, hint: Any = None) -> Any:
    """Sentry `before_breadcrumb`: httpx и логгеры пишут URL и сообщение крошки — маскируем оба."""
    try:
        if isinstance(crumb, dict):
            if isinstance(crumb.get("message"), str):
                crumb["message"] = mask_secrets(crumb["message"])
            if "data" in crumb:
                crumb["data"] = mask_value(crumb["data"])
    except Exception:  # noqa: BLE001 — маска не должна терять крошку
        return crumb
    return crumb


def mask_sentry_event(event: Any, hint: Any = None) -> Any:
    """Sentry `before_send`: адрес, строка запроса, заголовки, тело исключений, extra, крошки.

    Никогда не возвращает None (событие не теряется) и не бросает исключений.
    """
    try:
        _mask_event(event)
    except Exception:  # noqa: BLE001 — маска не должна ронять отчёт об ошибке
        return event
    return event


def _mask_event(event: dict[str, Any]) -> None:
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
            if request.get(field):
                request[field] = REDACTED
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
    for field in ("extra", "contexts"):
        if field in event:
            event[field] = mask_value(event[field])
    breadcrumbs = event.get("breadcrumbs")
    crumbs = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    if isinstance(crumbs, list):
        for crumb in crumbs:
            mask_breadcrumb(crumb)
