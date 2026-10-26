"""Визы КП внутри ERP и передача КП директору на одобрение в EDS (EDS-03, ADR-0015, runbook волны 12 §2.4–§2.5).

Цепочка ERP — только визы расчёта: шаги строятся из исполнителей задания расчёта (`CalcTask`, резолюция EDS) в зонах
goods и services, у которых есть пользователь ERP; визирует назначенный исполнитель шага (право — назначение, а не
`quote.review`), автор КП визирует свою зону самой отправкой. Директор и прочие держатели `quote.review` в визы ERP не
попадают — одобрение директора только в EDS. КП без задания расчёта виз не ждёт. Когда виз больше не ждём (все шаги
пройдены или их нет), КП уходит директору: ERP публикует `uz.railtech.erp.quote.ready_for_approval.v1`
в транзакции изменения (`request_director_approval`) и ждёт решения маршрута EDS. Решение (`eds.approval.decided`)
применяет `apply_director_decision`: одобрено — ИСХ-номер EDS на КП и «Готово к отправке»; возвращено — черновик с
комментарием директора (правка и повторная отправка — новая редакция, новое событие); отклонено — КП отклонено.
Своей цепочки одобрения директором (шаг «Руководитель» и право финального утверждения КП) у ERP больше нет —
решение архитектора волны 12 §4 п. 3. Rule 8: логика здесь, вьюхи — тонкие обёртки.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.constants import Permission
from accounts.models import CompanyMember
from accounts.services.permissions import member_has_permission
from crm.constants import QuoteStatusCode
from crm.models import ActivityLog, Quote, QuoteApprovalStep, QuoteStatus
from crm.models.approvals import StepParticipation, StepStatus, StepTrigger

logger = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────
def _notify_user(
    user_id: Optional[int],
    title: str,
    message: str,
    *,
    event_code: str,
    event_params: dict,
    type_code: str = "INFO",
    link: str = "",
) -> None:
    """Уведомление участнику согласования — с МАШИННЫМ кодом события.

    Русские `title`/`message` остаются полем-фолбэком: ленту собирает витрина по локали
    ПОЛУЧАТЕЛЯ (`frontend/src/lib/activityText.ts`), и без кода она печатала русский текст в
    английском интерфейсе. Тот же класс уже чинили в журнале и уведомлениях волной #523/#524,
    но цепочка внутреннего согласования КП тогда осталась в стороне: `event_code` в этом файле
    стоял у `_log()` (ActivityLog), а у `Notification` — нет (замер 26-08, находка 12).
    """
    if not user_id:
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    ntype = NotificationType.objects.filter(code=type_code).first()
    notif = Notification.objects.create(
        user_id=user_id,
        type=ntype,
        title=title,
        message=message,
        link=link,
        event_code=event_code,
        event_params=event_params,
    )
    push_notification_ws(notif)


def may_act_on_step(step: QuoteApprovalStep, actor, company_id: Optional[int]) -> bool:
    """Может ли `actor` закрыть шаг: виза расчёта — только назначенный исполнитель шага (решение лида волны 12, Б1);
    прежние шаги без назначения по резолюции — держатель `quote.review`; суперпользователь — за другого («от имени»)."""
    if getattr(actor, "is_superuser", False):
        return True
    if step.trigger_reason == StepTrigger.CALC_VISA:
        return bool(step.approver_id) and step.approver.user_id == getattr(actor, "id", None)
    return bool(company_id) and member_has_permission(actor, company_id, Permission.QUOTE_REVIEW.value)


def _set_status(quote: Quote, code: str) -> None:
    quote.status = QuoteStatus.objects.get(code=code)
    fields = ["status", "updated_at"]
    if code == QuoteStatusCode.DRAFT and quote.fx_fixed_at is not None:
        # M1-ERP-08: КП вернулось в черновик (отклонён шаг / отозвано) — курс снова живой.
        quote.fx_fixed_at = None
        fields.append("fx_fixed_at")
    quote.save(update_fields=fields)


def _log(
    quote: Quote,
    actor,
    action: str,
    detail: str = "",
    *,
    event_code: str = "",
    event_params: Optional[dict] = None,
) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=quote.id,
        deal_id=quote.deal_id,
        company_id=quote.deal.company_id,
        event_code=event_code,
        event_params=event_params or {},
    )


def _link(quote: Quote) -> str:
    return f"#deal-quote/{quote.deal_id}"


def _visa_members(quote: Quote, company_id: int) -> list:
    """Кто визирует КП: исполнители задания расчёта сделки в зонах goods/services с пользователем ERP, кроме автора КП
    (он визирует свою зону отправкой). Участник ERP — членство в компании-владельце КП, иначе любое действующее."""
    from .calc_tasks import latest_task, visa_assignee_user_ids

    user_ids = [uid for uid in visa_assignee_user_ids(latest_task(quote.deal_id)) if uid != quote.prepared_by_id]
    members = []
    for user_id in user_ids:
        active = CompanyMember.objects.filter(user_id=user_id, is_active=True).select_related("user")
        member = active.filter(company_id=company_id).first() or active.order_by("id").first()
        if member is None:
            logger.warning(
                "Исполнитель расчёта #%s без членства в компании — шаг визы не создан (КП #%s)", user_id, quote.pk
            )
            continue
        members.append(member)
    return members


def _on_behalf_params(step: QuoteApprovalStep, actor) -> dict:
    """Суперпользователь закрыл шаг за другого согласующего (D-11): в журнале — «от имени» (кто и за кого)."""
    approver = step.approver
    if approver is None or not getattr(actor, "is_superuser", False) or approver.user_id == getattr(actor, "id", None):
        return {}
    return {"on_behalf_of": _member_display(approver), "on_behalf_of_user_id": approver.user_id}


# ── build ──────────────────────────────────────────────────────────────────
@transaction.atomic
def build_approval_chain(quote: Quote, company_id: int, economics: Optional[dict] = None) -> None:
    """(Пере)строить авто-шаги виз при отправке на согласование: прежние авто-шаги (кроме пройденных) удаляются,
    ручные и «для информации» остаются; каждому исполнителю расчёта (зоны goods/services, не автор) — шаг визы
    `CALC_VISA`. routing_mode живёт на КП: 'parallel' (по умолчанию) — у всех order=1, 'sequential' — по возрастанию.
    Шага директора нет: одобрение — маршрут EDS после виз (`request_director_approval`)."""
    quote.approval_steps.filter(is_auto=True).exclude(status=StepStatus.APPROVED).delete()

    sequential = getattr(quote, "approval_routing_mode", "PARALLEL") == "SEQUENTIAL"
    margin = (economics or {}).get("gross_margin_percent")
    new_steps = []
    order = 1
    for member in _visa_members(quote, company_id):
        new_steps.append(
            QuoteApprovalStep(
                quote=quote,
                order=order,
                participation=StepParticipation.APPROVER,
                approver=member,
                status=StepStatus.PENDING,
                is_mandatory=True,
                is_auto=True,
                trigger_reason=StepTrigger.CALC_VISA,
                tested_value=margin,
            )
        )
        if sequential:
            order += 1  # parallel keeps order=1 for everyone
    QuoteApprovalStep.objects.bulk_create(new_steps)


def _active_order(quote: Quote) -> Optional[int]:
    """The lowest order with a PENDING acting (non-informed) step — the current stage."""
    pending = (
        quote.approval_steps.filter(status=StepStatus.PENDING)
        .exclude(participation=StepParticipation.INFORMED)
        .order_by("order")
    )
    first = pending.first()
    return first.order if first else None


def _notify_order(quote: Quote, order: int) -> None:
    """Ping the (assigned) approvers at this order that it's their turn."""
    for step in quote.approval_steps.filter(order=order, status=StepStatus.PENDING).exclude(
        participation=StepParticipation.INFORMED
    ):
        if step.approver and step.approver.user_id:
            _notify_user(
                step.approver.user_id,
                "Требуется согласование КП",
                f"КП #{quote.number or quote.id}: ваша очередь согласовать.",
                type_code="WARNING",
                link=_link(quote),
                event_code="quote.approval_your_turn",
                event_params={"number": quote.number or quote.id},
            )


