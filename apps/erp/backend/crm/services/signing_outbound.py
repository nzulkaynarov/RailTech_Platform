"""Запрос подписи официального коммерческого документа в EDS (SIGN-4, FX-10, ADR-0024 п. 7).

ERP не подписывает документ сам. Из рабочего экрана уходит `erp.signing.requested`, EDS ставит шаг «Подписать» уполномоченному.
`CommercialSigningRequest` хранит отпечаток редакции: подпись изменённого документа ERP не применит (`eds_inbound`).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any, Literal, Optional

from django.db import transaction
from integration.bus import get_bus
from integration.models import CommercialSigningRequest, CrmUserMapping
from integration.services.event_builders import build_actor

from accounts.models import CustomUser
from core.currency import BASE_CURRENCY

logger = logging.getLogger(__name__)

SIGNING_REQUESTED = "uz.railtech.erp.signing.requested.v1"
Kind = Literal["quote", "contract", "invoice", "act"]


class SigningRequestError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _amount(doc: Any) -> Decimal:
    raw = getattr(doc, "total_incl_vat", None)
    if raw is None:
        raw = getattr(doc, "total_amount", None)
    return Decimal(str(raw or 0))


def _currency(kind: str, doc: Any) -> str:
    if kind == "act":
        invoice = getattr(doc, "invoice", None) or doc.deal.invoices.exclude(currency=None).order_by("-id").first()
        return invoice.currency.code if invoice is not None and invoice.currency_id else BASE_CURRENCY
    if kind == "quote":
        return doc.quote_currency.code if doc.quote_currency_id else BASE_CURRENCY
    return doc.currency.code if doc.currency_id else BASE_CURRENCY


def fingerprint(kind: str, doc: Any) -> str:
    """Отпечаток редакции: любое изменение документа после запроса меняет `updated_at`."""
    raw = f"{kind}|{doc.pk}|{doc.number}|{_amount(doc)}|{_currency(kind, doc)}|{doc.updated_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _version(kind: str, doc: Any, print_: str) -> int:
    """Версия для EDS: у КП — своя, у остальных — от отпечатка (та же редакция — та же версия, другая — новая)."""
    if kind == "quote" and getattr(doc, "version", None) is not None:
        return int(doc.version)
    return int(print_[:7], 16)


def _person(user: CustomUser, fallback_position: str) -> dict[str, Any]:
    mapping = CrmUserMapping.objects.filter(user=user).first()
    if mapping is None:
        raise SigningRequestError("NO_CRM_USER", "Сотрудник не сопоставлен с учётной записью CRM.")
    return {
        "crm_user_id": int(mapping.crm_user_id),
        "name": user.get_full_name() or user.email,
        "position": getattr(user, "position", "") or fallback_position,
    }


def _check_can_be_signed(kind: str, doc: Any) -> None:
    if doc.verification_code:
        raise SigningRequestError("ALREADY_SIGNED", "Документ уже подписан. Исправление — новый документ.")
    if kind in ("invoice", "act") and doc.status_code == "DRAFT":
        raise SigningRequestError("NOT_ISSUED", "Сначала выпустите документ: у черновика нет номера.")
    if not doc.number:
        raise SigningRequestError("NO_NUMBER", "У документа нет номера.")


@transaction.atomic
def request_commercial_signing(
    *, kind: Kind, doc: Any, user: CustomUser, requested_signer: Optional[CustomUser] = None
) -> CommercialSigningRequest:
    """Запрос подписи из рабочего экрана: строка запроса и событие в одной транзакции."""
    _check_can_be_signed(kind, doc)
    print_ = fingerprint(kind, doc)
    pending = (
        CommercialSigningRequest.objects.select_for_update()
        .filter(kind=kind, object_id=doc.pk, status=CommercialSigningRequest.Status.PENDING)
        .first()
    )
    if pending is not None:
        if pending.fingerprint == print_:
            raise SigningRequestError("ALREADY_REQUESTED", "Документ уже на подписи.")
        pending.status = CommercialSigningRequest.Status.STALE
        pending.comment = "Документ изменён, отправлен на подпись заново."
        pending.save(update_fields=["status", "comment"])

    requested_by = _person(user, "Сотрудник")
    data = {
        "object": {
            "kind": kind,
            "object_id": int(doc.pk),
            "number": str(doc.number),
            "version": _version(kind, doc, print_),
            "amount_tiyins": int(_amount(doc) * 100),
            "currency": _currency(kind, doc),
            "title": f"{kind.upper()} {doc.number}",
            "deal_id": int(doc.deal_id) if getattr(doc, "deal_id", None) else None,
            "erp_company_id": None,
        },
        "requested_by": requested_by,
        "requested_signer": _person(requested_signer, "Уполномоченное лицо") if requested_signer else None,
        "actor": build_actor(user),
    }
    request = CommercialSigningRequest.objects.create(
        kind=kind, object_id=doc.pk, number=str(doc.number), fingerprint=print_, requested_by=user
    )
    get_bus().publish(SIGNING_REQUESTED, data, subject=str(doc.number))
    logger.info("Запрос подписи %s #%s", kind, doc.number)
    return request
