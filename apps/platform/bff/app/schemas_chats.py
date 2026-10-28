"""Модели «Чаты · С клиентами» (B-D18-1, W18A-P3): диалоги, открытые сотруднику.

Список собирается из CRM `GET /chats`: что открыто, решает CRM (её `app/domain/chat_access.py`);
BFF переводит словарь (номер `L-NNNN`, сотрудник — `PersonRef`, канал) и данных реестра лидов
(оценка, квалификация, стадия) не добавляет.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.feeds.models import PersonRef
from app.schemas_crm_messages import Language

ChatAccess = Literal["registry", "participant", "invoiced"]


class ExternalChat(BaseModel):
    lead: str
    name: str
    channel: str
    language: Language
    last_message_at: datetime | None
    assigned: PersonRef | None
    invoiced: bool
    access: ChatAccess


class ExternalChatList(BaseModel):
    items: list[ExternalChat]
    total: int
