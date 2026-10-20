from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser
from crm.services.pdf_storage import save_rendered_pdf

from ..constants import DealStageCode, FulfillmentStatusCode
from ..models import Deal
from .deals import transition_deal_stage

# ──────────────────────────────────────────────────────────────────────────
# Fulfillment (post-sale)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def delivery_note_number(fulfillment) -> str:
    """Номер накладной для показа: присвоенный из схемы либо ЛЕГАСИ-вид `DN-{id}`.

    У отгрузок, напечатанных до перехода на схему, номер уже у контрагента на руках —
    переписывать его нельзя (правило E3 «выпущенный документ не переписывается»).
    """
    return fulfillment.note_number or f"DN-{fulfillment.id}"


def ensure_delivery_note_number(fulfillment, seller_company) -> str:
    """Присвоить номер из ОБЩЕЙ схемы при первой печати; дальше он неизменен.

    Эталон: Odoo даёт `stock.picking` имя из последовательности, у SAP delivery note —
    собственный номерной диапазон. До этого номер собирался как `DN-{id}` в пяти местах кода,
    мимо схемы, по которой идут все прочие документы (квитанция уже по схеме).
    """
    from django.db import transaction

    from .numbering import next_document_number

    if fulfillment.note_number:
        return fulfillment.note_number
    with transaction.atomic():
        # Блокировка счётчика живёт до коммита — контракт `next_document_number`.
        number = next_document_number("DN", "DN", company=seller_company)
        fulfillment.note_number = number
        fulfillment.save(update_fields=["note_number", "updated_at"])
    return number


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

    from accounts.services import is_seller

    from ..models import Fulfillment, FulfillmentStatus

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
        # Приёмку и спор подтверждает ЗАКАЗЧИК, а заказчика-пользователя в ERP нет (FIX-13):
        # шаг вернёт портал (FIX-24). Продавцу говорим именно это, а не общее «нужно членство»:
        # прежний общий код витрина переводила как «действие доступно только членам компании» —
        # продавцу, который членом СВОЕЙ компании является, это читается как поломка.
        return None, "FULFILLMENT_ACCEPTANCE_IS_BUYER_STEP"
    else:
        # Seller status: own-company staff (the seller of every deal).
        authorized = is_seller(actor)
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
    # Движение груза не порождало ни одного уведомления: покупатель, ждущий поставку, не
    # узнавал ни об отгрузке, ни о доставке. Адресат — противоположная сторона.
    from django.db import transaction

    from .deal_notifications import notify_fulfillment_status

    transaction.on_commit(lambda: notify_fulfillment_status(obj, status_code, actor))
    return obj, None


def _render_delivery_note_pdf(fulfillment) -> None:
    """Накладная на отгрузку (D2b, паттерн Odoo Delivery Slip): печатный артефакт отгрузки.

    Состав отправления — billable-позиции КП победившего договора (юридически согласованный
    товар); подписи «двух рук» (отправитель/получатель) — печатное основание приёмки для
    двустороннего акта (G1).
    """
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from .document_blocks import company_template_for, render_delivery_note_body
    from .documents import brand_context_for_pdf, document_brand_context
    from .quotes import _quote_seller_company

    contract = fulfillment.contract
    quote = contract.quote if (contract and contract.quote_id) else None
    supplier = _quote_seller_company(quote) if quote else None
    number = ensure_delivery_note_number(fulfillment, supplier)
    brand = document_brand_context(supplier)
    ccy = contract.currency.code if (contract and contract.currency_id) else "UZS"
    items = quote.items.billable().select_related("product") if quote else []
    template = company_template_for(supplier, "DELIVERY_NOTE")
    body = render_delivery_note_body(
        fulfillment, items, ccy, template, seller=brand.get("seller"), seller_profile=brand.get("seller_profile")
    )
    html_string = render_to_string(
        "crm/delivery_note_pdf_templated.html",
        {
            "fulfillment": fulfillment,
            "note_number": number,
            "company": fulfillment.deal.company,
            "contact": getattr(fulfillment.deal, "contact", None),
            "body_html": body,
            **brand_context_for_pdf(brand),
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    save_rendered_pdf(fulfillment, f"DeliveryNote_{number}.pdf", ContentFile(buf.getvalue()))
