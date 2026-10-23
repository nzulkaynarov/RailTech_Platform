"""Секреты пар шины CRM ↔ ERP (решение L12, CONTRACTS §9.4).

Секрет пары «издатель → подписчик» — переменная `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>`, если задана.
Иначе, только для пар `crm` ↔ `erp`, он выводится из секрета вебхуков сопряжения (тот, что хранят
обе системы, «Подключения» → ERP):
`hex(HMAC-SHA256(webhook_secret, "rt-bus/v1/<издатель>-><подписчик>"))`.
Выводится из каждого действующего секрета (текущего и предыдущего), так что ротация без простоя
работает и на шине. Прочие подписчики (platform-bff, заглушки, коннекторы) — только из окружения.

Секреты вебхуков лежат в БД (шифрованно), а поставщик секретов шины синхронный, поэтому значения
перечитываются в кэш перед каждым приёмом и доставкой (`SecretCache.refresh`): смена или снятие
секрета в «Подключениях» действует на шине сразу, без перезапуска.
"""

import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable, Sequence

import structlog
from rt_bus.signing import env_secrets

logger = structlog.get_logger(__name__)

PAIR = frozenset({"crm", "erp"})
#: 0 — перечитывать при каждом приёме и доставке (чтение из БД дёшево, ротация действует сразу).
CACHE_TTL_S = 0.0

#: Читает действующие секреты вебхуков сопряжения: текущий, затем предыдущий.
WebhookSecretsLoader = Callable[[], Awaitable[Sequence[str]]]


def derive_pair_secret(webhook_secret: str, publisher: str, subscriber: str) -> str:
    """Направленный секрет пары из секрета вебхуков: обе стороны считают его сами (L12)."""
    message = f"rt-bus/v1/{publisher}->{subscriber}".encode()
    return hmac.new(webhook_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class SecretCache:
    """Поставщик секретов шины (`BusConfig.secrets`) с кэшем секретов вебхуков сопряжения."""

    def __init__(
        self,
        loader: WebhookSecretsLoader | None = None,
        *,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl_s = ttl_s
        self._clock = clock
        self._webhook: tuple[str, ...] = ()
        self._loaded_at: float | None = None

    def __call__(self, publisher: str, subscriber: str) -> list[str]:
        explicit = env_secrets(publisher, subscriber)
        if explicit:
            return explicit
        if {publisher, subscriber} != PAIR or publisher == subscriber:
            return []
        return [derive_pair_secret(secret, publisher, subscriber) for secret in self._webhook]

    def set_webhook_secrets(self, secrets: Sequence[str]) -> None:
        """Подставить секреты вебхуков напрямую (тесты, прогрев)."""
        self._webhook = tuple(dict.fromkeys(s for s in secrets if s))
        self._loaded_at = self._clock()

    async def refresh(self, *, force: bool = False) -> None:
        """Перечитать секреты вебхуков, если кэш старше срока; сбой чтения оставляет прежние."""
        if self._loader is None:
            return
        now = self._clock()
        if not force and self._loaded_at is not None and now - self._loaded_at < self._ttl_s:
            return
        try:
            self.set_webhook_secrets(await self._loader())
        except Exception:
            logger.warning("rt_bus_webhook_secrets_unavailable", exc_info=True)
