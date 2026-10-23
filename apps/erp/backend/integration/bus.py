"""Шина событий rt_bus в ERP (B3, ADR-0014, CONTRACTS §9): одна `DjangoBus` на процесс.

Что здесь:
- `get_bus()` — шина сервиса `erp`: outbox и inbox в БД ERP (приложение `rt_bus`), код акцепта в outbox только маской,
  значение — в кэше (`DjangoCacheStash`); раскладку и доставку ведёт Celery (`core/celery.py`, расписание Beat);
- `pair_secrets` — поставщик секретов пары «издатель → подписчик» (L12): `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` из окружения,
  если задан; иначе для пары CRM ↔ ERP — вывод из секрета вебхуков сопряжения (каждого действующего, для ротации).

События публикует сервисный слой (`integration/services/events.py`) внутри `transaction.atomic()` изменения; чужие события
принимает `POST /bus/v1/events` (`core/urls.py`), обрабатывает `integration/bus_handlers.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from typing import Optional

from rt_bus import BusConfig, default_registry, env_secrets
from rt_bus.django.bus import DjangoBus
from rt_bus.django.stash import DjangoCacheStash

from core.cache import fail_closed

from .bus_http import build_http_client
from .services import credentials

logger = logging.getLogger(__name__)

#: Имя сервиса в шине: `source` = `rt://erp`, секреты пар `RT_BUS_SECRET_ERP_*` и `RT_BUS_SECRET_*_ERP`.
SERVICE = "erp"
#: Пара сервисов, секрет которой выводится из секрета вебхуков сопряжения (L12).
PAIRED_SERVICE = "crm"

_lock = threading.Lock()
_bus: Optional[DjangoBus] = None


class FailClosedCacheStash(DjangoCacheStash):
    """Кэш секретных полей события (код акцепта), у которого запись при недоступном Redis не «молчит» (S0-2, ADR-0013 п. 5).

    Кэш ERP при отказе отвечает «пусто» (`core.cache.ResilientRedisCache`): обычная запись пропала бы без следа, а событие
    с кодом ушло бы в outbox маской, когда настоящего значения уже негде взять. Поэтому запись идёт под `fail_closed()`:
    недоступный кэш — `CacheUnavailable` (503) наружу, публикация и вместе с ней изменение откатываются, события без секрета
    не бывает. Чтение при доставке — библиотечное (см. `docs/runbooks/rt-bus-erp.md`).
    """

    def put(self, event_id, values):
        with fail_closed():
            super().put(event_id, values)


def derive_pair_secret(webhook_secret: str, publisher: str, subscriber: str) -> str:
    """Направленный секрет пары (L12): `hex(HMAC-SHA256(webhook_secret, "rt-bus/v1/{publisher}->{subscriber}"))`.

    Секрет вебхуков по шине не ходит и в подписи не участвует напрямую; обе стороны считают пару сами.
    """
    message = f"rt-bus/v1/{publisher}->{subscriber}".encode()
    return hmac.new(webhook_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def pair_secrets(publisher: str, subscriber: str) -> list[str]:
    """Действующие секреты пары, первый подписывает (L4, L12).

    Окружение `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` главнее. Нет — для пары CRM ↔ ERP секрет выводится из каждого
    действующего секрета вебхуков сопряжения (БД, иначе `ERP_WEBHOOK_SECRET`); для остальных пар (platform-bff, заглушки,
    коннекторы) без окружения секрета нет — доставка откладывается, а не уходит неподписанной.
    """
    from_env = env_secrets(publisher, subscriber)
    if from_env:
        return from_env
    if {publisher, subscriber} == {SERVICE, PAIRED_SERVICE}:
        return [derive_pair_secret(secret, publisher, subscriber) for secret in credentials.webhook_secrets()]
    return []


def build_bus() -> DjangoBus:
    """Новая шина ERP с очередью Celery (`core.celery.bus_tasks`); обычному коду нужен `get_bus()`."""
    from core.celery import bus_tasks

    config = BusConfig(service=SERVICE, secrets=pair_secrets)
    bus = DjangoBus(
        config,
        registry=default_registry,
        http=build_http_client(config.http_timeout),
        stash=FailClosedCacheStash(),
        enqueue=bus_tasks.enqueue,
        wakeup=bus_tasks.wakeup,
    )
    return bus


def get_bus() -> DjangoBus:
    """Шина процесса: создаётся при первом обращении, обработчики регистрируются на `ready()` приложения `integration`."""
    global _bus
    if _bus is None:
        with _lock:
            if _bus is None:
                _bus = build_bus()
    return _bus


def reset_bus() -> None:
    """Забыть созданную шину (тесты, смена настроек): следующий `get_bus()` соберёт её заново."""
    global _bus
    with _lock:
        _bus = None
