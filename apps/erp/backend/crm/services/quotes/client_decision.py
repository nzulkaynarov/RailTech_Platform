"""«Клиент принял / отклонил КП» по подтверждению клиента (A1 волны 18a, «Отметить за контрагента»).

Сотрудник с правом `deal.manage` записывает решение клиента по ОТПРАВЛЕННОМУ КП, которое пришло не через кабинет: канал,
кто со стороны клиента, когда, комментарий (для отказа — причина) и обязательный файл подтверждения (письмо, переписка,
скан — решение юриста 2026-11-02). Дальше — то же ядро, что у онлайн-решения (`lifecycle_accept`): стадия, проект,
договор, резерв, события и уведомления не отличаются; атрибуция — `on_behalf.OnBehalf`.

Коды ошибок (`{"detail": CODE}`): `ROLE_NOT_PERMITTED` (403), `QUOTE_NOT_FOUND` (404), `QUOTE_NOT_SENT` (409 — КП не ждёт
решения: не отправлено, уже решено, истекло или решили параллельно), `DEAL_STAGE_CONFLICT` (409 — заявка не на стадии КП),
400: `DECISION_INVALID`, `CHANNEL_INVALID`, `COUNTERPARTY_PERSON_REQUIRED`, `COMMENT_REQUIRED`, `OCCURRED_ON_INVALID`,
`OCCURRED_ON_IN_FUTURE`, `EVIDENCE_REQUIRED`, `EVIDENCE_INVALID`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crm.constants import QuoteStatusCode
from crm.models import Quote

from .on_behalf import CHANNELS, COMMENT_MAX, PERSON_MAX, OnBehalf

DECISIONS = ("accept", "reject")

HTTP_STATUS = {
    "ROLE_NOT_PERMITTED": 403,
    "QUOTE_NOT_FOUND": 404,
    "QUOTE_NOT_SENT": 409,
    "DEAL_STAGE_CONFLICT": 409,
}


@dataclass(frozen=True)
class ClientDecisionInput:
    decision: str
    channel: str
    counterparty_person: str
    occurred_on: str
    comment: str
    evidence: Any = None


class _Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def may_record(user) -> bool:
    """Право записать решение клиента: `deal.manage` в своей компании (администратор платформы — всегда)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    company_id = own_company_id()
    return bool(company_id and member_has_permission(user, company_id, "deal.manage"))


def can_record(user, quote) -> bool:
    """Показать «Клиент принял / отклонил»: КП ждёт решения клиента и у сотрудника есть право."""
    return bool(quote.status_id and quote.status.code == QuoteStatusCode.SENT and may_record(user))


def _occurred_on(raw: str) -> datetime.date:
    try:
        value = datetime.date.fromisoformat((raw or "").strip())
    except ValueError:
        raise _Refused("OCCURRED_ON_INVALID") from None
    if value > timezone.localdate():
        raise _Refused("OCCURRED_ON_IN_FUTURE")
    return value


def _evidence(file_obj) -> None:
    if file_obj is None or not getattr(file_obj, "size", 0):
        raise _Refused("EVIDENCE_REQUIRED")
    from core.validators import validate_document_upload

    try:
        validate_document_upload(file_obj)
    except ValidationError:
        raise _Refused("EVIDENCE_INVALID") from None


def _validated(data: ClientDecisionInput) -> Tuple[str, str, datetime.date, str]:
    """Проверка полей до любой записи; возвращает (канал, лицо, дата, комментарий)."""
    if data.decision not in DECISIONS:
        raise _Refused("DECISION_INVALID")
    if data.channel not in CHANNELS:
        raise _Refused("CHANNEL_INVALID")
    person = (data.counterparty_person or "").strip()
    if not person or len(person) > PERSON_MAX:
        raise _Refused("COUNTERPARTY_PERSON_REQUIRED")
    comment = (data.comment or "").strip()
    if not comment or len(comment) > COMMENT_MAX:
        raise _Refused("COMMENT_REQUIRED")
    occurred_on = _occurred_on(data.occurred_on)
    _evidence(data.evidence)
    return data.channel, person, occurred_on, comment


def _store_evidence(quote, actor, file_obj):
    from sourcing.models import Attachment

    return Attachment.objects.create(
        file=file_obj,
        original_filename=(getattr(file_obj, "name", "") or "evidence")[:255],
        quote=quote,
        uploaded_by=actor,
    )


@transaction.atomic
def _record(quote_id: int, actor, data: ClientDecisionInput) -> Quote:
    from .lifecycle_accept import perform_quote_acceptance, perform_quote_rejection

    channel, person, occurred_on, comment = _validated(data)
    quote = Quote.objects.select_related("status").filter(pk=quote_id).first()
    if quote is None:
        raise _Refused("QUOTE_NOT_FOUND")
    if not (quote.status_id and quote.status.code == QuoteStatusCode.SENT):
        raise _Refused("QUOTE_NOT_SENT")
    attachment = _store_evidence(quote, actor, data.evidence)
    on_behalf = OnBehalf(
        recorded_by=actor,
        channel=channel,
        counterparty_person=person,
        occurred_on=occurred_on,
        comment=comment,
        evidence_attachment_id=attachment.pk,
        evidence_name=attachment.original_filename,
    )
    try:
        if data.decision == "accept":
            return perform_quote_acceptance(quote_id, on_behalf=on_behalf)
        return perform_quote_rejection(quote_id, reason=comment, on_behalf=on_behalf)
    except ValueError:
        # Ядро под блокировкой строки КП увидело не SENT (решили параллельно) или стадия заявки не та.
        status = Quote.objects.filter(pk=quote_id).values_list("status__code", flat=True).first()
        raise _Refused("QUOTE_NOT_SENT" if status != QuoteStatusCode.SENT else "DEAL_STAGE_CONFLICT") from None


def record_client_decision(quote_id: int, actor, data: ClientDecisionInput) -> Tuple[Optional[Quote], Optional[str]]:
    """Записать решение клиента по отправленному КП; `(КП, None)` или `(None, код ошибки)`. Отказ — всё откатывается."""
    if not may_record(actor):
        return None, "ROLE_NOT_PERMITTED"
    try:
        return _record(quote_id, actor, data), None
    except _Refused as refused:
        return None, refused.code
