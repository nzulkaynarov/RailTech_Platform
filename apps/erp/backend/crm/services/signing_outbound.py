"""Сервис отправки запроса на регламентированное подписание официального коммерческого документа (SIGN-4, ADR-0024).

ERP не подписывает официальные коммерческие документы (КП, договор, счёт, акт) локально в обход
регламента. При запросе подписи публикуется событие `uz.railtech.erp.signing.requested.v1` в шину rt_bus.
Сервис EDS проверяет полномочия подписанта по реестру SigningAuthority с учётом замещения и возвращает
`uz.railtech.eds.signing.decided.v1` (signed/rejected).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Literal, Optional

from django.db import transaction
from integration.bus import get_bus
from integration.services.event_builders import build_actor

logger = logging.getLogger(__name__)

SIGNING_REQUESTED = "uz.railtech.erp.signing.requested.v1"


def request_commercial_signing(
    *,
    kind: Literal["quote", "contract", "invoice", "act"],
    doc: Any,
    user: Any,
    requested_signer: Optional[Any] = None,
) -> Any:
    """Опубликовать `uz.railtech.erp.signing.requested.v1` в текущей транзакции."""
    amount_raw = getattr(doc, "total_incl_vat", None)
    if amount_raw is None:
        amount_raw = getattr(doc, "total_amount", 0)
    amount_tiyins = int(Decimal(str(amount_raw)) * 100) if amount_raw is not None else 0

    currency_code = "UZS"
    if hasattr(doc, "currency") and doc.currency:
        currency_code = getattr(doc.currency, "code", "UZS")
    elif hasattr(doc, "quote_currency") and doc.quote_currency:
        currency_code = getattr(doc.quote_currency, "code", "UZS")

    crm_user_id = getattr(user, "crm_user_id", None) or getattr(user, "pk", 1)
    user_name = user.get_full_name() if hasattr(user, "get_full_name") else str(user)
    user_position = getattr(user, "position", "") or "Сотрудник"

    requested_by = {
        "crm_user_id": int(crm_user_id),
        "name": user_name or "Сотрудник",
        "position": user_position,
    }

    if requested_signer:
        signer_id = getattr(requested_signer, "crm_user_id", None) or getattr(requested_signer, "pk", 1)
        signer_name = (
            requested_signer.get_full_name() if hasattr(requested_signer, "get_full_name") else str(requested_signer)
        )
        signer_pos = getattr(requested_signer, "position", "") or "Уполномоченное лицо"
        requested_signer_dict = {
            "crm_user_id": int(signer_id),
            "name": signer_name or "Уполномоченное лицо",
            "position": signer_pos,
        }
    else:
        requested_signer_dict = requested_by

    actor = build_actor(user)

    doc_number = doc.number or f"{kind.upper()}-{doc.pk}"
    version = getattr(doc, "version", None)

    deal_id = getattr(doc, "deal_id", None)
    seller_company_id = getattr(doc, "seller_company_id", None) or getattr(doc, "company_id", None)

    data = {
        "object": {
            "kind": kind,
            "object_id": int(doc.pk),
            "number": str(doc_number),
            "version": int(version) if version is not None else None,
            "amount_tiyins": amount_tiyins,
            "currency": currency_code,
            "title": f"{kind.upper()} {doc_number}",
            "deal_id": int(deal_id) if deal_id is not None else None,
            "erp_company_id": int(seller_company_id) if seller_company_id is not None else None,
        },
        "requested_by": requested_by,
        "requested_signer": requested_signer_dict,
        "actor": actor,
    }

    with transaction.atomic():
        logger.info(
            "Публикация запроса на подпись %s #%s (signer=%s)",
            kind,
            doc_number,
            requested_signer_dict["crm_user_id"],
        )
        return get_bus().publish(SIGNING_REQUESTED, data, subject=str(doc_number))