def _notify_informed(quote: Quote, message: str, *, event_code: str, event_params: dict) -> None:
    # `select_related`: без него каждый шаг тянул своего участника отдельным запросом.
    for step in quote.approval_steps.select_related("approver").filter(participation=StepParticipation.INFORMED):
        if step.approver and step.approver.user_id:
            _notify_user(
                step.approver.user_id,
                "КП — для информации",
                message,
                type_code="INFO",
                link=_link(quote),
                event_code=event_code,
                event_params=event_params,
            )


# ── act / recall ─────────────────────────────────────────────────────────────
@transaction.atomic
def act_on_step(step_id: int, actor, decision: str, comment: str = "") -> Tuple[Optional[Quote], Optional[str]]:
    """Исполнитель расчёта визирует или отклоняет свой шаг. decision ∈ {APPROVE, REJECT}.
    APPROVE продвигает цепочку виз; последняя виза передаёт КП директору — `request_director_approval`
    (событие `quote.ready_for_approval` в EDS, КП остаётся «На утверждении»). REJECT возвращает КП в черновик,
    отзывает открытые шаги и уведомляет автора с причиной.

    Автор КП не закрывает шаг проверяющего своего КП (`SELF_APPROVAL_NOT_ALLOWED`, FIX-55, D-02). Суперпользователь
    закрывает шаг за другого, но в журнале это помечено «от имени» (D-11)."""
    from .quotes import _quote_owner_company_id

    step = (
        QuoteApprovalStep.objects.select_for_update(of=("self",))
        .select_related("quote", "quote__status", "quote__deal", "approver__user")
        .filter(pk=step_id)
        .first()
    )
    if step is None:
        return None, "STEP_NOT_FOUND"
    quote = step.quote
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None, "NO_QUOTE_COMPANY"
    if not may_act_on_step(step, actor, company_id):
        return None, "ROLE_NOT_PERMITTED"
    if (
        step.participation == StepParticipation.APPROVER
        and quote.prepared_by_id is not None
        and quote.prepared_by_id == getattr(actor, "id", None)
    ):
        return None, "SELF_APPROVAL_NOT_ALLOWED"
    if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
        return None, "INVALID_STATUS"
    if step.status != StepStatus.PENDING:
        return None, "STEP_ALREADY_DECIDED"
    active_order = _active_order(quote)
    if step.order != active_order:
        return None, "STEP_NOT_ACTIVE"  # earlier steps must resolve first

    on_behalf = _on_behalf_params(step, actor)
    on_behalf_text = f" (от имени {on_behalf['on_behalf_of']})" if on_behalf else ""
    if decision == "REJECT":
        step.status = StepStatus.REJECTED
        step.acted_by = actor
        step.decided_at = timezone.now()
        step.comment = comment
        step.save(update_fields=["status", "acted_by", "decided_at", "comment"])
        quote.approval_steps.filter(status=StepStatus.PENDING).exclude(participation=StepParticipation.INFORMED).update(
            status=StepStatus.RECALLED
        )
        _set_status(quote, QuoteStatusCode.DRAFT)
        _log(
            quote,
            actor,
            "Согласование отклонено",
            f"Шаг отклонён: {comment}{on_behalf_text}".strip(),
            event_code="quote.approval_step_rejected",
            event_params={"comment": comment, **on_behalf},
        )
        _notify_user(
            quote.prepared_by_id,
            "КП возвращён на доработку",
            f"КП #{quote.number or quote.id} отклонён на согласовании. {comment}".strip(),
            type_code="WARNING",
            link=_link(quote),
            event_code="quote.approval_returned",
            event_params={"number": quote.number or quote.id, "comment": comment},
        )
        return quote, None

    # APPROVE
    step.status = StepStatus.APPROVED
    step.acted_by = actor
    step.decided_at = timezone.now()
    step.comment = comment
    step.save(update_fields=["status", "acted_by", "decided_at", "comment"])
    _log(
        quote,
        actor,
        "Шаг согласования пройден",
        f"Шаг согласован ({step.get_participation_display()}){on_behalf_text}",
        event_code="quote.approval_step_approved",
        # `get_participation_display()` переводится на языке ТОГО, кто согласовал, и
        # замерзает в журнале — читателю на другом языке доставалось «(Руководитель)».
        # Витрина подбирает подпись по коду; имя остаётся для старых строк (ARCH-05).
        event_params={
            "participation": step.get_participation_display(),
            "participation_code": step.participation,
            **on_behalf,
        },
    )

    next_order = _active_order(quote)
    if next_order is None:
        # Все визы собраны → КП уходит директору (маршрут EDS). Убыточное КП директору не уходит.
        from .quotes import compute_quote_economics

        econ = compute_quote_economics(quote)
        if econ["fx_missing"] or econ["below_cost"]:
            return None, "FX_RATE_MISSING" if econ["fx_missing"] else "QUOTE_BELOW_COST"
        from .eds_quote_approval import request_director_approval

        request_director_approval(quote, actor)
        _notify_user(
            quote.prepared_by_id,
            "Визы собраны",
            f"КП #{quote.number or quote.id}: визы собраны, КП передано директору на одобрение.",
            type_code="INFO",
            link=_link(quote),
            event_code="quote.visas_complete",
            event_params={"number": quote.number or quote.id},
        )
        _notify_informed(
            quote,
            f"КП #{quote.number or quote.id}: визы собраны, КП у директора.",
            event_code="quote.visas_complete_informed",
            event_params={"number": quote.number or quote.id},
        )
    elif next_order != step.order:
        _notify_order(quote, next_order)  # the next stage's turn
    return quote, None


