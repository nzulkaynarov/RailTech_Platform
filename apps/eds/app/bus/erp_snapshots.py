"""Тела событий ERP, которые читает EDS: `erp.request.created` и `erp.quote.ready_for_approval` (терпимое чтение, L10).

Лишние поля игнорируются; неверный тип или нет обязательного поля — ошибка обработчика (автоповтор, затем `failed`).
Схемы — `packages/contracts/events/erp/`.
"""

import datetime as dt
import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DealRef(_Tolerant):
    erp_deal_id: int
    number: str
    title: str = ""


class RequestPayload(_Tolerant):
    erp_request_id: int | None = None
    summary: str | None = None


class RequestCreated(_Tolerant):
    """`data` события `uz.railtech.erp.request.created.v1`."""

    erp_company_id: int | None = None
    crm_client_id: int | None = None
    deal: DealRef
    payload: RequestPayload = Field(default_factory=RequestPayload)


class VisaBy(_Tolerant):
    crm_user_id: int | None = None
    full_name: str


class Visa(_Tolerant):
    zone: Literal["goods", "services"]
    by: VisaBy
    at: AwareDatetime


class QuotePayload(_Tolerant):
    erp_quote_id: int
    number: str
    version: int
    client_name: str | None = None
    total: str
    currency: str
    cost: str | None = None
    margin_amount: str | None = None
    margin_pct: str
    min_margin_pct: str | None = None
    required_zones: list[Literal["goods", "services"]] = Field(default_factory=list)
    visas: list[Visa] = Field(default_factory=list)
    due: dt.date | None = None
    ready_at: AwareDatetime
    valid_until: dt.date | None = None
    eds_letter_id: uuid.UUID | None = None


class QuoteReady(_Tolerant):
    """`data` события `uz.railtech.erp.quote.ready_for_approval.v1`."""

    erp_company_id: int | None = None
    crm_client_id: int | None = None
    deal: DealRef
    payload: QuotePayload
