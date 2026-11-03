"""Типы входящих писем (MAIL-TYPES; контракт: tag `inbound-mail`, 0.39.0): тип письма, правила
отправителя, действия по типу.

Справочник «Типы входящих писем» — `mail-types` в `/dictionaries` (`app/api/dictionaries.py`).
Здесь — остальное, всё в CRM (`/api/v1/inbound-mail/{id}/type|price|handover|suspicious`,
`/api/v1/mail-sender-rules`) токеном сотрудника: смена типа и действия — первая линия
`crm.leads.triage` (полный), правила — только `admin: full`. Решает CRM (что делает действие, кто
кандидат, правило ли побеждает ИИ); BFF проверяет раздел и переводит ошибки.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.inbound_mail import CRM, Clerk, MailId, _json
from app.clients import crm_models as crm
from app.deps import Authed, require, require_any
from app.schemas_inbound_mail import (
    InboundMailHandoverIn,
    InboundMailHandoverTargets,
    InboundMailTypeIn,
    MailSenderRuleIn,
    MailSenderRuleList,
    MailSenderRuleOut,
)

router = APIRouter(tags=["inbound-mail"])

AdminWrite = Annotated[Authed, Depends(require("admin", "full"))]
RulesReader = Annotated[
    Authed, Depends(require_any(("crm.leads.triage", "read"), ("admin", "read")))
]
RULES = "/api/v1/mail-sender-rules"


@router.get(
    "/inbound-mail/handover-targets",
    response_model=InboundMailHandoverTargets,
    operation_id="listInboundMailHandoverTargets",
)
async def handover_targets(authed: Clerk) -> InboundMailHandoverTargets:
    """Кому передать счёт: сотрудники, чья роль даёт подтверждать оплату."""
    raw = await _json(authed, "GET", f"{CRM}/handover-targets")
    return InboundMailHandoverTargets.model_validate(
        crm.InboundMailHandoverTargets.model_validate(raw).model_dump()
    )


@router.put("/inbound-mail/{id}/type", status_code=204, operation_id="setInboundMailType")
async def set_type(body: InboundMailTypeIn, authed: Clerk, id: MailId) -> Response:
    """Сменить тип письма одним щелчком (`null` — снять); запись в журнал письма."""
    await _json(authed, "PUT", f"{CRM}/{id}/type", json={"type_code": body.type_code})
    return Response(status_code=204)


@router.post(
    "/inbound-mail/{id}/price", status_code=204, operation_id="markInboundMailPriceUploaded"
)
async def price_uploaded(authed: Clerk, id: MailId) -> Response:
    """«Прайс загружен»: письмо «Разобрано» с итогом `price`."""
    await _json(authed, "POST", f"{CRM}/{id}/price")
    return Response(status_code=204)


@router.post(
    "/inbound-mail/{id}/suspicious", status_code=204, operation_id="moveInboundMailToSuspicious"
)
async def to_suspicious(authed: Clerk, id: MailId) -> Response:
    """«В Подозрительные»: письмо уходит из очереди во вкладку, оттуда его можно вернуть."""
    await _json(authed, "POST", f"{CRM}/{id}/suspicious")
    return Response(status_code=204)


@router.post("/inbound-mail/{id}/handover", status_code=204, operation_id="handoverInboundMail")
async def handover(body: InboundMailHandoverIn, authed: Clerk, id: MailId) -> Response:
    """«Передать бухгалтеру»: письмо «В работе» у выбранного сотрудника."""
    await _json(authed, "POST", f"{CRM}/{id}/handover", json={"user_id": body.user_id})
    return Response(status_code=204)


@router.get(
    "/mail-sender-rules", response_model=MailSenderRuleList, operation_id="listMailSenderRules"
)
async def list_rules(authed: RulesReader) -> MailSenderRuleList:
    raw = await _json(authed, "GET", RULES)
    return MailSenderRuleList.model_validate(
        crm.MailSenderRuleList.model_validate(raw).model_dump(mode="json")
    )


@router.post(
    "/mail-sender-rules",
    status_code=201,
    response_model=MailSenderRuleOut,
    operation_id="createMailSenderRule",
)
async def create_rule(body: MailSenderRuleIn, authed: AdminWrite) -> MailSenderRuleOut:
    """Правило «отправитель или домен → тип»: применяется до помощника и побеждает его."""
    raw = await _json(authed, "POST", RULES, json=body.model_dump())
    return MailSenderRuleOut.model_validate(
        crm.MailSenderRuleOut.model_validate(raw).model_dump(mode="json")
    )


@router.delete("/mail-sender-rules/{id}", status_code=204, operation_id="deleteMailSenderRule")
async def delete_rule(authed: AdminWrite, id: MailId) -> Response:
    await _json(authed, "DELETE", f"{RULES}/{id}")
    return Response(status_code=204)
