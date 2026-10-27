"""«Создать заявку» (CRM-03, W16-D1-2; SPEC-v3 §3.1 шаг 2, §7.2): из лида и из карточки клиента.

Ошибки (ADR-0017, `details.reason`): `erp_not_configured` (409 — без коннектора ERP заявку некуда
передать), `handoff_no_consent` (422 — согласия нет: лид даёт его в боте, ручной лид — отметка
сотрудника в `consent`), `consent_via_bot` (409 — отметить согласие лида из Telegram нельзя),
`contact_channel_required` (422 — у контакта нет ни телефона, ни e-mail, ни Telegram),
`request_not_allowed` (409 — лид в отказе), `not_lead_owner` (403), `telegram_linked_elsewhere`
(409). Заявка уходит в ERP задачей после коммита: состояние — `erp_request_status` заявки.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.schemas.client_requests import RequestCreate, RequestCreated
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["clients"])

ClientWriter = Annotated[Principal, Depends(require("clients", "write"))]


@router.post(
    "/leads/{lead_id}/actions/create_request",
    response_model=RequestCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_request_from_lead(
    lead_id: int, body: RequestCreate, who: ClientWriter, container: ContainerDep
) -> RequestCreated:
    """«+ Создать заявку» из лида любой активной стадии: лид → клиент, заявка → ERP (письмо ВХ
    директору в EDS)."""
    return await container.client_request_service.create_from_lead(who, lead_id, body)


@router.post(
    "/clients/{client_id}/actions/create_request",
    response_model=RequestCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_request_for_client(
    client_id: int, body: RequestCreate, who: ClientWriter, container: ContainerDep
) -> RequestCreated:
    """«Новая заявка для клиента» из карточки клиента."""
    return await container.client_request_service.create_for_client(who, client_id, body)
