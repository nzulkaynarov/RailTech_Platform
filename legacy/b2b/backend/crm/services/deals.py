import logging
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import QuerySet

from accounts.models import Company, CustomUser

from ..constants import ContractStatusCode, DealStageCode
from ..models import ActivityLog, Deal, DealStage, Lead

logger = logging.getLogger(__name__)

_S = DealStageCode  # local alias to keep the FSM matrix readable


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_STAGE_TRANSITIONS = {
    # KYC_PENDING выведен из эксплуатации (решение владельца 28-07): KYC — свойство КОМПАНИИ
    # (verification_status + KYC-floor гейты), а не этап сделки; бизнес-логика этап никогда не
    # ставила (мёртвая колонка воронки). ВХОДА в него больше нет; ВЫХОДЫ сохранены, чтобы
    # застрявшая сделка всегда могла уйти (никаких тупиков).
    _S.DRAFT: [_S.RFQ_OPEN, _S.SOURCING, _S.CLOSED_LOST],
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
        deal=deal,
        company=deal.company,
        contact=deal.contact,
        event_code="deal.created",
        event_params={
            "actor_email": actor.email,
            "deal_id": deal.id,
            "company_name": deal.company.name if deal.company else "N/A",
        },
    )

    # Wave E F1 — SELLER-OWNED deal keystone. A deal opened by a seller for an offline
    # contact, or a company-less calculator draft (F3), is not routed by any buyer, so
    # without a DealSellerRouting row it is INVISIBLE to its own creator (seller visibility
    # is routing-only). Write the creator's routing row so the seller can see / claim /
    # build / send it. Buyer-initiated deals (client + own company) keep their existing
    # path — they get routing rows at submit/route time.
    if deal.contact_id or deal.company_id is None:
        from .assignment import ensure_creator_seller_routing

        ensure_creator_seller_routing(deal, actor)

    # Counterparty book (Phase B): a deal opened FOR an offline contact is a seller acting on
    # their own client — touch the CLIENT edge (creates it for pre-Phase-B books). Buyer-opened
    # RFQs get their edges at routing time instead (both sides at once).
    if deal.contact_id and deal.company_id:
        from accounts.services.permissions import primary_seller_company_id

        seller_company_id = primary_seller_company_id(actor)
        if seller_company_id:
            from ..models import RelationshipDirection, RelationshipSource
            from .relationships import touch_relationship

            touch_relationship(
                owner_company_id=seller_company_id,
                counterparty_company_id=deal.company_id,
                direction=RelationshipDirection.CLIENT,
                source=RelationshipSource.OFFLINE_CREATED,
            )
    return deal


def link_registered_client_to_contact_deals(contact_id: int, user: CustomUser) -> int:
    """Wave E F4 — promote-invite backfill.

    A seller works an offline client for months (deals carry `contact`, `client` is NULL
    because the person had no account). When that contact accepts the invite and registers,
    every КП the seller already sent them would stay orphaned: the buyer cabinet lists deals
    by `client`/company membership, so the new user would log in to an empty history.

    Point the historical deals of THAT contact at the freshly-registered user. Scoped by
    contact id and only fills NULLs — it never re-points a deal that already has a client,
    and the caller has just proven ownership of the contact by consuming a signed invite.
    Returns the number of deals updated.
    """
    if not contact_id or user is None or not user.pk:
        return 0
    return Deal.objects.filter(contact_id=contact_id, client__isnull=True).update(client=user)


def assert_user_may_change_stage(deal: Deal, actor: Optional[CustomUser], target_stage_code: str) -> Optional[str]:
    """SEC (audit #7): user-initiated FSM guard for the change-stage ENDPOINT only — NOT the
    shared transition_deal_stage, which internal auto-transitions (Move-0 send-КП/approve/
    dual-sign) invoke with seller/system actors and must not be re-gated.

    Closes two bypasses of submit_request's gates via the generic change-stage endpoint:
      (a) an unverified/non-buyer moving DRAFT→RFQ_OPEN (fanning the заявка to sellers below
          KYC L2, skipping submit_request's KYC + buy-capability gates);
      (b) a co-routed seller driving the SHARED Deal.stage to a terminal state (CLOSED_LOST/
          CLOSED_WON), griefing the buyer and the competing seller on a multi-seller RFQ.
    Returns an error code or None. superuser/internal (actor=None) bypass."""
    if actor is None or getattr(actor, "is_superuser", False):
        return None
    from accounts.services.kyc import company_kyc_verified
    from accounts.services.permissions import is_member_of

    is_buyer_side = is_member_of(actor, deal.company_id, capability="buy")
    if target_stage_code == DealStageCode.RFQ_OPEN:
        if not is_buyer_side:
            return "ONLY_BUYER_CAN_SUBMIT_REQUEST"
        if not company_kyc_verified(deal.company_id):
            return "KYC_REQUIRED_TO_SUBMIT"
    # A seller may decline a SINGLE-seller deal, but must not close a SHARED (multi-seller)
    # deal out from under the buyer and the competing sellers (CLOSED_LOST griefing).
    if target_stage_code == DealStageCode.CLOSED_LOST and not is_buyer_side and deal.seller_routings.count() > 1:
        return "ONLY_BUYER_CAN_CLOSE_SHARED_DEAL"
    return None


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
        has_signed = deal.contracts.filter(status__code=ContractStatusCode.SIGNED).exists()
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
        event_code="deal.stage_changed" if validate_fsm else "deal.stage_changed_force",
        event_params={"deal_id": deal.id, "from_stage": old_stage_name, "to_stage": target_stage.name},
        actor=actor,
        reason=reason,
        before={"stage_code": old_stage_code, "stage_name": old_stage_name},
        after={"stage_code": target_stage.code, "stage_name": target_stage.name},
        level="WARNING" if not validate_fsm else "INFO",
        deal_id=deal.id,
        company_id=deal.company_id,
    )

    # Counterparty book (Phase B): a stage change is an interaction — refresh the deal's
    # relationship-edge rollups (deals_count/won_count/gmv stay honest without a nightly job).
    from .relationships import recompute_rollups_for_deal

    recompute_rollups_for_deal(deal)

    # Post-sale hook: on CLOSED_WON, auto-generate Invoice + Act (async).
    # Dispatched via transaction.on_commit so the financial task NEVER fires
    # if the surrounding transaction rolls back (e.g. a later failure in the
    # caller). When no transaction is active, on_commit runs the callback
    # immediately, so the behaviour is correct in both contexts.
    if target_stage_code == DealStageCode.CLOSED_WON:
        deal_id = deal.id

        def _dispatch_auto_invoice() -> None:
            from kombu.exceptions import OperationalError

            from ..tasks import auto_invoice_on_closed_won

            try:
                auto_invoice_on_closed_won.delay(deal_id)
            except (OperationalError, OSError):
                logger.exception("Failed to dispatch auto-invoice task for deal %s", deal_id)

        transaction.on_commit(_dispatch_auto_invoice)

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
        deal=deal,
        company=company,
        event_code="lead.converted",
        event_params={"lead_id": lead.id, "deal_id": deal.id},
    )
    return deal, None
