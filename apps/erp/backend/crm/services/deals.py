import logging
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import QuerySet

from accounts.models import CustomUser

from ..constants import ContractStatusCode, DealStageCode
from ..models import ActivityLog, Deal, DealStage

logger = logging.getLogger(__name__)

_S = DealStageCode  # local alias to keep the FSM matrix readable


def user_can_access_deal(user: CustomUser, deal: Deal) -> bool:
    """Superuser, own-company staff, deal manager, deal client, or any active member of deal.company.

    The read boundary of a deal (timeline and other per-deal surfaces). The seller of every deal
    is the own company (BUSINESS §3.3), so its staff see every deal; the client side (buyer
    accounts until M2-ERP-01) sees only its own company's deals.
    """
    from accounts.services.permissions import sees_all_deals

    if not user or not user.is_authenticated:
        return False
    if sees_all_deals(user):
        return True
    if deal.manager_id == user.id or deal.client_id == user.id:
        return True
    if deal.company_id:
        return user.memberships.filter(company_id=deal.company_id, is_active=True).exists()
    return False


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CONVENTIONS.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_STAGE_TRANSITIONS = {
    # KYC_PENDING выведен из эксплуатации (решение владельца 28-07), а сам KYC удалён в
    # M1-ERP-02 волна 1c; бизнес-логика этап никогда не ставила (мёртвая колонка воронки).
    # ВХОДА в него нет; ВЫХОДЫ сохранены, чтобы застрявшая сделка всегда могла уйти (никаких
    # тупиков). Строка справочника уйдёт со свежими миграциями M1-ERP-03.
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

    # Wave E F1 — a deal opened by a staff member for an offline contact, or a company-less
    # calculator draft (F3), is already «taken in work» by its creator: they own it from the
    # start (a teammate can still release / reassign it). Buyer-initiated deals land unclaimed
    # in the back-office queue.
    if deal.contact_id or deal.company_id is None:
        from .assignment import assign_creator_as_owner

        assign_creator_as_owner(deal, actor)
    return deal


def assert_user_may_change_stage(deal: Deal, actor: Optional[CustomUser], target_stage_code: str) -> Optional[str]:
    """SEC (audit #7): user-initiated FSM guard for the change-stage ENDPOINT only — NOT the
    shared transition_deal_stage, which internal auto-transitions (Move-0 send-КП/approve/
    dual-sign) invoke with staff/system actors and must not be re-gated.

    (a) moving DRAFT→RFQ_OPEN is submitting the request — the client's action in the portal
        (FIX-13: ERP has no buyer accounts), so the change-stage endpoint never does it;
    (b) on the back-office side moving a deal through the pipeline is part of building the
        сделки, so the staff member needs the `deal.manage` role permission (a view-only role —
        e.g. Наблюдатель — sees the deal but cannot move it).
    Returns an error code or None. superuser/internal (actor=None) bypass."""
    if actor is None or getattr(actor, "is_superuser", False):
        return None
    from accounts.services.permissions import member_has_permission, primary_seller_company_id

    if target_stage_code == DealStageCode.RFQ_OPEN:
        return "ONLY_BUYER_CAN_SUBMIT_REQUEST"
    own_company_id = primary_seller_company_id(actor)
    if not (own_company_id and member_has_permission(actor, own_company_id, "deal.manage")):
        return "ROLE_NOT_PERMITTED"
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
    admin_override=True allows the administrator (superuser) to bypass the FSM.
    Use only from force_transition_deal_stage.
    Logs the change to ActivityLog.
    Returns: (deal, error_or_None)
    """
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

    # Гейт содержимого: заявку без единой позиции продавцу не отправляют.
    #
    # «Add at least one line item to submit the request» жило ТОЛЬКО в браузере: тем же токеном
    # покупателя POST /crm/deals/{id}/change-stage/ {"stage_code":"RFQ_OPEN"} проходил, и продавец
    # получал в очередь пустую заявку, по которой нечего считать (прогон 20-08). У отправки КП
    # продавцом такой гейт есть (`QUOTE_EMPTY`), у отправки заявки покупателем не было.
    #
    # Гейт применяется только к обычному переходу: force-override оператора (`validate_fsm=False`)
    # намеренно проходит мимо всех гейтов — это его смысл.
    if validate_fsm and target_stage_code == DealStageCode.RFQ_OPEN:
        from ..models import QuoteItem

        has_items = QuoteItem.objects.filter(quote__deal=deal, display_type=QuoteItem.DisplayType.ITEM).exists()
        if not has_items:
            return None, "REQUEST_HAS_NO_ITEMS"

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
        # Коды рядом с именами: имя стадии — русская строка справочника, и, замороженная в
        # журнале, она печаталась в английской ленте как есть. Витрина подбирает подпись по
        # коду; имена остаются ради СТАРЫХ строк, у которых кода нет (ARCH-05).
        event_params={
            "deal_id": deal.id,
            "from_stage": old_stage_name,
            "to_stage": target_stage.name,
            "from_stage_code": old_stage_code,
            "to_stage_code": target_stage.code,
        },
        actor=actor,
        reason=reason,
        before={"stage_code": old_stage_code, "stage_name": old_stage_name},
        after={"stage_code": target_stage.code, "stage_name": target_stage.name},
        level="WARNING" if not validate_fsm else "INFO",
        deal_id=deal.id,
        company_id=deal.company_id,
    )

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
    if not isinstance(reason, str) or not reason.strip():
        return None, "REASON_REQUIRED"
    return transition_deal_stage(
        deal=deal,
        target_stage_code=target_stage_code,
        actor=actor,
        reason=reason.strip(),
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
