"""Список диалогов с клиентами (B-D18-1): только открытые сотруднику по `domain/chat_access`."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.chat_access import DialogAccess


class DialogOut(BaseModel):
    """Диалог лида без данных реестра (оценка, квалификация, стадия — в карточке лида)."""

    lead_id: int
    display_name: str
    source: str = Field(description="Канал лида: telegram, web, phone, email, referral")
    language: str
    client_id: int | None
    assigned_user_id: int | None
    last_lead_msg_at: datetime | None = Field(description="Последнее сообщение клиента")
    last_message_at: datetime | None = Field(
        description="Последнее сообщение в диалоге (клиента, бота или сотрудника)"
    )
    invoiced: bool = Field(description="По сделке клиента ERP выставила счёт")
    access: DialogAccess = Field(
        description=(
            "Почему диалог открыт: `registry` — реестр лидов (`leads:read`), `participant` — "
            "сотрудник участвует (ответственный за лида, клиента или сделку, автор ответа), "
            "`invoiced` — зона «Счета и оплаты» (`chats:invoiced`)"
        )
    )


class DialogPage(BaseModel):
    items: list[DialogOut]
    total: int
