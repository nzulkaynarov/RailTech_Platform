"""Чтение CRM и ERP от имени сотрудника с учётом частичных данных (`sources`).

Агрегаты ходят в источники параллельно (клиенты держат таймаут 3 с, `app/clients/base.py`).
Источник, который не ответил, помечается `unavailable`, а ответ собирается из того, что есть
(02-architecture.md §8). Сотруднику без доступа к ERP источник остаётся `not_applicable`, вызовы
в него не уходят.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any, cast

import structlog

from app.clients.base import Backend
from app.deps import Authed
from app.errors import PlatformError
from app.feeds.models import Sources, SourceState
from app.rbac import gives_backend, strip_restricted

log = structlog.get_logger()

# Кэш на секунды (CLAUDE.md Платформы, правило 3: Redis — сессии, кэш на секунды, события).
# Снимок источников общий для всех экранов сессии: счётчики меню, очередь, карточки, уведомления
# и лента опрашиваются вместе каждые 30 с, и без кэша один сотрудник давал бы по 5–6 одинаковых
# запросов в ERP за тик.
SNAPSHOT_TTL_SECONDS = 8
# Отказ бэкенда (ERP отдаёт журнал только админу платформы) запоминается: повторять бессмысленно.
REFUSAL_TTL_SECONDS = 60

# Поля ответов ERP с ограничением (platform-rbac.yaml `restricted_fields`): вырезаются из сырого
# ответа до разбора и до кэша, чтобы ни один агрегат не мог вернуть их по ошибке. Поля берутся по
# объединению ролей (как права операций).
RESTRICTED_KEYS: Mapping[str, Collection[str]] = {
    "cost_margin": (
        "margin_percent",
        "economics",
        "charges",
        "charges_total",
        "approval_steps",
        "landed_cost",
        "gross_profit",
        "cost_price",
    ),
    "supplier_prices": ("offer", "supplier_price", "purchase_price", "unit_cost"),
}


# Одинаковые запросы одной сессии, начатые одновременно, делят один вызов бэкенда. Подсказка потока
# (B5) заставляет браузер перезапросить очередь, карточки, счётчики, уведомления и ленту разом: все
# пять читают одни и те же списки (сделки, согласования, входящие CRM), и без общего вызова каждый
# из них ушёл бы в бэкенд по нескольку раз.
_inflight: dict[str, "asyncio.Future[tuple[Any | None, SourceState]]"] = {}


async def _single_flight(
    key: str, load: Callable[[], Awaitable[tuple[Any | None, SourceState]]]
) -> tuple[Any | None, SourceState]:
    pending = _inflight.get(key)
    if pending is None:
        pending = asyncio.ensure_future(load())
        _inflight[key] = pending

        def _done(task: "asyncio.Future[tuple[Any | None, SourceState]]") -> None:
            _inflight.pop(key, None)
            if not task.cancelled():
                task.exception()  # исключение уйдёт ожидающим; «не извлечено» в журнал не пишем

        pending.add_done_callback(_done)
    # shield: отмена одного запроса (клиент ушёл) не обрывает вызов, на который ждут другие
    return await asyncio.shield(pending)


class Feed:
    """Состояние источников одного запроса и вызовы бэкендов, которые не роняют ответ при сбое."""

    def __init__(self, authed: Authed) -> None:
        self.authed = authed
        self.states: dict[Backend, SourceState] = cast(
            dict[Backend, SourceState], dict(authed.data.sources())
        )
        # Ни одна роль не даёт прав в CRM (например, только «Счета и оплаты»): CRM для агрегатов —
        # `not_applicable`, вызовы в неё не уходят (иначе CRM ответила бы 403).
        if not gives_backend(authed.access, "crm"):
            self.states["crm"] = "not_applicable"

    @property
    def sources(self) -> Sources:
        return Sources(crm=self.states["crm"], erp=self.states["erp"])

    @property
    def fields(self) -> list[str]:
        """Поля с ограничением по объединению ролей (как права операций)."""
        return self.authed.fields

    def usable(self, backend: Backend) -> bool:
        """Вызывать стоит: у сотрудника есть доступ (недоступный сейчас источник пробуем снова)."""
        return self.states[backend] != "not_applicable"

    @property
    def _redis(self) -> Any:
        return self.authed.service.store.redis

    def _key(self, kind: str, backend: Backend, path: str, params: dict[str, Any] | None) -> str:
        query = json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
        return f"feed:{self.authed.sid}:{kind}:{backend}:{path}:{query}"

    async def invalidate(
        self, backend: Backend, path: str, params: dict[str, Any] | None = None
    ) -> None:
        """Сбросить кэш ответа (после изменяющего вызова, который его устарил)."""
        await self._redis.delete(self._key("data", backend, path, params))

    async def get(
        self,
        backend: Backend,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        ttl: int = 0,
        remember_refusal: bool = False,
    ) -> Any | None:
        """GET с токеном сотрудника. Сбой источника — None и `unavailable`; отказ бэкенда 4xx —
        None (журнал).

        `ttl` — секунды жизни ответа в кэше сессии (только успешные ответы, уже без полей с
        ограничением); `remember_refusal` — не повторять запрос минуту после 403.
        """
        if not self.usable(backend):
            return None
        data_key = self._key("data", backend, path, params)
        refusal_key = self._key("refused", backend, path, params)
        if remember_refusal and await self._redis.get(refusal_key):
            return None
        if ttl:
            cached = await self._redis.get(data_key)
            if cached is not None:
                self.states[backend] = "ok"
                return json.loads(cached)
            payload, state = await _single_flight(
                data_key,
                lambda: self._load(backend, path, params, ttl, remember_refusal, data_key),
            )
        else:
            payload, state = await self._load(backend, path, params, 0, remember_refusal, data_key)
        self.states[backend] = state
        return payload

    async def _load(
        self,
        backend: Backend,
        path: str,
        params: dict[str, Any] | None,
        ttl: int,
        remember_refusal: bool,
        data_key: str,
    ) -> tuple[Any | None, SourceState]:
        """Запрос к бэкенду: (ответ или None, состояние источника); успешный ответ — в кэш."""
        try:
            response = await self.authed.call(backend, "GET", path, params=params)
        except PlatformError as exc:
            if exc.status_code == 503:
                log.warning("feed_source_unavailable", backend=backend, path=path)
                return None, "unavailable"
            raise
        if response.status_code >= 400:
            log.warning(
                "feed_source_refused", backend=backend, path=path, status=response.status_code
            )
            if remember_refusal and response.status_code == 403:
                refusal_key = self._key("refused", backend, path, params)
                await self._redis.set(refusal_key, "1", ex=REFUSAL_TTL_SECONDS)
            return None, "ok"
        try:
            payload = response.json()
        except ValueError:
            log.warning("feed_source_bad_json", backend=backend, path=path)
            return None, "unavailable"
        clean = strip_restricted(payload, self.fields, RESTRICTED_KEYS)
        if ttl:
            await self._redis.set(data_key, json.dumps(clean, ensure_ascii=False), ex=ttl)
        return clean, "ok"

    async def send(self, backend: Backend, method: str, path: str) -> int:
        """Изменяющий вызов (отметка «прочитано»): статус ответа бэкенда; сбой источника — ошибка
        503 наверх."""
        response = await self.authed.call(backend, method, path)
        return response.status_code


async def drop_snapshots(redis: Any, sid: str) -> None:
    """Сбросить кэш ответов бэкендов сессии: после подсказки шины (B5) данные свежие, не из кэша."""
    async for key in redis.scan_iter(match=f"feed:{sid}:data:*", count=200):
        await redis.delete(key)


def rows(payload: Any) -> list[dict[str, Any]]:
    """Строки ответа списка: постраничный `{results: [...]}` ERP, `{items: [...]}` CRM или голый
    массив."""
    if isinstance(payload, dict):
        payload = payload.get("results", payload.get("items"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]
