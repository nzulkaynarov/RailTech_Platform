"""Тела событий ERP, которые читает EDS: `erp.request.created`, `erp.quote.ready_for_approval` и документы проектов —
`erp.contract.status_changed`, `erp.invoice.*`, `erp.act.*` (D2-5; терпимое чтение, L10).

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
    amount: str | None = None
    currency: str | None = None


class RequestPayload(_Tolerant):
    erp_request_id: int | None = None
    summary: str | None = None
    # Отправитель и менеджер письма (необязательные, с 2026-10-26, C1-G-7); старое событие их не несёт.
    company_name: str | None = None
    company_inn: str | None = None
    contact_name: str | None = None
    manager_crm_user_id: int | None = None
    # «Создать заявку» Платформы (W16-D1-2, необязательные): срочность и файл письма директору, загруженный менеджером.
    urgency: Literal["normal", "urgent"] | None = None
    letter_file_id: uuid.UUID | None = None
    request_number: str | None = None


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


class ProjectDocumentPayload(_Tolerant):
    """`payload` событий документов проекта: у договора — статус, у счёта — сумма, у акта — только номер."""

    number: str
    erp_contract_id: int | None = None
    erp_invoice_id: int | None = None
    erp_act_id: int | None = None
    status: Literal["project", "client_agreed", "issued_at_operator", "signed", "rejected", "cancelled"] | None = None
    amount: str | None = None
    currency: str | None = None


class ProjectDocumentEvent(_Tolerant):
    """`data` событий `contract.status_changed`, `invoice.issued|paid|overdue`, `act.issued|accepted|returned`."""

    erp_company_id: int | None = None
    crm_client_id: int | None = None
    deal: DealRef
    payload: ProjectDocumentPayload
