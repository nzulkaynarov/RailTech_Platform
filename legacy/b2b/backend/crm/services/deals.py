import logging
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import QuerySet

from accounts.models import Company, CustomUser

from ..constants import DealStageCode
from ..models import ActivityLog, Deal, DealStage, Lead

logger = logging.getLogger(__name__)

_S = DealStageCode  # local alias to keep the FSM matrix readable


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_STAGE_TRANSITIONS = {
    _S.DRAFT: [_S.KYC_PENDING, _S.RFQ_OPEN, _S.SOURCING, _S.CLOSED_LOST],
    _S.KYC_PENDING: [_S.RFQ_OPEN, _S.SOURCING, _S.CLOSED_LOST],
    _S.RFQ_OPEN: [_S.SOURCING, _S.CALCULATING, _S.CLOSED_LOST],
    _S.SOURCING: [_S.CALCULATING, _S.CLOSED_LOST],
    _S.CALCULATING: [_S.QUOTE_SENT, _S.SOURCING, _S.CLOSED_LOST],
    _S.QUOTE_SENT: [_S.CONTRACT_SIGNED, _S.CALCULATING, _S.CLOSED_LOST],
    _S.CONTRACT_SIGNED: [_S.CLOSED_WON, _S.CLOSED_LOST],
    # Terminal states are reopenable by manager for rare legitimate cases.
    _S.CLOSED_WON: [_S.CONTRACT_SIGNED],
    _S.CLOSED_LOST: [_S.CALCULATING, _S.SOURCING],
}


# Stage codes that require a signed Contract before entering.
STAGE_REQUIRES_SIGNED_CONTRACT = {_S.CLOSED_WON}


def get_allowed_transitions(stage_code: str) -> list[str]:
    """Return list of stage codes reachable from the given stage."""
    return ALLOWED_STAGE_TRANSITIONS.get(stage_code, [])


def register_new_deal(deal: Deal, actor: CustomUser) -> Deal:
    """
    Post-create hook for new deals: writes ActivityLog entry.

    The Deal itself is created by the ViewSet's perform_create
    (auto-assigning client, company, and DRAFT stage). This function
    records the audit trail so the ViewSet stays a thin wrapper
    (Rule 8).
    """
    ActivityLog.objects.create(
        action="Сделка создана",
        detail=(
            f"Пользователь {actor.email} инициировал "
            f"новую сделку #{deal.id} для компании "
            f"{deal.company.name if deal.company else 'N/A'}"
        ),
        user=actor,
        level="INFO",
    )
    return deal


