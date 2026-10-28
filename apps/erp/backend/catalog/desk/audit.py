"""След правок справочников и условий закупки из Платформы (D2-3, ревью #299): кто, что и когда изменил.

Те же записи `crm.ActivityLog` через `core.audit.log_admin_action`, что и у соседних справочников ERP: код `admin.<сущность>.<действие>`
(по префиксу `admin.` запись попадает в «Журнал доступа»), снимки `before`/`after` без служебных полей. Цена закупки и ставка
бригады в снимки не попадают: журнал читает администратор, у которого нет `supplier_prices` и `cost_margin`, поэтому
закрытые поля (`masked`) пишутся только фактом изменения.
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


CHANGED = "изменено"
HIDDEN = "скрыто"


def _mask(before: dict | None, after: dict | None, masked: tuple[str, ...]) -> tuple[dict | None, dict | None]:
    """Закрытые поля: значения заменяются на «изменено» (если поменялись) или «скрыто»; сравнение уже сделано по настоящим."""
    if not masked:
        return before, after
    out_before = None if before is None else dict(before)
    out_after = None if after is None else dict(after)
    for name in masked:
        changed = (before or {}).get(name) != (after or {}).get(name)
        if out_before is not None and name in out_before:
            out_before[name] = HIDDEN
        if out_after is not None and name in out_after:
            out_after[name] = CHANGED if changed else HIDDEN
    return out_before, out_after


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
    masked: tuple[str, ...] = (),
    detail: str | None = None,
) -> None:
    """Запись в журнал. Правка без изменений (`before == after`) ничего не пишет; `masked` — поля без значений."""
    if before is not None and after is not None and before == after:
        return
    before, after = _mask(before, after, masked)
    log_admin_action(
        entity_type=entity,
        entity_id=instance.pk,
        action=action,
        detail=(detail if detail is not None else str(instance))[:200],
        event_code=f"admin.{entity}.{event}",
        event_params={"id": instance.pk},
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        before=before,
        after=after,
        level=level,
    )
