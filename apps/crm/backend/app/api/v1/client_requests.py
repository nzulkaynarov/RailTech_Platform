"""«Создать заявку» (CRM-03, W16-D1-2; SPEC-v3 §3.1 шаг 2, §7.2): из лида и из карточки клиента.

Ошибки (ADR-0017, `details.reason`): `erp_not_configured` (409 — без коннектора ERP заявку некуда
передать), `handoff_no_consent` (422 — согласия нет: лид даёт его в боте, ручной лид — отметка
сотрудника в `consent`), `consent_via_bot` (409 — отметить согласие лида из Telegram нельзя),
`contact_channel_required` (422 — у контакта нет ни телефона, ни e-mail, ни Telegram),
`request_not_allowed` (409 — лид в отказе), `not_lead_owner` (403), `telegram_linked_elsewhere`
(409), `request_key_reused` (409 — ключ формы уже у заявки другого лида или клиента). Заявка уходит
в ERP задачей после коммита: состояние — `erp_request_status` заявки.

Идемпотентность — `request_key` формы (UUID, задаёт клиент): повтор с тем же ключом (двойной клик,
повтор по таймауту, параллельно) — 200 с той же заявкой, без второй строки `deals`, задачи и письма
ВХ. Защита — блокировка лида или клиента и UNIQUE `deals.request_key` (последний рубеж).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ContainerDep, require
from app.schemas.client_requests import RequestCreate, RequestCreated, RequestRetried
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["clients"])

ClientWriter = Annotated[Principal, Depends(require("clients", "write"))]


@router.post(
    "/leads/{lead_id}/actions/create_request",
    response_model=RequestCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_request_from_lead(
    lead_id: int,
    body: RequestCreate,
    who: ClientWriter,
    container: ContainerDep,
    response: Response,
) -> RequestCreated:
    """«+ Создать заявку» из лида любой активной стадии: лид → клиент, заявка → ERP (письмо ВХ
    директору в EDS)."""
    created = await container.client_request_service.create_from_lead(who, lead_id, body)
    return _answer(created, response)


@router.post(
    "/clients/{client_id}/actions/create_request",
    response_model=RequestCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_request_for_client(
    client_id: int,
    body: RequestCreate,
    who: ClientWriter,
    container: ContainerDep,
    response: Response,
) -> RequestCreated:
    """«Новая заявка для клиента» из карточки клиента."""
    created = await container.client_request_service.create_for_client(who, client_id, body)
    return _answer(created, response)


@router.post("/deals/{deal_id}/actions/retry_request", response_model=RequestRetried)
async def retry_request(deal_id: int, who: ClientWriter, container: ContainerDep) -> RequestRetried:
    """«Повторить отправку в ERP» (B-082): заявка с ошибкой передачи снова уходит в ERP той же
    задачей и с тем же `crm_request_id`. Не в ошибке — 409 `request_not_failed`; постоянная
    ошибка (`erp_request_conflict`) — 409 `request_not_retryable`."""
    return await container.request_retry_service.retry(who, deal_id)


def _answer(created: RequestCreated, response: Response) -> RequestCreated:
    """Повтор формы с тем же `request_key` — 200 с той же заявкой; новая заявка — 201."""
    if not created.created:
        response.status_code = status.HTTP_200_OK
    return created