def transition_deal_stage(
    deal: Deal,
    target_stage_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = "",
    validate_fsm: bool = True,
    admin_override: bool = False,
) -> Tuple[Optional[Deal], Optional[str]]:
    """
    Transition a Deal to a new stage by stage code.

    When validate_fsm=True, enforces the FSM transition matrix.
    admin_override=True allows Platform Admin to bypass both the FSM and the
    is_platform_admin_viewer guard. Use only from force_transition_deal_stage.
    Logs the change to ActivityLog.
    Returns: (deal, error_or_None)
    """
    # Actor-guard: when called by a real user (not internal/system), block
    # platform-admin viewers. Internal callers (auto-tasks, smoke scripts) pass
    # actor=None and bypass this check intentionally. admin_override also
    # bypasses: that path requires a reason and is itself a platform admin act.
    if actor is not None and not admin_override:
        from accounts.services import is_platform_admin_viewer

        if is_platform_admin_viewer(actor):
            return None, "ADMIN_VIEWER_CANNOT_ACT"

    target_stage = DealStage.objects.filter(code=target_stage_code).first()
    if not target_stage:
        return None, "DEAL_STAGE_NOT_FOUND"

    if deal.stage and deal.stage.code == target_stage_code:
        return deal, None  # already in target state, no-op

    if validate_fsm:
        current_code = deal.stage.code if deal.stage else DealStageCode.DRAFT
        allowed = get_allowed_transitions(current_code)
        if target_stage_code not in allowed:
            return None, "FSM_TRANSITION_NOT_ALLOWED"

    # Contract gate: CLOSED_WON requires a fully signed Contract.
    if validate_fsm and target_stage_code in STAGE_REQUIRES_SIGNED_CONTRACT:
        has_signed = deal.contracts.filter(status="SIGNED").exists()
        if not has_signed:
            return None, "CLOSED_WON_REQUIRES_SIGNED_CONTRACT"

    old_stage_code = deal.stage.code if deal.stage else ""
    old_stage_name = deal.stage.name if deal.stage else "—"
    deal.stage = target_stage
    deal.save(update_fields=["stage"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="deal",
        entity_id=deal.id,
        action="Стадия изменена" if validate_fsm else "Force: стадия изменена",
        detail=f"Сделка #{deal.id}: {old_stage_name} → {target_stage.name}",
        actor=actor,
        reason=reason,
        before={"stage_code": old_stage_code, "stage_name": old_stage_name},
        after={"stage_code": target_stage.code, "stage_name": target_stage.name},
        level="WARNING" if not validate_fsm else "INFO",
    )

    # Post-sale hook: on CLOSED_WON, auto-generate Invoice + Act (async)
    if target_stage_code == DealStageCode.CLOSED_WON:
        try:
            from ..tasks import auto_invoice_on_closed_won

            auto_invoice_on_closed_won.delay(deal.id)
        except Exception:
            logger.exception("Failed to dispatch auto-invoice task for deal %s", deal.id)

    return deal, None


def force_transition_deal_stage(
    deal: Deal,
    target_stage_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = "",
) -> Tuple[Optional[Deal], Optional[str]]:
    """
    Platform-admin override: bypasses the FSM but REQUIRES a non-empty reason.
    Must be called only from the admin force-stage endpoint.
    """
    if not (reason or "").strip():
        return None, "REASON_REQUIRED"
    return transition_deal_stage(
        deal=deal,
        target_stage_code=target_stage_code,
        actor=actor,
        reason=reason,
        validate_fsm=False,
        admin_override=True,
    )


def bulk_close_deals_lost(
    deals: QuerySet[Deal],
    actor: Optional[CustomUser] = None,
) -> int:
    """
    Mark deals as CLOSED_LOST. Skips deals already in any closed state.

    Returns: count of deals updated.
    """
    closed_lost = DealStage.objects.filter(code=DealStageCode.CLOSED_LOST).first()
    if not closed_lost:
        return 0
    open_deals = deals.exclude(stage__code__in=[DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST])
    count = 0
    for deal in open_deals:
        _, error = transition_deal_stage(deal, DealStageCode.CLOSED_LOST, actor=actor)
        if not error:
            count += 1
    return count


def mark_leads_processed(leads: QuerySet[Lead]) -> int:
    """
    Mark a queryset of leads as processed.

    Returns: count of leads updated (only previously-unprocessed ones).
    """
    return leads.filter(is_processed=False).update(is_processed=True)


@transaction.atomic
def convert_lead_to_deal(
    lead: Lead,
    actor: CustomUser,
    company: Optional[Company] = None,
) -> Tuple[Optional[Deal], Optional[str]]:
    """Convert a Lead into a Deal in DRAFT stage.

    If `company` is not provided, tries to resolve one via the lead email.
    """
    from accounts.services import is_platform_admin_viewer

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if lead.is_processed:
        return None, "LEAD_ALREADY_PROCESSED"

    if company is None:
        company = Company.objects.filter(
            members__user__email__iexact=lead.email,
            members__is_active=True,
        ).first()
    if company is None:
        return None, "LEAD_NO_CLIENT_COMPANY"

    draft_stage = DealStage.objects.filter(code=DealStageCode.DRAFT).first()
    deal = Deal.objects.create(
        company=company,
        client=CustomUser.objects.filter(email__iexact=lead.email).first(),
        manager=actor if (actor and actor.is_platform_admin) else None,
        stage=draft_stage,
        title=(lead.message[:200] if lead.message else f"Лид: {lead.name}"),
        notes=f"Создано из Lead #{lead.id}\nEmail: {lead.email}\nТелефон: {lead.phone}",
    )
    lead.is_processed = True
    lead.save(update_fields=["is_processed"])

    ActivityLog.objects.create(
        action="Lead конвертирован в сделку",
        detail=f"Lead #{lead.id} → Deal #{deal.id}",
        user=actor,
        level="SUCCESS",
    )
    return deal, None
