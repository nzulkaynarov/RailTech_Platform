"""Колокольчик сотрудника: события CRM — ответ на обращение, привязка Telegram (W15-H7).

Только свои уведомления; BFF Платформы сливает их с лентой ERP (`crm:<id>`). Чужое уведомление
«не существует» (404).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import ContainerDep
from app.api.v1.me import Settled
from app.schemas.staff_tickets import StaffNotificationOut, StaffNotificationsOut

router = APIRouter(prefix="/api/v1/me/notifications", tags=["me"])


@router.get("", response_model=StaffNotificationsOut)
async def list_notifications(who: Settled, container: ContainerDep) -> StaffNotificationsOut:
    """Новейшие 200, непрочитанные считаются по всей ленте."""
    service = container.staff_notifications
    items = await service.list(who.user_id)
    return StaffNotificationsOut(
        items=[
            StaffNotificationOut(
                id=n.id,
                kind=n.kind,
                tab=n.tab,
                title=n.title,
                subtitle=n.subtitle,
                object_kind=n.object_kind,
                object_id=n.object_id,
                object_number=n.object_number,
                created_at=n.created_at,
                read=n.read,
            )
            for n in items
        ],
        unread_count=await service.unread_count(who.user_id),
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all(who: Settled, container: ContainerDep) -> Response:
    await container.staff_notifications.mark_all_read(who.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_one(
    notification_id: Annotated[int, Path(gt=0)], who: Settled, container: ContainerDep
) -> Response:
    await container.staff_notifications.mark_read(who.user_id, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
