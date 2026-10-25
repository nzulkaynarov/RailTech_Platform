"""BFF — подписчик шины rt_bus (B5, ADR-0014): приёмник `POST /bus/v1/events` без базы.

Событие шины превращается в подсказку инвалидации (`app/hub.py`), а не в данные: что изменилось,
браузер узнаёт обычными запросами с проверкой прав. Подписки (типы и адрес) —
`packages/contracts/bus/subscriptions.yaml`, строка `platform-bff`; секреты пар —
`RT_BUS_SECRET_ERP_PLATFORM_BFF`, `RT_BUS_SECRET_CRM_PLATFORM_BFF`, `RT_BUS_SECRET_EDS_PLATFORM_BFF`
из окружения. События EDS (волна 12) приходят, но подсказок пока не дают (`skipped`). Своих событий
BFF не публикует. Снаружи `/bus/*` домена Платформы не публикуется (Caddy отвечает 404).
"""

from fnmatch import fnmatchcase

from rt_bus import BusConfig, Event, HandlerRegistry
from rt_bus.memory import MemoryReceiver

from app.hub import TOPICS, EventHub, Hint

SERVICE = "platform-bff"

# Маски обязаны совпадать с `types` строки platform-bff в subscriptions.yaml (тест test_bus.py).
ERP_EVENTS = "uz.railtech.erp.*.v1"
LEAD_EVENTS = "uz.railtech.crm.lead.*.v1"
USER_EVENTS = "uz.railtech.identity.user.*.v1"
# События EDS (волна 12): подписка в контракте есть, обработчика нет — приёмник отвечает
# 200 `skipped`, подсказок SSE нет (экраны EDS — этап D).
EDS_EVENTS = "uz.railtech.eds.*.v1"
SUBSCRIBED = (ERP_EVENTS, LEAD_EVENTS, USER_EVENTS, EDS_EVENTS)
HANDLED = (ERP_EVENTS, LEAD_EVENTS, USER_EVENTS)

# Что может изменить событие: уведомления, счётчики меню, «Моя очередь», лента «Сегодня».
_TOPICS_BY_MASK: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ERP_EVENTS, TOPICS),
    (LEAD_EVENTS, ("counters", "queue", "activity")),
    (USER_EVENTS, ("counters", "queue")),
)


def topics_for(event_type: str) -> tuple[str, ...]:
    wanted: set[str] = set()
    for mask, topics in _TOPICS_BY_MASK:
        if fnmatchcase(event_type, mask):
            wanted.update(topics)
    return tuple(t for t in TOPICS if t in wanted)


def create_receiver(hub: EventHub) -> MemoryReceiver:
    """Приёмник шины BFF: обработчик публикует подсказку в Redis.

    Сбой Redis — 503, издатель повторит доставку по расписанию.
    """
    registry = HandlerRegistry()

    async def on_event(event: Event) -> None:
        await hub.publish(Hint(topics_for(event.type), event.type))

    for mask in HANDLED:
        registry.add(mask, on_event)
    return MemoryReceiver(BusConfig(service=SERVICE), registry=registry)
