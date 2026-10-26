"""Сделка по решениям директора в EDS (EDS-01, runbook волны 12 §2.4): резолюция → задание расчёта, отказ → LOST.

* `apply_resolution` — `eds.letter.resolved`: задание расчёта по сделке (`CalcTask`, одно на письмо): исполнители с зоной,
  срок, порог маржи; сделка переходит в «Расчёт» (FSM `CALCULATING`, в контракте — `quoting`). Повтор того же события —
  без изменений; новая резолюция того же письма обновляет задание. Сотрудник CRM без пользователя ERP (`CrmUserMapping`) —
  исполнитель без пользователя и предупреждение в журнале сделки, не ошибка.
* `apply_letter_rejection` — `eds.letter.rejected`: сделка в `CLOSED_LOST` с причиной (обычный переход FSM: событие
  `deal.lost` с `lost_reason` публикуется в той же транзакции) — только до отправки КП клиенту; позже — WARNING в журнал.
  Сделка уже проиграна — без изменений.

Вызываются обработчиками шины (`integration/services/eds_inbound.py`) в транзакции записи inbox: исключение — автоповтор
шины, поэтому «нельзя применить» (стадия не пускает, сделка закрыта) — запись в журнал, а не исключение.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional
from uuid import UUID

from django.db import transaction

from ..constants import DealStageCode
from ..models import ActivityLog, CalcTask, CalcTaskAssignee
from ..models import CalcZone as Zone
from ..models import Deal

logger = logging.getLogger(__name__)

#: Стадии FSM, из которых резолюция переводит сделку в «Расчёт». Дальше сделка уже ушла (КП отправлено, договор) или
#: закрыта (выиграна, проиграна) — резолюция её не двигает и не переоткрывает: запись WARNING в журнал.
_BEFORE_CALCULATION = {
    DealStageCode.DRAFT,
    DealStageCode.KYC_PENDING,
    DealStageCode.RFQ_OPEN,
    DealStageCode.SOURCING,
}
#: Стадии, в которых отказ директора по письму закрывает сделку (до отправки КП клиенту). После отправки КП судьбу
#: сделки решает клиент и менеджер — отказ по письму пишется в журнал WARNING, сделка не закрывается.
_REJECTABLE = _BEFORE_CALCULATION | {DealStageCode.CALCULATING}


@dataclass
class Assignment:
    crm_user_id: int
    zone: str


@dataclass
class ResolutionOutcome:
    task: CalcTask
    created: bool
    changed: bool
    unknown_crm_user_ids: list[int] = field(default_factory=list)


def deal_log(
    deal: Optional[Deal],
    action: str,
    detail: str,
    *,
    event_code: str,
    event_params: Optional[dict] = None,
    level: str = "INFO",
) -> ActivityLog:
    """Строка журнала сделки от имени системы (решение пришло из EDS, пользователя ERP за ним нет)."""
    return ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=None,
        level=level,
        entity_type="deal" if deal is not None else "eds_letter",
        entity_id=deal.id if deal is not None else None,
        deal=deal,
        company_id=deal.company_id if deal is not None else None,
        event_code=event_code,
        event_params=event_params or {},
    )


def latest_task(deal_id: Optional[int]) -> Optional[CalcTask]:
    """Действующее задание расчёта сделки — по последней резолюции."""
    if not deal_id:
        return None
    return CalcTask.objects.filter(deal_id=deal_id).order_by("-decided_at", "-id").first()


def visa_zones_of(task: Optional[CalcTask], crm_user_id: Optional[int]) -> list[str]:
    """Зоны виз (goods, services), в которых сотрудник (по `crm_user_id`: исполнителя могли завести в ERP позже
    резолюции) — исполнитель задания."""
    if task is None or not crm_user_id:
        return []
    zones = task.assignees.filter(crm_user_id=crm_user_id, zone__in=[Zone.GOODS, Zone.SERVICES]).values_list(
        "zone", flat=True
    )
    return sorted(set(zones))


def visa_assignee_user_ids(task: Optional[CalcTask]) -> list[int]:
    """Пользователи ERP — исполнители зон goods/services задания (по порядку назначения, без повторов). Исполнителя,
    заведённого в ERP после резолюции, привязывает здесь же по `CrmUserMapping`."""
    if task is None:
        return []
    rows = list(task.assignees.filter(zone__in=[Zone.GOODS, Zone.SERVICES]).order_by("id"))
    missing = _users_by_crm_id({row.crm_user_id for row in rows if row.user_id is None})
    for row in rows:
        if row.user_id is None and row.crm_user_id in missing:
            row.user_id = missing[row.crm_user_id]
            row.save(update_fields=["user"])
    return list(dict.fromkeys(row.user_id for row in rows if row.user_id))


def required_visa_zones(task: Optional[CalcTask]) -> list[str]:
    """Чьи визы нужны расчёту: зоны goods/services исполнителей резолюции."""
    if task is None:
        return []
    zones = task.assignees.filter(zone__in=[Zone.GOODS, Zone.SERVICES]).values_list("zone", flat=True)
    return sorted(set(zones))


def _users_by_crm_id(crm_user_ids: Iterable[int]) -> dict[int, int]:
    from integration.models import CrmUserMapping

    rows = CrmUserMapping.objects.filter(crm_user_id__in=list(crm_user_ids), user__is_active=True)
    return dict(rows.values_list("crm_user_id", "user_id"))


def _notify_assignee(user_id: int, deal: Deal, task: CalcTask) -> None:
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    notification = Notification.objects.create(
        user_id=user_id,
        type=NotificationType.objects.filter(code="INFO").first(),
        title="Задание на расчёт",
        message=f"Резолюция по {task.letter_number}: расчёт по заявке #{deal.id} до {task.due.isoformat()}.",
        link=f"#deal/{deal.id}",
        event_code="deal.calc_assigned",
        event_params={"deal_id": deal.id, "letter_number": task.letter_number, "due": task.due.isoformat()},
    )
    push_notification_ws(notification)


def _move_to_calculation(deal: Deal, letter_number: str) -> None:
    """Сделка → «Расчёт». Уже там — ничего; ушла дальше (КП отправлено, договор, выиграна) — запись в журнал."""
    from .deals import transition_deal_stage

    current = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    if current == DealStageCode.CALCULATING:
        return
    if current not in _BEFORE_CALCULATION:
        deal_log(
            deal,
            "Стадия не изменена резолюцией",
            f"Резолюция по {letter_number}: сделка на стадии {current}, в «Расчёт» не переводится",
            event_code="deal.calc_stage_kept",
            event_params={"letter_number": letter_number, "stage_code": current},
            level="WARNING",
        )
        return
    reason = f"Резолюция {letter_number}"
    error = None
    if current in (DealStageCode.DRAFT, DealStageCode.KYC_PENDING):
        # FSM ведёт заявку в «Расчёт» через «Подбор» (как отправка КП из RFQ_OPEN): своего перехода в обход матрицы нет.
        _, error = transition_deal_stage(deal, DealStageCode.SOURCING, actor=None, reason=reason)
    if not error:
        _, error = transition_deal_stage(deal, DealStageCode.CALCULATING, actor=None, reason=reason)
    if error:
        deal_log(
            deal,
            "Стадия не изменена резолюцией",
            f"Резолюция по {letter_number}: переход в «Расчёт» не выполнен ({error})",
            event_code="deal.calc_stage_kept",
            event_params={"letter_number": letter_number, "stage_code": current, "error": error},
            level="WARNING",
        )


@transaction.atomic
def apply_resolution(
    deal: Deal,
    *,
    eds_letter_id: UUID,
    letter_number: str,
    letter_subject: str,
    text: str,
    due: date,
    min_margin_pct: Optional[Decimal],
    decided_by_crm_user_id: Optional[int],
    decided_by_name: str,
    decided_at: datetime,
    assignees: list[Assignment],
    event_id: Optional[UUID] = None,
) -> ResolutionOutcome:
    """Задание расчёта по резолюции EDS и сделка в «Расчёт» (идемпотентно по письму и id события)."""
    deal = Deal.objects.select_for_update(of=("self",)).select_related("stage").get(pk=deal.pk)
    task = CalcTask.objects.select_for_update().filter(eds_letter_id=eds_letter_id).first()
    if task is not None and event_id is not None and task.eds_event_id == event_id:
        return ResolutionOutcome(task=task, created=False, changed=False)
    if task is not None and task.decided_at > decided_at:
        # События не по порядку: более старая резолюция пришла после новой — не откатываем задание.
        deal_log(
            deal,
            "Устаревшая резолюция не применена",
            f"Резолюция {letter_number} от {decided_at.isoformat()} старше действующей ({task.decided_at.isoformat()})",
            event_code="deal.calc_resolution_stale",
            event_params={"letter_number": letter_number, "decided_at": decided_at.isoformat()},
            level="WARNING",
        )
        return ResolutionOutcome(task=task, created=False, changed=False)

    fields = {
        "deal": deal,
        "letter_number": letter_number,
        "letter_subject": letter_subject[:300],
        "resolution_text": text,
        "due": due,
        "min_margin_pct": min_margin_pct,
        "decided_by_crm_user_id": decided_by_crm_user_id,
        "decided_by_name": decided_by_name[:255],
        "decided_at": decided_at,
        "eds_event_id": event_id,
    }
    created = task is None
    if created:
        task = CalcTask.objects.create(eds_letter_id=eds_letter_id, **fields)
    else:
        for name, value in fields.items():
            setattr(task, name, value)
        task.save()

    wanted = {(a.crm_user_id, a.zone) for a in assignees}
    existing = {(a.crm_user_id, a.zone): a for a in task.assignees.all()}
    task.assignees.exclude(pk__in=[a.pk for key, a in existing.items() if key in wanted]).delete()
    users = _users_by_crm_id({crm_user_id for crm_user_id, _ in wanted})
    notified: set[int] = set()
    unknown: list[int] = []
    for crm_user_id, zone in sorted(wanted):
        user_id = users.get(crm_user_id)
        row = existing.get((crm_user_id, zone))
        if row is None:
            CalcTaskAssignee.objects.create(task=task, crm_user_id=crm_user_id, zone=zone, user_id=user_id)
            if user_id and user_id not in notified:
                _notify_assignee(user_id, deal, task)
                notified.add(user_id)
        elif row.user_id != user_id:
            row.user_id = user_id
            row.save(update_fields=["user"])
        if user_id is None and crm_user_id not in unknown:
            unknown.append(crm_user_id)

    deal_log(
        deal,
        "Резолюция директора: задание на расчёт" if created else "Резолюция директора обновлена",
        f"{letter_number}: {text}".strip()[:2000],
        event_code="deal.calc_task_created" if created else "deal.calc_task_updated",
        event_params={
            "letter_number": letter_number,
            "due": due.isoformat(),
            "min_margin_pct": None if min_margin_pct is None else str(min_margin_pct),
            "assignees": [{"crm_user_id": c, "zone": z} for c, z in sorted(wanted)],
        },
    )
    for crm_user_id in unknown:
        deal_log(
            deal,
            "Исполнитель резолюции не найден в ERP",
            f"Сотрудник CRM #{crm_user_id} из резолюции {letter_number} не заведён в ERP: задание без пользователя, "
            "назначьте исполнителя после входа сотрудника в ERP",
            event_code="deal.calc_assignee_unknown",
            event_params={"letter_number": letter_number, "crm_user_id": crm_user_id},
            level="WARNING",
        )
    _move_to_calculation(deal, letter_number)
    return ResolutionOutcome(task=task, created=created, changed=True, unknown_crm_user_ids=unknown)


@transaction.atomic
def apply_letter_rejection(deal: Deal, *, letter_number: str, reason: str) -> bool:
    """Сделка в `CLOSED_LOST` с причиной отказа директора. False — ничего не изменилось (уже проиграна или нельзя)."""
    from .deals import transition_deal_stage

    deal = Deal.objects.select_for_update(of=("self",)).select_related("stage").get(pk=deal.pk)
    current = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    if current == DealStageCode.CLOSED_LOST:
        return False
    if current not in _REJECTABLE:
        deal_log(
            deal,
            "Отказ по письму не применён",
            f"Письмо {letter_number} отклонено директором, но сделка на стадии {current} (КП уже у клиента или сделка "
            "закрыта) — сделка не закрывается",
            event_code="deal.letter_rejection_kept",
            event_params={"letter_number": letter_number, "stage_code": current, "reason": reason},
            level="WARNING",
        )
        return False
    _, error = transition_deal_stage(
        deal,
        DealStageCode.CLOSED_LOST,
        actor=None,
        reason=f"Отказ по {letter_number}: {reason}"[:2000],
        lost_reason=reason,
    )
    if error:
        deal_log(
            deal,
            "Отказ по письму не применён",
            f"Письмо {letter_number} отклонено директором, но сделка на стадии {current} не закрывается ({error})",
            event_code="deal.letter_rejection_kept",
            event_params={"letter_number": letter_number, "stage_code": current, "error": error, "reason": reason},
            level="WARNING",
        )
        return False
    deal_log(
        deal,
        "Письмо отклонено директором",
        f"{letter_number}: {reason}",
        event_code="deal.lost_by_letter_rejection",
        event_params={"letter_number": letter_number, "reason": reason},
    )
    return True
