"""Чек-лист одобрения КП (SPEC-v3 §7.3, eds.yaml `ChecklistItem`): визы, маржа ≥ порога резолюции, срок расчёта.

Порог маржи — поле резолюции EDS (владелец — EDS, runbook §2.4): берётся из резолюции письма по этому КП
(`eds_letter_id` события или сделка ERP); `min_margin_pct` из события ERP — только снимок для показа. Одобрение
недоступно, пока хотя бы одна строка красная, — проверка на сервере в `approvals.decide`.
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
        ChecklistItem(code="margin", label="Маржа не ниже порога резолюции", ok=ok, by=None, at=None, value=value)
    )
    due = snapshot.get("due")
    if due is None:
        items.append(
            ChecklistItem(code="due", label="Срок расчёта выдержан", ok=True, by=None, at=None, value="срок не задан")
        )
    else:
        ready = clock.company_date(dt.datetime.fromisoformat(snapshot["ready_at"]))
        deadline = dt.date.fromisoformat(due)
        value = f"готово {ready:%d.%m.%Y}, срок {deadline:%d.%m.%Y}"
        items.append(
            ChecklistItem(
                code="due", label="Срок расчёта выдержан", ok=ready <= deadline, by=None, at=None, value=value
            )
        )
    return items


def is_green(items: list[ChecklistItem]) -> bool:
    return all(item.ok for item in items)
