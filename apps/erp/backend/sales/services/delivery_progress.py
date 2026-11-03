"""Отметки доставки клиенту из Платформы (L0-1 волны L0): «Отправлено клиенту / В пути» и «Доставлено».

До L0-1 статусы «В пути» и «Доставлено» ставил только старый фронт ERP (`POST crm/fulfillments/update-status/`), а клиент
принимает поставку в кабинете только из «Доставлено» (`delivery_lines.accept_delivery_line`). Здесь — проверка отметки и
допустимого перехода, дата, № накладной перевозчика и файл подтверждения; сама смена статуса, накладная, события шины и
уведомления — тот же сервис `crm.services.fulfillment.update_fulfillment_status`, что и раньше (логика не дублируется).
Отметка — на весь проект (исполнение сделки одно), строки поставки получают статус через `sync_delivery_lines`.

Эталоны: Odoo «Validate» доставки и Proof of Delivery (подпись/вложение), Business Central «Posted Sales Shipment» с
номером отправления перевозчика (Package Tracking No.), SAP S/4HANA «Proof of Delivery» — дата и подтверждение получателя.

Коды ошибок (`{"detail": CODE}`): `ROLE_NOT_PERMITTED` (403), `NOT_FOUND` (404), `FULFILLMENT_NOT_READY` и
`DELIVERY_TRANSITION_NOT_ALLOWED` (409), 400: `DELIVERY_ACTION_INVALID`, `DELIVERY_DATE_INVALID`,
`DELIVERY_DATE_IN_FUTURE`, `DELIVERY_DATE_BEFORE_SHIPPED`, `WAYBILL_TOO_LONG`, `PROOF_INVALID`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crm.constants import FulfillmentStatusCode as F

IN_TRANSIT = "in_transit"
DELIVERED = "delivered"
ACTIONS = (IN_TRANSIT, DELIVERED)
WAYBILL_MAX = 128

#: Отметка → целевой статус исполнения и статусы, из которых она допустима. Решения клиента (`ACCEPTED`, `DISPUTED`)
#: и уже доставленное назад не переводятся: доставленное принимает или оспаривает клиент.
TRANSITIONS = {
    IN_TRANSIT: (F.IN_TRANSIT, (F.PENDING, F.SHIPPED)),
    DELIVERED: (F.DELIVERED, (F.PENDING, F.SHIPPED, F.IN_TRANSIT)),
}

HTTP_STATUS = {
    "ROLE_NOT_PERMITTED": 403,
    "NOT_FOUND": 404,
    "FULFILLMENT_NOT_READY": 409,
    "DELIVERY_TRANSITION_NOT_ALLOWED": 409,
}


@dataclass(frozen=True)
class DeliveryMark:
    action: str
    on_date: str
    waybill: str = ""
    proof: Any = None


class _Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def may_mark(user) -> bool:
    """Право отмечать доставку: `fulfillment.manage` в своей компании (администратор платформы — всегда)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    company_id = own_company_id()
    return bool(company_id and member_has_permission(user, company_id, "fulfillment.manage"))


def _status_code(fulfillment) -> Optional[str]:
    return fulfillment.status.code if fulfillment.status_id else None


def available_actions(fulfillment, user) -> list[str]:
    """Отметки, доступные сотруднику сейчас: по статусу исполнения и праву (страница не угадывает)."""
    if fulfillment is None or not may_mark(user):
        return []
    code = _status_code(fulfillment)
    return [action for action in ACTIONS if code in TRANSITIONS[action][1]]


def _on_date(raw: str) -> datetime.date:
    try:
        value = datetime.date.fromisoformat((raw or "").strip())
    except ValueError:
        raise _Refused("DELIVERY_DATE_INVALID") from None
    if value > timezone.localdate():
        raise _Refused("DELIVERY_DATE_IN_FUTURE")
    return value


def _moment(day: datetime.date) -> datetime.datetime:
    """Дата отметки → момент: сегодня — сейчас, прошедший день — полдень по местному времени (дата не «уплывает»)."""
    if day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(12, 0)))


def _proof(file_obj) -> None:
    if file_obj is None:
        return
    from core.validators import validate_document_upload

    if not getattr(file_obj, "size", 0):
        raise _Refused("PROOF_INVALID")
    try:
        validate_document_upload(file_obj)
    except ValidationError:
        raise _Refused("PROOF_INVALID") from None


