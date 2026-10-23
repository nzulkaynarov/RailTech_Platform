"""Шина процесса CRM: `AsyncBus` сервиса `crm`, поставщик секретов, постановка обработки в очередь.

Публикация идёт через `get_bus()`: в API это шина контейнера приложения (`install` в lifespan), в
воркере и CLI — контейнер процесса (`get_container()`). Для `publish` нужны только схемы и настройки
шины — сессию, в которой пишется outbox, передаёт вызывающий.

`CrmBus` дополняет библиотечный `AsyncBus` двумя вещами, которые библиотека знать не может:
* перед приёмом и доставкой перечитывает секреты вебхуков сопряжения (L12, `app.bus.secrets`);
* после обработки записи inbox отправляет сообщения Telegram, посчитанные обработчиком, —
  уже после коммита (`ErpEventNotices.deliver`).
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from rt_bus import BusConfig
from rt_bus.receiver import ReceiveResult
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.secrets import SecretCache, WebhookSecretsLoader

if TYPE_CHECKING:
    from app.container import Container

SERVICE = "crm"

AfterProcessed = Callable[[str], Awaitable[object]]


class CrmBus(AsyncBus):
    def __init__(
        self,
        config: BusConfig,
        sessions: Callable[[], AsyncSession],
        *,
        secret_cache: SecretCache,
        after_processed: AfterProcessed | None = None,
        enqueue: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        super().__init__(config, sessions, enqueue=enqueue)
        self.secret_cache = secret_cache
        self._after_processed = after_processed

    async def receive(self, headers: Mapping[str, str], body: bytes) -> ReceiveResult:
        await self.secret_cache.refresh()
        return await super().receive(headers, body)

    async def deliver(self, limit: int | None = None) -> Any:
        await self.secret_cache.refresh()
        return await super().deliver(limit)

    async def process_inbox(self, event_id: Any) -> str | None:
        status = await super().process_inbox(event_id)
        if status == "processed" and self._after_processed is not None:
            await self._after_processed(str(event_id))
        return status


def build_bus(
    sessions: Callable[[], AsyncSession],
    webhook_secrets: WebhookSecretsLoader | None,
    *,
    after_processed: AfterProcessed | None = None,
    enqueue: Callable[[str], Awaitable[Any]] | None = None,
) -> CrmBus:
    """Шина CRM. Каталог схем и файл подписок — из `RT_BUS_CONTRACTS_DIR` / `RT_BUS_SUBSCRIPTIONS`
    (в образе — `/opt/rt/contracts`, в репозитории библиотека находит `packages/contracts` сама).
    """
    secrets = SecretCache(webhook_secrets)
    return CrmBus(
        BusConfig(service=SERVICE, secrets=secrets),
        sessions,
        secret_cache=secrets,
        after_processed=after_processed,
        enqueue=enqueue,
    )


_override: AsyncBus | None = None
_container: "Container | None" = None


def install(container: "Container | None") -> None:
    """Сделать шину этого контейнера шиной процесса (lifespan API); `None` — снять."""
    global _container
    _container = container


def set_bus(bus: AsyncBus | None) -> None:
    """Подменить шину процесса (тесты: стенд публикации, сбой публикации)."""
    global _override
    _override = bus


def current_container() -> "Container":
    if _container is not None:
        return _container
    from app.container import get_container

    return get_container()


def get_bus() -> AsyncBus:
    return _override if _override is not None else current_container().bus
