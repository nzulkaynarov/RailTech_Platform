"""DTO клиентов, документов, привязки Telegram и сервисных запросов (Фаза 6)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["contract", "proposal", "letter", "invoice", "act", "other"]


class ClientOut(BaseModel):
    id: int
    name: str
    inn: str | None
    segment: str | None
    owner_user_id: int | None
    is_active: bool
    notes: str | None
    created_at: datetime


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=32)
    segment: str | None = Field(default=None, max_length=64)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=32)
    segment: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    owner_user_id: int | None = None


class IdentityOut(BaseModel):
    tg_user_id: int
    tg_username: str | None
    tg_first_name: str | None
    lead_id: int | None
    verified_at: datetime | None
    verified_by_user_id: int | None


class LinkTelegram(BaseModel):
    tg_user_id: int = Field(gt=0)


class DocumentOut(BaseModel):
    id: int
    client_id: int
    type: str
    title: str
    number: str | None
    doc_date: date | None
    filename: str
    mime: str
    size_bytes: int
    extract_status: str
    is_visible_to_client: bool
    created_at: datetime


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    type: DocType | None = None
    number: str | None = Field(default=None, max_length=64)
    doc_date: date | None = None
    is_visible_to_client: bool | None = None


class AccessOut(BaseModel):
    id: int
    document_id: int
    accessed_by_type: str
    accessed_by_id: int | None
    tg_user_id: int | None
    created_at: datetime


class ServiceRequestOut(BaseModel):
    id: int
    lead_id: int | None
    summary: str
    status: str
    resolution: str | None = None
    closed_at: datetime | None = None
    created_at: datetime


class ServiceRequestClose(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)


class LeadBrief(BaseModel):
    id: int
    display_name: str
    stage: str
    created_at: datetime


class ClientDetail(ClientOut):
    identities: list[IdentityOut]
    candidates: list[IdentityOut]
    leads: list[LeadBrief]
    service_requests: list[ServiceRequestOut]


class MakeCustomer(BaseModel):
    client_id: int | None = None
    new_client_name: str | None = Field(default=None, max_length=255)
