"""Чек-лист одобрения КП (SPEC-v3 §7.3, eds.yaml `ChecklistItem`): визы, маржа ≥ порога резолюции, срок расчёта.

Порог маржи — поле резолюции EDS (владелец — EDS, runbook §2.4): берётся из резолюции письма по этому КП
(`eds_letter_id` события или сделка ERP); `min_margin_pct` из события ERP — только снимок для показа. Одобрение
недоступно, пока красна хотя бы одна **блокирующая** строка (визы, маржа), — проверка на сервере в `approvals.decide`.
Строка «срок» — предупреждение (`blocking=False`): КП, готовое позже срока, директор одобряет, осознанно приняв
опоздание (решение архитектора 2026-10-26, C1-G-1; маршрут получает отметку `approved_late`).
"""

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.models import ApprovalRoute, Letter
from app.schemas.approvals import ChecklistItem, QuoteVisaAuthor
from app.schemas.letters import LetterStatus

DUE_LABEL = "Срок расчёта выдержан"
_VISA_LABELS = {"goods": "Виза снабженца (товары)", "services": "Виза гл. инженера (услуги)"}


def _pct(value: Decimal) -> str:
    return format(value.normalize(), "f")


async def resolution_threshold(session: AsyncSession, route: ApprovalRoute) -> Decimal | None:
    """Минимальная маржа из резолюции EDS по КП; `None` — резолюции нет или ограничение не задано."""
    resolved = Letter.status == LetterStatus.RESOLVED.value
    letter: Letter | None = None
    if route.eds_letter_id is not None:
        letter = (
            await session.execute(select(Letter).where(Letter.id == route.eds_letter_id, resolved))
        ).scalar_one_or_none()
    if letter is None and route.erp_deal_id is not None:
        stmt = select(Letter).where(Letter.erp_deal_id == route.erp_deal_id, resolved)
        letter = (
            await session.execute(stmt.order_by(Letter.resolution_decided_at.desc()).limit(1))
        ).scalar_one_or_none()
    return None if letter is None else letter.resolution_min_margin_pct


def build(snapshot: dict[str, Any], threshold: Decimal | None) -> list[ChecklistItem]:
    """Строки чек-листа по снимку КП и порогу резолюции."""
    items: list[ChecklistItem] = []
    visas = {v["zone"]: v for v in sorted(snapshot.get("visas", []), key=lambda v: v["at"])}
    for zone in ("goods", "services"):
        if zone not in snapshot.get("required_zones", []):
            continue
        visa = visas.get(zone)
        items.append(
            ChecklistItem(
                code=f"visa_{zone}",
                label=_VISA_LABELS[zone],
                ok=visa is not None,
                blocking=True,
                by=QuoteVisaAuthor(**visa["by"]) if visa else None,
                at=dt.datetime.fromisoformat(visa["at"]) if visa else None,
                value=None,
            )
        )
    margin = Decimal(snapshot["margin_pct"])
    if threshold is None:
        ok, value = True, f"{_pct(margin)} % (порог не задан)"
    else:
        ok = margin >= threshold
        value = f"{_pct(margin)} % {'≥' if ok else '<'} {_pct(threshold)} %"
    items.append(
        ChecklistItem(
            code="margin", label="Маржа не ниже порога резолюции", ok=ok, blocking=True, by=None, at=None, value=value
        )
    )
    due = snapshot.get("due")
    if due is None:
        items.append(
            ChecklistItem(code="due", label=DUE_LABEL, ok=True, blocking=False, by=None, at=None, value="срок не задан")
        )
    else:
        ready = clock.company_date(dt.datetime.fromisoformat(snapshot["ready_at"]))
        deadline = dt.date.fromisoformat(due)
        value = f"готово {ready:%d.%m.%Y}, срок {deadline:%d.%m.%Y}"
        items.append(
            ChecklistItem(
                code="due", label=DUE_LABEL, ok=ready <= deadline, blocking=False, by=None, at=None, value=value
            )
        )
    return items


def failed_blocking(items: list[ChecklistItem]) -> list[str]:
    """Коды красных блокирующих строк: пока список не пуст, `approve` недоступно."""
    return [item.code for item in items if item.blocking and not item.ok]


def is_green(items: list[ChecklistItem]) -> bool:
    """Одобрение доступно: все блокирующие строки зелёные (предупреждения не мешают)."""
    return not failed_blocking(items)


def late(items: list[ChecklistItem]) -> ChecklistItem | None:
    """Красная строка «срок» — КП готово позже срока резолюции; `None` — срок выдержан или не задан."""
    return next((item for item in items if item.code == "due" and not item.ok), None)
