from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser

from ..constants import DealStageCode, FulfillmentStatusCode
from ..models import Deal
from .deals import transition_deal_stage

# ──────────────────────────────────────────────────────────────────────────
# Fulfillment (post-sale)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def ensure_fulfillment(deal: Deal, contract=None) -> object:
    """Отгрузка сделки, создаётся идемпотентно.

    `contract` — ПРИВЯЗКА К ВЛАДЕЛЬЦУ, а не украшение. Видимость биллинга у продавца
    (`crm/views/billing.py:_seller_side_q`) считает документ своим, если он привязан к его
    компании через `contract → quote.seller_company`; при неопределённом владельце включается
    фолбэк «виден любому ЗАРОУТИНЕННОМУ продавцу». Раньше `contract` не заполнялся никогда,
    поэтому отгрузка выигранной сделки всегда уходила в фолбэк — и её видел проигравший
    со-роутед продавец (нарушение «скрытой конкуренции», ADR-0003 §5; у инвойсов и актов
    привязка есть, у отгрузки не было).

    Договор может появиться ПОЗЖЕ отгрузки, поэтому недостающая привязка дозаполняется при
    повторном вызове. Уже проставленная НЕ перезаписывается — победитель сделки один.
    """
    from ..models import Fulfillment, FulfillmentStatus

    # status is now a FK (null=True); stamp the PENDING lookup on creation so a new
    # fulfillment keeps the old CharField default behaviour.
    obj, _ = Fulfillment.objects.get_or_create(
        deal=deal,
        defaults={
            "status": FulfillmentStatus.objects.get(code=FulfillmentStatusCode.PENDING),
            "contract": contract,
        },
    )
    if contract is not None and obj.contract_id is None:
        obj.contract = contract
        obj.save(update_fields=["contract", "updated_at"])
    return obj


@transaction.atomic
def update_fulfillment_status(
    deal_id: int,
    actor: CustomUser,
    status_code: str,
    **extra,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone

    from accounts.services import is_member_of, is_platform_admin_viewer, seller_company_routed_to_deal

    from ..models import Fulfillment, FulfillmentStatus

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    valid = set(FulfillmentStatusCode.values)
    if status_code not in valid:
        return None, "FULFILLMENT_INVALID_STATUS"
    obj = Fulfillment.objects.select_for_update().select_related("deal").get(deal_id=deal_id)
    # Seller drives shipping (PENDING→…→DELIVERED); the buyer ACCEPTS or DISPUTES on
    # receipt. Authorize the actor against the side that owns the target status.
    buyer_statuses = {FulfillmentStatusCode.ACCEPTED, FulfillmentStatusCode.DISPUTED}
    if getattr(actor, "is_superuser", False):
        authorized = True
    elif status_code in buyer_statuses:
        authorized = is_member_of(actor, obj.deal.company_id, capability="buy")
    else:
        # Seller status: bind to THIS deal's routing — not any seller (audit M1).
        authorized = seller_company_routed_to_deal(actor, obj.deal_id)
    if not authorized:
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    obj.status = FulfillmentStatus.objects.get(code=status_code)
    now = timezone.now()
    if status_code == FulfillmentStatusCode.SHIPPED and not obj.shipped_at:
        obj.shipped_at = now
    if status_code == FulfillmentStatusCode.DELIVERED and not obj.delivered_at:
        obj.delivered_at = now
    if status_code == FulfillmentStatusCode.ACCEPTED and not obj.accepted_at:
        obj.accepted_at = now
    for key in ("tracking_number", "carrier", "expected_delivery_date", "notes"):
        if key in extra and extra[key] is not None:
            setattr(obj, key, extra[key])
    obj.save()
    # Auto-close deal when accepted by client
    if status_code == FulfillmentStatusCode.ACCEPTED:
        transition_deal_stage(obj.deal, DealStageCode.CLOSED_WON, actor=actor, reason="Приёмка клиентом")
    return obj, None
