"""BFF — подписчик шины rt_bus (B5, ADR-0014): приёмник `POST /bus/v1/events` без базы.

Событие шины превращается в подсказку инвалидации (`app/hub.py`), а не в данные: что изменилось,
браузер узнаёт обычными запросами с проверкой прав. Подписки (типы и адрес) —
`packages/contracts/bus/subscriptions.yaml`, строка `platform-bff`; секреты пар —
`RT_BUS_SECRET_ERP_PLATFORM_BFF`, `RT_BUS_SECRET_CRM_PLATFORM_BFF`, `RT_BUS_SECRET_EDS_PLATFORM_BFF`
из окружения. События EDS (волна 12) приходят, но подсказок пока не дают (`skipped`). Своих событий
BFF не публикует. Снаружи `/bus/*` домена Платформы не публикуется (Caddy отвечает 404).
"""

from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Any

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

# Новое сообщение в переписке лида (D1-1): очередь «Ждут ответа» и открытая лента; если лид не у
# бота (`handoff`), ещё бейдж «Ждут ответа» и «Моя очередь» (непрочитанное). Диалог с ботом
# счётчиков не меняет; ленту «Сегодня» сообщение не меняет.
MESSAGE_ADDED = "uz.railtech.crm.lead.message_added.v1"
_MESSAGE_TOPICS: tuple[str, ...] = ("messages",)
_HANDOFF_MESSAGE_TOPICS: tuple[str, ...] = ("counters", "queue", "messages")

# Что может изменить событие: уведомления, счётчики меню, «Моя очередь», лента «Сегодня», переписка
# (новая передача, «Забрать», смена ответственного — тоже «Ждут ответа»).
_TOPICS_BY_MASK: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ERP_EVENTS, ("notifications", "counters", "queue", "activity")),
    (LEAD_EVENTS, ("counters", "queue", "activity", "messages")),
    (USER_EVENTS, ("counters", "queue")),
)


def topics_for(event_type: str, data: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    if event_type == MESSAGE_ADDED:
        handoff = bool((data or {}).get("handoff", True))
        exact = _HANDOFF_MESSAGE_TOPICS if handoff else _MESSAGE_TOPICS
        return tuple(t for t in TOPICS if t in exact)
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
        await hub.publish(Hint(topics_for(event.type, event.data), event.type))

    for mask in HANDLED:
        registry.add(mask, on_event)
    return MemoryReceiver(BusConfig(service=SERVICE), registry=registry)
