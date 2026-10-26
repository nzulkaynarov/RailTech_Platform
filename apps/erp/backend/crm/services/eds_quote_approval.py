"""Одобрение КП директором через маршрут EDS (EDS-03, ADR-0015, runbook волны 12 §2.4–§2.5, решение §4 п. 3).

* `request_director_approval` — визы собраны (или проверяющих нет): КП получает номер (КП-…, коммерческий номер ERP) и
  новую редакцию `eds_revision`, ERP публикует `uz.railtech.erp.quote.ready_for_approval.v1` в транзакции изменения
  (откат — события нет). Снимок для маршрута: суммы, маржа, визы по зонам резолюции, порог маржи и срок из задания
  расчёта (`CalcTask`, проекция резолюции EDS — владелец порога EDS). КП остаётся «На утверждении».
* `apply_director_decision` — `eds.approval.decided` по КП: approve — ИСХ-номер EDS на КП, каналы отправки,
  «Готово к отправке» (отправка клиенту разблокирована); return — черновик с комментарием директора (правка и повторная
  отправка — новая редакция и новое событие); reject — КП отклонено. Идемпотентно: решение по другой редакции —
  устаревшее (запись в журнал КП, без изменений), повтор применённого решения — без изменений.
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from ..constants import QuoteStatusCode
from ..models import Quote
from ..models.approvals import StepParticipation, StepStatus
from . import calc_tasks

logger = logging.getLogger(__name__)

#: Решение EDS → (состояние закрытого маршрута в событии, статус КП после решения).
DECISIONS = {
    "approve": ("approved", QuoteStatusCode.READY_TO_SEND),
    "return": ("returned", QuoteStatusCode.DRAFT),
    "reject": ("rejected", QuoteStatusCode.REJECTED),
}

_CENT = Decimal("0.01")
#: Маржа КП в событии — строка `-?\d{1,3}(\.\d{1,2})?`: убыток глубже −999,99 % показываем как −999,99 %.
_MARGIN_LIMIT = Decimal("999.99")


def _iso(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def _amount(value: Any) -> str:
    return f"{Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP):.2f}"


def _margin(value: Any) -> str:
    pct = Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return f"{max(-_MARGIN_LIMIT, min(_MARGIN_LIMIT, pct)):.2f}"


def _threshold(value: Optional[Decimal]) -> Optional[str]:
    """Порог маржи резолюции (`MarginPct`: 0–100, до двух знаков) строкой."""
    if value is None:
        return None
    return f"{Decimal(value).quantize(_CENT):.2f}"


def _crm_user_ids(user_ids: set[int]) -> dict[int, int]:
    from integration.models import CrmUserMapping

    return dict(CrmUserMapping.objects.filter(user_id__in=user_ids).values_list("user_id", "crm_user_id"))


def _person(user, crm_ids: dict[int, int]) -> dict[str, Any]:
    name = (user.get_full_name() or user.email or "").strip() or f"Сотрудник #{user.pk}"
    return {"crm_user_id": crm_ids.get(user.pk), "full_name": name[:255]}


def _visas(quote: Quote, task, ready_at: datetime) -> list[dict[str, Any]]:
    """Визы по зонам резолюции: пройденные шаги проверяющих-исполнителей и зона автора КП (он визирует отправкой)."""
    steps = list(
        quote.approval_steps.filter(participation=StepParticipation.APPROVER, status=StepStatus.APPROVED)
        .exclude(acted_by__isnull=True)
        .select_related("acted_by")
        .order_by("-decided_at", "-id")  # каждый круг визирует заново: в снимок — последняя виза человека
    )
    people = [(step.acted_by, step.decided_at or ready_at) for step in steps]
    if quote.prepared_by_id:
        people.append((quote.prepared_by, ready_at))
    crm_ids = _crm_user_ids({user.pk for user, _ in people})
    visas: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for user, at in people:
        for zone in calc_tasks.visa_zones_of(task, crm_ids.get(user.pk)):
            if (zone, user.pk) in seen:
                continue
            seen.add((zone, user.pk))
            visas.append({"zone": zone, "by": _person(user, crm_ids), "at": _iso(at)})
    return visas


def build_ready_payload(quote: Quote, *, ready_at: datetime) -> dict[str, Any]:
    """`payload` события `quote.ready_for_approval` (`QuoteReadyForApproval` в `events/erp/_defs.v1.json`)."""
    from portal import projections

    from .quotes.pricing import compute_quote_economics

    task = calc_tasks.latest_task(quote.deal_id)
    economics = compute_quote_economics(quote)
    payload: dict[str, Any] = {
        "erp_quote_id": quote.pk,
        "number": quote.number,
        "version": quote.eds_revision,
        "total": _amount(quote.total_incl_vat),
        "currency": projections.currency_code(quote.quote_currency).upper(),
        "cost": _amount(economics.get("total_landed_cost")),
        "margin_amount": _amount(economics.get("gross_profit")),
        "margin_pct": _margin(economics.get("gross_margin_percent")),
        "min_margin_pct": _threshold(task.min_margin_pct) if task else None,
        "required_zones": calc_tasks.required_visa_zones(task),
        "visas": _visas(quote, task, ready_at),
        "due": task.due.isoformat() if task else None,
        "ready_at": _iso(ready_at),
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "eds_letter_id": str(task.eds_letter_id) if task else None,
    }
    company = quote.deal.company
    if company is not None and company.name:
        payload["client_name"] = company.name[:255]
    return payload


_DECISION_FIELDS = ["director_decision", "director_comment", "director_decided_at", "outgoing_number", "send_channels"]


@transaction.atomic
def request_director_approval(quote: Quote, actor) -> Quote:
    """КП → директору: номер КП, новая редакция и событие `quote.ready_for_approval` в этой транзакции.

    Вызывают отправка на согласование без проверяющих и последняя виза (`approvals.act_on_step`). Переданный объект КП
    получает новые значения полей (номер, редакция). КП без компании клиента сюда не попадает (гейт отправки).
    """
    from integration.services import events

    from .numbering import next_document_number
    from .quotes._shared import _log_quote

    locked = (
        Quote.objects.select_for_update(of=("self",))
        .select_related("deal", "deal__company", "deal__stage", "status", "quote_currency", "seller_company")
        .get(pk=quote.pk)
    )
    if not locked.deal.company_id:
        raise ValueError("QUOTE_CLIENT_REQUIRED")
    if not locked.number:
        locked.number = next_document_number("KP", "КП", locked.seller_company)
    locked.eds_revision += 1
    locked.director_decision = ""
    locked.director_comment = ""
    locked.director_decided_at = None
    locked.outgoing_number = ""
    locked.send_channels = []
    changed = ["number", "eds_revision", *_DECISION_FIELDS]
    locked.save(update_fields=[*changed, "updated_at"])
    for name in [*changed, "updated_at"]:
        setattr(quote, name, getattr(locked, name))

    payload = build_ready_payload(locked, ready_at=timezone.now())
    events.publish_quote_ready_for_approval(locked, payload, actor=events.build_actor(user=actor))
    _log_quote(
        locked,
        actor,
        "КП передано директору на одобрение",
        f"КП {locked.number} (редакция {locked.eds_revision}) → маршрут одобрения EDS",
        event_code="quote.sent_to_director",
        event_params={"number": locked.number, "revision": locked.eds_revision},
    )
    return quote


def _erp_user(crm_user_id: Optional[int]):
    if not crm_user_id:
        return None
    from integration.models import CrmUserMapping

    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    return mapping.user if mapping else None


@transaction.atomic
def apply_director_decision(
    *,
    erp_quote_id: int,
    quote_version: int,
    decision: str,
    route_status: str,
    comment: Optional[str],
    outgoing_number: Optional[str],
    channels: Optional[list[str]],
    decided_by: dict[str, Any],
    decided_at: datetime,
) -> str:
    """Применить решение директора из EDS к КП. Возвращает исход: applied, duplicate, stale, ignored, route_open,
    unknown_quote (исход не ошибка — повторять событие незачем)."""
    from .approvals import _link, _notify_user, _set_status
    from .quotes._shared import _log_quote

    quote = (
        Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").filter(pk=erp_quote_id).first()
    )
    if quote is None:
        logger.warning("approval.decided: КП #%s в ERP нет — решение пропущено", erp_quote_id)
        return "unknown_quote"
    if decision not in DECISIONS or route_status == "open":
        return "route_open"  # промежуточный шаг маршрута: КП ждёт закрытия маршрута
    actor = _erp_user(decided_by.get("crm_user_id"))
    director = decided_by.get("full_name") or ""
    params = {"number": quote.number or quote.id, "decision": decision, "version": quote_version}
    if quote_version != quote.eds_revision:
        _log_quote(
            quote,
            actor,
            "Решение директора по устаревшей редакции КП не применено",
            f"{director}: {decision} по редакции {quote_version}, действующая — {quote.eds_revision}",
            event_code="quote.director_decision_stale",
            event_params={**params, "current_revision": quote.eds_revision},
        )
        return "stale"
    if quote.director_decision == decision:
        return "duplicate"
    status_code = quote.status.code if quote.status_id else ""
    if status_code != QuoteStatusCode.PENDING_APPROVAL:
        _log_quote(
            quote,
            actor,
            "Решение директора не применено: КП не ждёт одобрения",
            f"{director}: {decision}; статус КП — {status_code or '—'}",
            event_code="quote.director_decision_ignored",
            event_params={**params, "status_code": status_code},
        )
        return "ignored"

    quote.approval_steps.filter(status=StepStatus.PENDING).exclude(participation=StepParticipation.INFORMED).update(
        status=StepStatus.RECALLED
    )
    quote.director_decision = decision
    quote.director_comment = comment or ""
    quote.director_decided_at = decided_at
    if decision == "approve":
        quote.outgoing_number = outgoing_number or ""
        quote.send_channels = list(channels or [])
    quote.save(update_fields=[*_DECISION_FIELDS, "updated_at"])
    _set_status(quote, DECISIONS[decision][1])

    number = quote.number or quote.id
    if decision == "approve":
        _log_quote(
            quote,
            actor,
            "КП одобрено директором",
            f"{director}: {quote.outgoing_number or 'без ИСХ-номера'} → «Готово к отправке»",
            event_code="quote.director_approved",
            event_params={"number": number, "outgoing_number": quote.outgoing_number, "channels": quote.send_channels},
        )
        _notify_user(
            quote.prepared_by_id,
            "КП одобрено директором",
            f"КП #{number} одобрено ({quote.outgoing_number or '—'}) — можно отправлять клиенту.",
            type_code="SUCCESS",
            link=_link(quote),
            event_code="quote.director_approved",
            event_params={"number": number, "outgoing_number": quote.outgoing_number},
        )
    elif decision == "return":
        _log_quote(
            quote,
            actor,
            "КП возвращено директором на доработку",
            f"{director}: {quote.director_comment}",
            event_code="quote.director_returned",
            event_params={"number": number, "comment": quote.director_comment},
        )
        _notify_user(
            quote.prepared_by_id,
            "КП возвращён на доработку",
            f"КП #{number} возвращено директором на доработку. {quote.director_comment}".strip(),
            type_code="WARNING",
            link=_link(quote),
            event_code="quote.approval_returned",
            event_params={"number": number, "comment": quote.director_comment},
        )
    else:
        _log_quote(
            quote,
            actor,
            "КП отклонено директором",
            f"{director}: {quote.director_comment}",
            event_code="quote.director_rejected",
            event_params={"number": number, "comment": quote.director_comment},
        )
        _notify_user(
            quote.prepared_by_id,
            "КП отклонено директором",
            f"КП #{number} отклонено директором. {quote.director_comment}".strip(),
            type_code="WARNING",
            link=_link(quote),
            event_code="quote.director_rejected",
            event_params={"number": number, "comment": quote.director_comment},
        )
    return "applied"
