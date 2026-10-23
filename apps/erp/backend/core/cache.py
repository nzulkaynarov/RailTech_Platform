"""Кэш ERP, переживающий отказ Redis (S0-2, ADR-0017).

Кэш Django, троттлинг DRF, блокировка входа и «виденные» jti живут в отдельном экземпляре `redis-cache`. Брокер Celery и
Channels — в `redis-broker`. Отказ кэша не должен ронять ERP, поэтому штатный `RedisCache` Django обёрнут:

* обычный режим — **открыто**: операция с недоступным Redis не бросает исключение, а возвращает «пусто»
  (`get` → default, `add` → True, `set`/`delete` → ничего не делают); раз в `_LOG_EVERY_S` секунд пишется предупреждение
  без ключей и значений. ERP работает без кэша, троттлинг пропускает запросы;
* строгий режим (`with fail_closed():`) — **закрыто**: та же ошибка превращается в `CacheUnavailable` (503). Нужен там, где
  «нет кэша» означало бы пропуск проверки: одноразовые `jti` SSO, привязки и MCP, повторное использование кода 2FA.
  Безопаснее отказать во входе с понятным текстом, чем принять токен повторно;
* автомат отказа: после ошибки обычные операции пять секунд не ходят в Redis вовсе — иначе каждый запрос платил бы за
  таймаут подключения. Строгие операции автомат не учитывают и всегда пробуют Redis.

Ошибки, не связанные с доступностью Redis (например `ValueError` у `incr` по отсутствующему ключу), не гасятся.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

# `redis.exceptions.ConnectionError`/`TimeoutError` наследуют RedisError; сокет и DNS дают OSError.
_UNAVAILABLE = (RedisError, OSError)

_BREAKER_S = 5.0
_LOG_EVERY_S = 30.0

_strict: contextvars.ContextVar[bool] = contextvars.ContextVar("rt_cache_strict", default=False)
_state = {"down_until": 0.0, "last_log": 0.0, "down": False}

# Понятный текст для людей: SSO и 2FA показывают его рядом с кодом ошибки.
UNAVAILABLE_MESSAGE = (
    "Проверка одноразового токена временно недоступна, вход не выполнен. Повторите попытку через минуту; "
    "если ошибка повторяется, сообщите администратору."
)


class CacheUnavailable(APIException):
    """Кэш недоступен там, где без него нельзя безопасно продолжить (одноразовые метки): 503, а не 500 и не пропуск."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "SERVICE_TEMPORARILY_UNAVAILABLE"
    default_code = "service_temporarily_unavailable"


@contextmanager
def fail_closed() -> Iterator[None]:
    """Внутри блока недоступный кэш бросает `CacheUnavailable` вместо «пусто» (одноразовые jti, коды 2FA)."""
    token = _strict.set(True)
    try:
        yield
    finally:
        _strict.reset(token)


def _mark_down(operation: str, exc: BaseException) -> None:
    now = time.monotonic()
    _state["down_until"] = now + _BREAKER_S
    _state["down"] = True
    if now - _state["last_log"] >= _LOG_EVERY_S:
        _state["last_log"] = now
        logger.warning(
            "Кэш (Redis) недоступен, ERP работает без кэша: операция=%s, ошибка=%s", operation, type(exc).__name__
        )


def _mark_up() -> None:
    if _state["down"]:
        _state["down"] = False
        _state["down_until"] = 0.0
        logger.warning("Кэш (Redis) снова доступен")


def _guarded(fallback: Callable[..., Any]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(method)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            strict = _strict.get()
            if not strict and time.monotonic() < _state["down_until"]:
                return fallback(*args, **kwargs)
            try:
                result = method(self, *args, **kwargs)
            except _UNAVAILABLE as exc:
                _mark_down(method.__name__, exc)
                if strict:
                    raise CacheUnavailable() from exc
                return fallback(*args, **kwargs)
            _mark_up()
            return result

        return wrapper

    return decorate


def _default_of_get(key: Any, default: Any = None, version: Any = None) -> Any:
    return default


class ResilientRedisCache(RedisCache):
    """`RedisCache` Django, который при недоступном Redis отвечает «пусто» (или `CacheUnavailable` в `fail_closed()`)."""

    @_guarded(lambda key, value, timeout=None, version=None: True)
    def add(self, key, value, timeout=None, version=None):  # type: ignore[no-untyped-def]
        return super().add(key, value, timeout, version)

    @_guarded(_default_of_get)
    def get(self, key, default=None, version=None):  # type: ignore[no-untyped-def]
        return super().get(key, default, version)

    @_guarded(lambda *a, **kw: None)
    def set(self, key, value, timeout=None, version=None):  # type: ignore[no-untyped-def]
        return super().set(key, value, timeout, version)

    @_guarded(lambda *a, **kw: False)
    def touch(self, key, timeout=None, version=None):  # type: ignore[no-untyped-def]
        return super().touch(key, timeout, version)

    @_guarded(lambda *a, **kw: False)
    def delete(self, key, version=None):  # type: ignore[no-untyped-def]
        return super().delete(key, version)

    @_guarded(lambda *a, **kw: {})
    def get_many(self, keys, version=None):  # type: ignore[no-untyped-def]
        return super().get_many(keys, version)

    @_guarded(lambda *a, **kw: False)
    def has_key(self, key, version=None):  # type: ignore[no-untyped-def]
        return super().has_key(key, version)

    @_guarded(lambda key, delta=1, version=None: delta)
    def incr(self, key, delta=1, version=None):  # type: ignore[no-untyped-def]
        return super().incr(key, delta, version)

    @_guarded(lambda data, timeout=None, version=None: list(data))
    def set_many(self, data, timeout=None, version=None):  # type: ignore[no-untyped-def]
        return super().set_many(data, timeout, version)

    @_guarded(lambda *a, **kw: None)
    def delete_many(self, keys, version=None):  # type: ignore[no-untyped-def]
        return super().delete_many(keys, version)

    @_guarded(lambda *a, **kw: None)
    def clear(self):  # type: ignore[no-untyped-def]
        return super().clear()
