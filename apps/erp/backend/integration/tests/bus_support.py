"""Помощники тестов шины rt_bus в ERP (B3): что опубликовано в outbox и как это проверить по контракту.

Публикация пишет строку `rt_bus_outbox` в транзакцию изменения; тесты читают её, а не мокают шину. Конверт и `data`
библиотека проверяет строго по `packages/contracts/events/` до записи (`EventValidationError`), поэтому событие в outbox уже
соответствует схеме типа; `assert_matches_contract` повторяет проверку независимо — по схемам из каталога контрактов.
"""

from __future__ import annotations

from typing import Any, Optional

from integration.services.events import event_type_name
from rt_bus.django.models import Outbox
from rt_bus.schemas import SchemaRegistry

_registry: Optional[SchemaRegistry] = None


def registry() -> SchemaRegistry:
    global _registry
    if _registry is None:
        _registry = SchemaRegistry()  # каталог — RT_BUS_CONTRACTS_DIR (в образе /opt/rt/contracts/events)
    return _registry


def published(short: Optional[str] = None) -> list[dict[str, Any]]:
    """Конверты из outbox по порядку публикации; `short` — короткое имя типа (`quote.sent`)."""
    rows = Outbox.objects.order_by("created_at", "id")
    if short is not None:
        rows = rows.filter(type=event_type_name(short))
    return [row.envelope for row in rows]


def only(short: str) -> dict[str, Any]:
    """Ровно один конверт типа `short`."""
    found = published(short)
    assert len(found) == 1, f"ожидалось одно событие {short}, опубликовано {len(found)}"
    return found[0]


def types() -> list[str]:
    """Короткие имена опубликованных типов по порядку."""
    prefix, suffix = "uz.railtech.erp.", ".v1"
    return [env["type"][len(prefix) : -len(suffix)] for env in published()]


def reset() -> None:
    Outbox.objects.all().delete()


def assert_matches_contract(envelope: dict[str, Any], *, secret_masked: bool = False) -> None:
    """Конверт и `data` проходят схемы контракта (строго, как у издателя). Для кода акцепта в outbox — маска `***`."""
    errors = registry().validate_envelope(envelope)
    assert not errors, errors
    if secret_masked:
        return  # маска вместо кода не проходит pattern поля code: строгая проверка — на publish, до маскирования
    errors = registry().validate_data(envelope["type"], envelope["data"], tolerant=False)
    assert not errors, errors


def stashed(envelope: dict[str, Any]) -> dict[str, Any]:
    """Секретные значения события из кэша издателя (`{путь: значение}`); нет — пусто (TTL вышел или события без секрета)."""
    from rt_bus.django.stash import DjangoCacheStash

    return dict(DjangoCacheStash().get(envelope["id"]) or {})


def real_data(envelope: dict[str, Any]) -> dict[str, Any]:
    """`data` события так, как оно уйдёт подписчику: маски секретных полей заменены значениями из кэша."""
    from rt_bus.masking import unmask_data

    return unmask_data(envelope["data"], stashed(envelope))
