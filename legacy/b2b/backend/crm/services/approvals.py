"""КП internal approval chain — engine for the unified approval workflow.

Replaces the hardcoded WorkspaceRole 3-step FSM (submit→ВЭД→director) with a
permission-driven, risk-aware STEP LIST: a mandatory final approver («руководитель»,
holder of quote.approve_final) plus optional intermediate reviewers (quote.review),
optionally an «informed» CC group. Same `order` runs in parallel; the head is always
last. Rule 8: all logic here; the views are thin wrappers.
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

HEAD_ORDER = 100  # the руководитель is always the last (highest-order) step


# ── helpers ────────────────────────────────────────────────────────────────
def _members_with_permission(company_id: int, perm: str) -> list:
    members = CompanyMember.objects.filter(company_id=company_id, is_active=True).select_related(
        "user", "company_role", "role"
    )
    return [m for m in members if m.user_id and member_has_permission(m.user, company_id, perm)]


def _fallback_head(company_id: int) -> Optional[CompanyMember]:
    """Never-orphan head fallback (ADR-0005 Phase E U3): if no quote.approve_final holder is
    found, fall back to the company's immutable admin (is_system «Администратор компании») — the
    never-orphan floor, which always carries quote.approve_final. No WorkspaceRole read. Returns
    None only for an admin-less company (a state never-orphan prevents); the caller logs that."""
    return (
        CompanyMember.objects.filter(company_id=company_id, is_active=True, company_role__is_system=True)
        .select_related("user")
        .first()
    )


def _notify_user(user_id: Optional[int], title: str, message: str, *, type_code: str = "INFO", link: str = "") -> None:
    if not user_id:
        return
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    ntype = NotificationType.objects.filter(code=type_code).first()
    notif = Notification.objects.create(user_id=user_id, type=ntype, title=title, message=message, link=link)
    push_notification_ws(notif)


def _step_permission(step: QuoteApprovalStep) -> str:
    """The permission a member needs to act on this step."""
    if step.participation == StepParticipation.HEAD:
        return Permission.QUOTE_APPROVE_FINAL.value
    return Permission.QUOTE_REVIEW.value


def _set_status(quote: Quote, code: str) -> None:
    quote.status = QuoteStatus.objects.get(code=code)
    quote.save(update_fields=["status", "updated_at"])


def _log(quote: Quote, actor, action: str, detail: str = "") -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=quote.id,
        deal_id=quote.deal_id,
        company_id=quote.deal.company_id,
    )


def _link(quote: Quote) -> str:
    return f"#deal-quote/{quote.deal_id}"


# ── build ──────────────────────────────────────────────────────────────────
@transaction.atomic
def build_approval_chain(quote: Quote, company_id: int, economics: Optional[dict] = None) -> None:
    """(Re)build the AUTO steps on submit. Wipes prior auto steps (keeps manual/informed ones),
    then creates: optional TRADE_REVIEW (a dedicated quote.review holder who isn't the head) at
    order=1 (parallel), and the mandatory HEAD at HEAD_ORDER. routing_mode lives on the Quote;
    'parallel' (default) gives every reviewer order=1, 'sequential' increments. Head always last.
    """
    quote.approval_steps.filter(is_auto=True).exclude(status=StepStatus.APPROVED).delete()

    head_candidates = _members_with_permission(company_id, Permission.QUOTE_APPROVE_FINAL.value)
    head_member = head_candidates[0] if head_candidates else _fallback_head(company_id)
    if head_member is None:
        logger.warning(
            "build_approval_chain: company %s has no quote.approve_final holder and no is_system "
            "admin — the head approval step will have no approver (company is orphaned)",
            company_id,
        )
    head_ids = {m.id for m in head_candidates}
    reviewers = [m for m in _members_with_permission(company_id, Permission.QUOTE_REVIEW.value) if m.id not in head_ids]

    sequential = getattr(quote, "approval_routing_mode", "PARALLEL") == "SEQUENTIAL"
    new_steps = []
    order = 1
    for reviewer in reviewers:
        new_steps.append(
            QuoteApprovalStep(
                quote=quote,
                order=order,
                participation=StepParticipation.APPROVER,
                approver=reviewer,
                status=StepStatus.PENDING,
                is_mandatory=False,
                is_auto=True,
                trigger_reason=StepTrigger.TRADE_REVIEW,
            )
        )
        if sequential:
            order += 1  # parallel keeps order=1 for everyone

    head_reason = StepTrigger.BELOW_FLOOR_ESCALATION if (economics or {}).get("below_floor") else StepTrigger.HEAD_FINAL
    margin = (economics or {}).get("gross_margin_percent")
    new_steps.append(
        QuoteApprovalStep(
            quote=quote,
            order=HEAD_ORDER,
            participation=StepParticipation.HEAD,
            approver=head_member,
            status=StepStatus.PENDING,
            is_mandatory=True,
            is_auto=True,
            trigger_reason=head_reason,
            tested_value=margin,
        )
    )
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
            )


def _notify_informed(quote: Quote, message: str) -> None:
    for step in quote.approval_steps.filter(participation=StepParticipation.INFORMED):
        if step.approver and step.approver.user_id:
            _notify_user(step.approver.user_id, "КП — для информации", message, type_code="INFO", link=_link(quote))


# ── act / recall ─────────────────────────────────────────────────────────────
@transaction.atomic
def act_on_step(step_id: int, actor, decision: str, comment: str = "") -> Tuple[Optional[Quote], Optional[str]]:
    """An approver approves or rejects their step. decision ∈ {APPROVE, REJECT}.
    APPROVE advances the chain (→ READY_TO_SEND once the head approves); REJECT returns the
    КП to DRAFT, recalls open steps, and notifies the submitter with the reason."""
    from .quotes import _quote_owner_company_id

    step = (
        QuoteApprovalStep.objects.select_for_update(of=("self",))
        .select_related("quote", "quote__status", "quote__deal")
        .filter(pk=step_id)
        .first()
    )
    if step is None:
        return None, "STEP_NOT_FOUND"
    quote = step.quote
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None, "NO_QUOTE_COMPANY"
    if not (getattr(actor, "is_superuser", False) or member_has_permission(actor, company_id, _step_permission(step))):
        return None, "ROLE_NOT_PERMITTED"
    if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
        return None, "INVALID_STATUS"
    if step.status != StepStatus.PENDING:
        return None, "STEP_ALREADY_DECIDED"
    active_order = _active_order(quote)
    if step.order != active_order:
        return None, "STEP_NOT_ACTIVE"  # earlier steps must resolve first (head can't jump the queue)

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
        _log(quote, actor, "quote.approval_reject", f"Шаг отклонён: {comment}".strip())
        _notify_user(
            quote.prepared_by_id,
            "КП возвращён на доработку",
            f"КП #{quote.number or quote.id} отклонён на согласовании. {comment}".strip(),
            type_code="WARNING",
            link=_link(quote),
        )
        return quote, None

    # APPROVE
    step.status = StepStatus.APPROVED
    step.acted_by = actor
    step.decided_at = timezone.now()
    step.comment = comment
    step.save(update_fields=["status", "acted_by", "decided_at", "comment"])
    _log(quote, actor, "quote.approval_approve", f"Шаг согласован ({step.get_participation_display()})")

    next_order = _active_order(quote)
    if next_order is None:
        # All acting steps approved → ready to send. Re-check loss-prevention defensively.
        from .quotes import compute_quote_economics

        econ = compute_quote_economics(quote)
        if econ["fx_missing"] or econ["below_cost"]:
            return None, "FX_RATE_MISSING" if econ["fx_missing"] else "QUOTE_BELOW_COST"
        _set_status(quote, QuoteStatusCode.READY_TO_SEND)
        _log(quote, actor, "quote.approval_complete", "Все согласования получены → READY_TO_SEND")
        _notify_user(
            quote.prepared_by_id,
            "КП согласован",
            f"КП #{quote.number or quote.id} полностью согласован — можно отправлять клиенту.",
            type_code="SUCCESS",
            link=_link(quote),
        )
        _notify_informed(quote, f"КП #{quote.number or quote.id} согласован.")
    elif next_order != step.order:
        _notify_order(quote, next_order)  # the next stage's turn
    return quote, None


@transaction.atomic
def recall_quote(quote_id: int, actor) -> Tuple[Optional[Quote], Optional[str]]:
    """Submitter (or head/owner) pulls a КП back out of approval to edit it. PENDING_APPROVAL →
    DRAFT, open steps RECALLED. Forbidden once READY_TO_SEND (Salesforce rule)."""
    from .quotes import _quote_owner_company_id

    quote = Quote.objects.select_for_update(of=("self",)).select_related("status").get(pk=quote_id)
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None, "NO_QUOTE_COMPANY"
    is_submitter = quote.prepared_by_id == getattr(actor, "id", None)
    is_head = member_has_permission(actor, company_id, Permission.QUOTE_APPROVE_FINAL.value)
    if not (getattr(actor, "is_superuser", False) or is_submitter or is_head):
        return None, "ROLE_NOT_PERMITTED"
    if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
        return None, "INVALID_STATUS"
    quote.approval_steps.filter(status=StepStatus.PENDING).exclude(participation=StepParticipation.INFORMED).update(
        status=StepStatus.RECALLED
    )
    _set_status(quote, QuoteStatusCode.DRAFT)
    _log(quote, actor, "quote.approval_recall", "КП отозван из согласования на доработку")
    return quote, None