# ── preview (Salesforce «Approval Preview») ──────────────────────────────────
_PARTICIPATION_LABELS = dict(StepParticipation.choices)
_TRIGGER_LABELS = dict(StepTrigger.choices)


def _member_display(member) -> str:
    if member is None:
        return ""
    user = getattr(member, "user", None)
    if user is None:
        return ""
    return (user.get_full_name() or user.email or "").strip()


def _preview_step(member, participation: str, trigger: str, submitter_user_id: Optional[int]) -> dict:
    """Project a would-be approver into the read-only preview shape (no QuoteApprovalStep row)."""
    roles = list(member.company_roles.all()) if member is not None else []
    return {
        "participation": participation,
        "participation_label": str(_PARTICIPATION_LABELS.get(participation, participation)),
        "trigger": trigger,
        "trigger_label": str(_TRIGGER_LABELS.get(trigger, trigger)),
        "member_id": getattr(member, "id", None),
        "user_id": getattr(member, "user_id", None),
        "name": _member_display(member),
        "role": ", ".join(role.name for role in roles),
        "is_assigned": member is not None,
        "is_submitter": member is not None and member.user_id == submitter_user_id,
    }


def preview_approval_chain(quote_id: int, actor) -> Tuple[Optional[dict], Optional[str]]:
    """Только чтение: кто визирует КП (исполнители расчёта), если отправить его сейчас (Salesforce Approval Preview). Шаги не строятся и
    ничего не сохраняется — то же разрешение участников, что у `build_approval_chain`. После виз КП уходит директору
    в EDS (EDS-03) — шагом ERP это не показывается. Доступно тому, кто может отправить КП (`quote.build`)."""
    from crm.services.quotes.lifecycle_gates import resolve_submit_company
    from crm.services.quotes.pricing import compute_quote_economics

    quote = Quote.objects.select_related("status", "prepared_by", "deal").filter(pk=quote_id).first()
    if quote is None:
        return None, "QUOTE_NOT_FOUND"
    company_id, err = resolve_submit_company(quote, actor)
    if err:
        return None, err

    economics = compute_quote_economics(quote)
    submitter_id = getattr(actor, "id", None)
    steps = [
        _preview_step(member, StepParticipation.APPROVER, StepTrigger.CALC_VISA, submitter_id)
        for member in _visa_members(quote, company_id)
    ]
    return {"below_floor": bool(economics.get("below_floor")), "steps": steps}, None


