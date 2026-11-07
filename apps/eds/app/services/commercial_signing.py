"""Сервис регламентированного подписания официальных коммерческих документов ERP (SIGN-4, ADR-0024).

Проверяет право подписи по реестру полномочий (SigningAuthority) и замещению через `signing_resolve.check_signer`.
Если полномочие подтверждено:
- генерирует 10-значный код проверки (`documents.generate_verification_code`) и URL валидации;
- публикует `uz.railtech.eds.signing.decided.v1` (decision="signed", снимок подписанта, основания, код, URL);
- записывает решение в журнал аудита `journal`.
Если полномочие отсутствует/превышен лимит/истекло/отозвано:
- публикует `uz.railtech.eds.signing.decided.v1` (decision="rejected", комментарий с объяснением);
- записывает отказ в журнал аудита `journal`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_snapshots import SigningRequestedEvent
from app.config import get_settings
from app.services import documents, events, journal, signing_resolve

log = structlog.get_logger(__name__)


async def handle_signing_request(
    session: AsyncSession,
    bus: AsyncBus,
    data: SigningRequestedEvent,
    *,
    event_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Обработка входящего запроса на подпись от ERP."""
    obj = data.object
    amount = Decimal(obj.amount_tiyins) / Decimal(100) if obj.amount_tiyins is not None else None
    today = event_time.date() if event_time else dt.date.today()

    signer_ref = data.requested_signer or data.requested_by
    signer_user_id = signer_ref.crm_user_id

    check = await signing_resolve.check_signer(
        session,
        signer_user_id,
        kind=obj.kind,
        amount=amount,
        currency=obj.currency,
        on_date=today,
    )

    now = dt.datetime.now(dt.UTC)
    actor = events.actor(signer_user_id)

    if check.allowed and check.candidate:
        cand = check.candidate
        verification_code = documents.generate_verification_code()
        verification_url = f"https://{get_settings().cabinet_domain}/v/{verification_code}"

        signer_info = {
            "crm_user_id": cand.signer.crm_user_id,
            "full_name": cand.signer.full_name,
            "position": cand.position or signer_ref.position,
        }

        decided_data: dict[str, Any] = {
            "object": {
                "kind": obj.kind,
                "object_id": obj.object_id,
                "number": obj.number,
                "version": obj.version,
            },
            "decision": "signed",
            "signer": signer_info,
            "authority_id": str(cand.authority.id),
            "basis": cand.authority.basis,
            "basis_text": cand.basis_text,
            "verification_code": verification_code,
            "verification_url": verification_url,
            "signed_at": now.isoformat(),
            "comment": None,
            "actor": actor,
        }

        await events.publish(
            bus,
            session,
            "signing.decided",
            decided_data,
            subject=obj.number,
        )

        await journal.record(
            session,
            action="commercial_signing.signed",
            by=signer_user_id,
            comment=f"Документ {obj.kind} № {obj.number} подписан. Код: {verification_code}",
        )

        log.info(
            "commercial_signing_signed",
            kind=obj.kind,
            number=obj.number,
            signer=signer_user_id,
            code=verification_code,
        )
        return decided_data

    else:
        rejection_reason = check.message or "Отказано: нет полномочий для подписания документа."
        decided_data = {
            "object": {
                "kind": obj.kind,
                "object_id": obj.object_id,
                "number": obj.number,
                "version": obj.version,
            },
            "decision": "rejected",
            "signer": {
                "crm_user_id": signer_ref.crm_user_id,
                "full_name": signer_ref.name,
                "position": signer_ref.position,
            },
            "authority_id": None,
            "basis": None,
            "basis_text": None,
            "verification_code": None,
            "verification_url": None,
            "signed_at": None,
            "comment": rejection_reason,
            "actor": actor,
        }

        await events.publish(
            bus,
            session,
            "signing.decided",
            decided_data,
            subject=obj.number,
        )

        await journal.record(
            session,
            action="commercial_signing.rejected",
            by=signer_user_id,
            comment=f"Отказ в подписании {obj.kind} № {obj.number}: {rejection_reason}",
        )

        log.warning(
            "commercial_signing_rejected",
            kind=obj.kind,
            number=obj.number,
            signer=signer_user_id,
            reason=rejection_reason,
        )
        return decided_data
