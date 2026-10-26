"""Общие схемы eds.yaml: люди, деньги, ссылки на ERP, журнал, файлы, страницы."""

import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AMOUNT_PATTERN = r"^-?\d+\.\d{2}$"
MARGIN_PATTERN = r"^(100(\.0{1,2})?|\d{1,2}(\.\d{1,2})?)$"

Amount = Annotated[str, StringConstraints(pattern=AMOUNT_PATTERN)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MarginPct = Annotated[str, StringConstraints(pattern=MARGIN_PATTERN)]
Inn = Annotated[str, StringConstraints(pattern=r"^\d{9,14}$")]
IdempotencyKey = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class Strict(BaseModel):
    """Тело запроса: лишние поля — 422 (`additionalProperties: false`)."""

    model_config = ConfigDict(extra="forbid")


class PersonRef(BaseModel):
    crm_user_id: int
    full_name: str


class Money(Strict):
    amount: Amount
    currency: Currency


class ErpLinks(BaseModel):
    erp_request_id: int | None = None
    erp_deal_id: int | None = None
    deal_number: str | None = None
    crm_client_id: int | None = None
    erp_company_id: int | None = None


class ErpLinksIn(Strict):
    erp_request_id: int | None = None
    erp_deal_id: int | None = None
    deal_number: Annotated[str | None, Field(max_length=64)] = None
    crm_client_id: int | None = None
    erp_company_id: int | None = None


class LetterSender(Strict):
    name: Annotated[str | None, Field(max_length=255)] = None
    inn: Inn | None = None


class SenderRef(Strict):
    number: Annotated[str | None, Field(max_length=64)] = None
    date: dt.date | None = None


class JournalEntry(BaseModel):
    at: dt.datetime
    action: str
    by: PersonRef | None
    comment: str | None = None
    file_id: uuid.UUID | None = None
    version: int | None = None


class FileRef(BaseModel):
    id: uuid.UUID
    name: str
    content_type: str
    size: int
    version: int
    sha256: str
    uploaded_at: dt.datetime
    uploaded_by: PersonRef
