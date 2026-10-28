"""Переписка с клиентами отдельно от реестра лидов (B-D18-1, W18A-P3): список диалогов.

`GET /chats` — диалоги, открытые сотруднику (`app/domain/chat_access.py`): держателю `leads:read`
(раздел `crm.leads`) — все, держателю `chats:read` (раздел `chats.external`) — где он участвует и
назначенные его зоне. Без обоих прав — 403. Сообщения, вложения и заметки диалога — маршруты
`/leads/{id}/messages`, `/leads/{id}/messages/{m}/attachments/{i}`, `/leads/{id}/notes` с той же
проверкой; карточка лида и реестр — только `leads:read`.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, PrincipalDep
from app.api.dialog_access import RbacDep, require_some_right, rights_of
from app.domain.chat_access import CHATS, dialog_access
from app.repositories import chat_access as repo
from app.schemas.chats import DialogOut, DialogPage

router = APIRouter(prefix="/api/v1", tags=["chats"])


@router.get("/chats", response_model=DialogPage)
async def list_dialogs(
    principal: PrincipalDep,
    rbac: RbacDep,
    container: ContainerDep,
    client_id: Annotated[int | None, Query(gt=0, description="Диалоги клиента CRM")] = None,
    erp_deal_id: Annotated[
        int | None, Query(gt=0, description="Диалоги клиента сделки ERP (запросить платёжку)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DialogPage:
    rights = rights_of(principal, rbac, "read")
    require_some_right(principal, rights, "read", named=CHATS)
    scope = repo.DialogScope(principal.user_id, rights.registry, rights.invoiced_zone)
    async with container.session_factory() as session:
        rows, total = await repo.list_dialogs(
            session, scope, client_id=client_id, erp_deal_id=erp_deal_id, limit=limit, offset=offset
        )
    items: list[DialogOut] = []
    for lead, facts in rows:
        access = dialog_access(rights, facts)
        if access is None:  # SQL отбирает по тому же правилу; расхождение — не показывать
            continue
        items.append(
            DialogOut(
                lead_id=lead.id,
                display_name=lead.display_name,
                source=lead.source,
                language=lead.language,
                client_id=lead.client_id,
                assigned_user_id=lead.assigned_user_id,
                last_lead_msg_at=lead.last_lead_msg_at,
                last_message_at=repo.last_activity(lead),
                invoiced=facts.invoiced,
                access=access,
            )
        )
    return DialogPage(items=items, total=total)
