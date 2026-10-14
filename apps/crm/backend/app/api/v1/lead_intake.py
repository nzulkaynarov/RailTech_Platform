"""Новые источники лидов (M3-CRM-05): публичная форма «Запрос» с сайта и «Новый лид» вручную.

Эндпоинты `/leads/web*` — без аутентификации (их вызывает страница входа Cabinet, CORS —
`CABINET_ORIGIN`); защита — антиспам в `services/lead_intake.py`. `POST /leads` — admin/manager
с правом `leads:create`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import ContainerDep, client_ip, require
from app.schemas.kb_admin import Created
from app.schemas.lead_intake import ManualLeadIn, WebFormToken, WebLeadAccepted, WebLeadIn
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["leads"])

Creator = Annotated[Principal, Depends(require("leads", "create"))]


@router.get("/leads/web/token", response_model=WebFormToken)
async def web_lead_token(container: ContainerDep) -> WebFormToken:
    """Токен формы «Запрос»: получить при показе формы, отправить в `form_token`.

    Без аутентификации. Отправка раньше `min_fill_seconds` или после `expires_at` отклоняется.
    """
    return await container.lead_intake.form_token()


@router.post("/leads/web", response_model=WebLeadAccepted, status_code=status.HTTP_202_ACCEPTED)
async def web_lead(body: WebLeadIn, request: Request, container: ContainerDep) -> WebLeadAccepted:
    """Форма «Запрос» со страницы входа Cabinet → лид CRM с источником `web` (ARCHITECTURE §17).

    Без аутентификации. Нужен телефон или e-mail. Ошибки: 422 `validation_failed` с
    `details.reason` (`form_token_invalid` | `form_too_fast` | `form_token_expired` |
    `contact_required` | `invalid_phone` | `invalid_email`), 429 `rate_limited`.
    Повторный запрос известного контакта дополняет существующую карточку.
    """
    lead_id = await container.lead_intake.create_web(body, client_ip(request))
    return WebLeadAccepted(lead_id=lead_id)


@router.post("/leads", response_model=Created, status_code=status.HTTP_201_CREATED)
async def create_lead(body: ManualLeadIn, who: Creator, container: ContainerDep) -> Created:
    """«Новый лид» вручную: звонок, письмо, рекомендация; создавший становится ответственным.

    409 `conflict` с `details.reason=lead_exists` (`lead_id`, `display_name`) или
    `client_exists` (`client_id`, `client_name`) — такой телефон/почта уже есть: откройте карточку.
    """
    return Created(id=await container.lead_intake.create_manual(who, body))