def _validated(mark: DeliveryMark) -> Tuple[datetime.date, str]:
    if mark.action not in ACTIONS:
        raise _Refused("DELIVERY_ACTION_INVALID")
    day = _on_date(mark.on_date)
    waybill = (mark.waybill or "").strip()
    if len(waybill) > WAYBILL_MAX:
        raise _Refused("WAYBILL_TOO_LONG")
    _proof(mark.proof)
    return day, waybill


def _locked_fulfillment(deal_id: int):
    from sales.models import Deal, Fulfillment

    fulfillment = Fulfillment.objects.select_for_update(of=("self",)).select_related("status").filter(deal_id=deal_id)
    found = fulfillment.first()
    if found is None:
        raise _Refused("FULFILLMENT_NOT_READY" if Deal.objects.filter(pk=deal_id).exists() else "NOT_FOUND")
    return found


def _store_proof(fulfillment, actor, file_obj):
    from sourcing.models import Attachment

    return Attachment.objects.create(
        file=file_obj,
        original_filename=(getattr(file_obj, "name", "") or "delivery-proof")[:255],
        deal_id=fulfillment.deal_id,
        uploaded_by=actor,
    )


def _journal(fulfillment, actor, mark: DeliveryMark, day: datetime.date, waybill: str, proof) -> None:
    """Запись в журнал проекта (`project.delivery_*` — видна в истории карточки проекта)."""
    from sales.models import ActivityLog

    deal = fulfillment.deal
    words = {IN_TRANSIT: "Отправлено клиенту, в пути", DELIVERED: "Доставлено клиенту"}
    detail = f"{words[mark.action]}: {day.strftime('%d.%m.%Y')}"
    if waybill:
        detail += f", накладная перевозчика {waybill}"
    ActivityLog.objects.create(
        action=words[mark.action],
        detail=detail,
        user=actor if getattr(actor, "pk", None) else None,
        level="INFO",
        entity_type="deal",
        entity_id=deal.pk,
        deal=deal,
        company_id=deal.company_id,
        event_code=f"project.delivery_{mark.action}",
        event_params={
            "deal_id": deal.pk,
            "on_date": day.isoformat(),
            "waybill": waybill,
            "proof_attachment_id": proof.pk if proof else None,
            "proof_name": proof.original_filename if proof else "",
        },
    )


@transaction.atomic
def _mark(deal_id: int, actor, mark: DeliveryMark):
    from sales.services.delivery_lines import sync_delivery_lines

    from crm.services.fulfillment import update_fulfillment_status

    day, waybill = _validated(mark)
    fulfillment = _locked_fulfillment(deal_id)
    target, allowed_from = TRANSITIONS[mark.action]
    if _status_code(fulfillment) not in allowed_from:
        raise _Refused("DELIVERY_TRANSITION_NOT_ALLOWED")
    shipped = fulfillment.shipped_at
    if mark.action == DELIVERED and shipped and day < timezone.localtime(shipped).date():
        raise _Refused("DELIVERY_DATE_BEFORE_SHIPPED")
    extra: dict[str, Any] = {"shipped_at": _moment(day)}
    if mark.action == DELIVERED:
        extra["delivered_at"] = _moment(day)
    if waybill:
        extra["tracking_number"] = waybill
    updated, error = update_fulfillment_status(deal_id, actor, target, **extra)
    if error:
        raise _Refused(error)
    proof = _store_proof(updated, actor, mark.proof) if mark.proof is not None else None
    if proof is not None:
        updated.delivery_proof = proof
        updated.save(update_fields=["delivery_proof", "updated_at"])
    _journal(updated, actor, mark, day, waybill, proof)
    sync_delivery_lines([updated])
    return updated


def mark_delivery(deal_id: int, actor, mark: DeliveryMark) -> Tuple[Optional[Any], Optional[str]]:
    """Отметить «В пути» или «Доставлено» по проекту; `(исполнение, None)` или `(None, код)`. Отказ — всё откатывается."""
    if not may_mark(actor):
        return None, "ROLE_NOT_PERMITTED"
    try:
        return _mark(deal_id, actor, mark), None
    except _Refused as refused:
        return None, refused.code
