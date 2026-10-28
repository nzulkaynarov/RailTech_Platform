"""След правок справочников и условий закупки из Платформы (D2-3, ревью #299): кто, что и когда изменил.

Те же записи `crm.ActivityLog` через `core.audit.log_admin_action`, что и у соседних справочников ERP: код `admin.<сущность>.<действие>`
(по префиксу `admin.` запись попадает в «Журнал доступа»), снимки `before`/`after` без служебных полей. Цена закупки и ставка
бригады в снимках есть: журнал читает только администратор.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from core.audit import log_admin_action


def _plain(value: Any) -> Any:
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value


def snapshot(instance, fields: tuple[str, ...]) -> dict[str, Any]:
    """Значения полей модели в виде, пригодном для JSON; внешний ключ — по коду или id."""
    out: dict[str, Any] = {}
    for name in fields:
        value = getattr(instance, name, None)
        if hasattr(value, "pk"):
            value = getattr(value, "code", None) or value.pk
        out[name] = _plain(value)
    return out


def record(
    actor,
    *,
    entity: str,
    instance,
    event: str,
    action: str,
    before: dict | None,
    after: dict | None,
    level: str = "INFO",
) -> None:
    """Запись в журнал. Правка без изменений (`before == after`) ничего не пишет."""
    if before is not None and after is not None and before == after:
        return
    log_admin_action(
        entity_type=entity,
        entity_id=instance.pk,
        action=action,
        detail=str(instance)[:200],
        event_code=f"admin.{entity}.{event}",
        event_params={"id": instance.pk},
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        before=before,
        after=after,
        level=level,
    )
