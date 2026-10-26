"""События EDS в ERP (волна 12, ADR-0015; `packages/contracts/events/eds/`): резолюция, отказ по письму, решение по КП.

* `uz.railtech.eds.letter.resolved.v1` (EDS-01) → задание расчёта по сделке и стадия «Расчёт» (`crm/services/calc_tasks.py`);
* `uz.railtech.eds.letter.rejected.v1` → сделка `CLOSED_LOST` с причиной;
* `uz.railtech.eds.approval.decided.v1` (EDS-03), объект — КП → решение директора на КП
  (`crm/services/eds_quote_approval.py`); решения по документам EDS ERP не касаются.

Сделка письма — `links.erp_deal_id`, иначе `links.erp_request_id` (у ERP заявка и есть сделка: `request.created` несёт
`erp_request_id = id сделки`). Нет ссылки или сделки — пропуск с записью в журнал (`ActivityLog`, уровень WARNING),
не ошибка: повтор такого события ничего бы не изменил. Повтор события — без дублей (идемпотентность — в сервисах).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from crm.models import Deal
from crm.services import calc_tasks, eds_quote_approval

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    applied: bool
    reason: str = ""


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _deal_of(data: dict[str, Any], event: str) -> Optional[Deal]:
    links = data.get("links") or {}
    letter = data.get("letter") or {}
    deal_id = links.get("erp_deal_id") or links.get("erp_request_id")
    deal = Deal.objects.filter(pk=deal_id).first() if deal_id else None
    if deal is None:
        why = "письмо не связано со сделкой ERP" if not deal_id else f"сделки #{deal_id} в ERP нет"
        logger.warning("%s %s: %s — пропуск", event, letter.get("number"), why)
        calc_tasks.deal_log(
            None,
            f"Событие EDS {event} пропущено",
            f"{letter.get('number', '—')}: {why}",
            event_code="eds.letter_skipped",
            event_params={"event": event, "letter_number": letter.get("number"), "erp_deal_id": deal_id},
            level="WARNING",
        )
    return deal


def apply_letter_resolved(data: dict[str, Any], event_id: Optional[UUID] = None) -> Outcome:
    """`letter.resolved` → задание расчёта (исполнители, срок, порог маржи) и сделка в «Расчёт»."""
    deal = _deal_of(data, "letter.resolved")
    if deal is None:
        return Outcome(False, "no_deal")
    letter, resolution = data["letter"], data["resolution"]
    margin = resolution.get("min_margin_pct")
    outcome = calc_tasks.apply_resolution(
        deal,
        eds_letter_id=UUID(letter["eds_letter_id"]),
        letter_number=letter["number"],
        letter_subject=letter.get("subject") or "",
        text=resolution["text"],
        due=date.fromisoformat(resolution["due"]),
        min_margin_pct=Decimal(margin) if margin is not None else None,
        decided_by_crm_user_id=resolution["decided_by"].get("crm_user_id"),
        decided_by_name=resolution["decided_by"].get("full_name") or "",
        decided_at=_when(resolution["decided_at"]),
        assignees=[calc_tasks.Assignment(int(a["crm_user_id"]), a["zone"]) for a in resolution["assignees"]],
        event_id=event_id,
    )
    return Outcome(outcome.changed, "" if outcome.changed else "duplicate")


def apply_letter_rejected(data: dict[str, Any]) -> Outcome:
    """`letter.rejected` → сделка `CLOSED_LOST` с причиной отказа."""
    deal = _deal_of(data, "letter.rejected")
    if deal is None:
        return Outcome(False, "no_deal")
    applied = calc_tasks.apply_letter_rejection(deal, letter_number=data["letter"]["number"], reason=data["reason"])
    return Outcome(applied, "" if applied else "unchanged")


def apply_approval_decided(data: dict[str, Any]) -> Outcome:
    """`approval.decided` по КП → решение директора на КП; прочие объекты маршрутов (документы EDS) — не ERP."""
    approval_object = data["approval"]["object"]
    if approval_object.get("kind") != "quote":
        return Outcome(False, "not_a_quote")
    result = eds_quote_approval.apply_director_decision(
        erp_quote_id=int(approval_object["erp_quote_id"]),
        quote_version=int(approval_object["quote_version"]),
        decision=data["decision"],
        route_status=data["route_status"],
        comment=data.get("comment"),
        outgoing_number=data.get("outgoing_number"),
        channels=data.get("channels"),
        decided_by=data.get("decided_by") or {},
        decided_at=_when(data["decided_at"]),
    )
    return Outcome(result == "applied", result)