@transaction.atomic
def recall_quote(quote_id: int, actor) -> Tuple[Optional[Quote], Optional[str]]:
    """Автор КП (или суперпользователь) забирает КП с визирования на правку: PENDING_APPROVAL → DRAFT, открытые
    шаги RECALLED. Запрещено после «Готово к отправке» (Salesforce rule) и после передачи директору в EDS
    (`QUOTE_AWAITING_DIRECTOR`, 409): маршрут EDS открыт, вернуть КП может только директор («на доработку»)."""
    from .quotes import _quote_owner_company_id

    quote = Quote.objects.select_for_update(of=("self",)).select_related("status").get(pk=quote_id)
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None, "NO_QUOTE_COMPANY"
    is_submitter = quote.prepared_by_id == getattr(actor, "id", None)
    if not (getattr(actor, "is_superuser", False) or is_submitter):
        return None, "ROLE_NOT_PERMITTED"
    if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
        return None, "INVALID_STATUS"
    if _active_order(quote) is None:
        return None, "QUOTE_AWAITING_DIRECTOR"  # визы собраны, КП у директора в EDS
    quote.approval_steps.filter(status=StepStatus.PENDING).exclude(participation=StepParticipation.INFORMED).update(
        status=StepStatus.RECALLED
    )
    _set_status(quote, QuoteStatusCode.DRAFT)
    _log(
        quote,
        actor,
        "КП отозван из согласования",
        "КП отозван из согласования на доработку",
        event_code="quote.approval_recalled",
    )
    return quote, None
