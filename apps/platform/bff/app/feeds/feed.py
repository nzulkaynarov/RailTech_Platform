"""Чтение CRM и ERP от имени сотрудника с учётом частичных данных (`sources`).

Агрегаты ходят в источники параллельно (клиенты держат таймаут 3 с, `app/clients/base.py`).
Источник, который не ответил, помечается `unavailable`, а ответ собирается из того, что есть
(02-architecture.md §8). Сотруднику без доступа к ERP источник остаётся `not_applicable`, вызовы
в него не уходят.
"""

from collections.abc import Collection, Mapping
from typing import Any, cast

import structlog

from app.clients.base import Backend
from app.deps import Authed
from app.errors import PlatformError
from app.feeds.models import Sources, SourceState
from app.rbac import strip_restricted
from app.rbac_generated import RoleCode

log = structlog.get_logger()

# Поля ответов ERP с ограничением (platform-rbac.yaml `restricted_fields`): вырезаются из сырого
# ответа до разбора,
# чтобы ни один агрегат не мог вернуть их по ошибке. Роли берутся по объединению (как права
# операций).
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


class Feed:
    """Состояние источников одного запроса и вызовы бэкендов, которые не роняют ответ при сбое."""

    def __init__(self, authed: Authed) -> None:
        self.authed = authed
        self.states: dict[Backend, SourceState] = cast(
            dict[Backend, SourceState], dict(authed.data.sources())
        )

    @property
    def sources(self) -> Sources:
        return Sources(crm=self.states["crm"], erp=self.states["erp"])

    @property
    def roles(self) -> list[RoleCode]:
        return self.authed.roles

    def usable(self, backend: Backend) -> bool:
        """Вызывать стоит: у сотрудника есть доступ (недоступный сейчас источник пробуем снова)."""
        return self.states[backend] != "not_applicable"

    async def get(
        self, backend: Backend, path: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        """GET с токеном сотрудника. Сбой источника — None и `unavailable`; отказ бэкенда 4xx —
        None (журнал)."""
        if not self.usable(backend):
            return None
        try:
            response = await self.authed.call(backend, "GET", path, params=params)
        except PlatformError as exc:
            if exc.status_code == 503:
                self.states[backend] = "unavailable"
                log.warning("feed_source_unavailable", backend=backend, path=path)
                return None
            raise
        self.states[backend] = "ok"
        if response.status_code >= 400:
            log.warning(
                "feed_source_refused", backend=backend, path=path, status=response.status_code
            )
            return None
        try:
            payload = response.json()
        except ValueError:
            self.states[backend] = "unavailable"
            log.warning("feed_source_bad_json", backend=backend, path=path)
            return None
        return strip_restricted(payload, self.roles, RESTRICTED_KEYS)

    async def send(self, backend: Backend, method: str, path: str) -> int:
        """Изменяющий вызов (отметка «прочитано»): статус ответа бэкенда; сбой источника — ошибка
        503 наверх."""
        response = await self.authed.call(backend, method, path)
        return response.status_code


def rows(payload: Any) -> list[dict[str, Any]]:
    """Строки ответа списка: постраничный `{results: [...]}` ERP, `{items: [...]}` CRM или голый
    массив."""
    if isinstance(payload, dict):
        payload = payload.get("results", payload.get("items"))
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]
