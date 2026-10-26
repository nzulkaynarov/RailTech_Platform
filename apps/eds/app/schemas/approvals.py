"""Схемы маршрутов согласования (eds.yaml: Approval, ApprovalStep, DecisionIn, QuoteSnapshot, ChecklistItem, …)."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, ValidationInfo, field_validator, model_serializer

from app.schemas.common import Amount, Currency, MarginPct, PersonRef, Strict


class ApprovalTemplate(StrEnum):
    MEMO = "memo"
    APPLICATION = "application"
    REPORT = "report"
    QUOTE = "quote"


class RouteStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    RETURNED = "returned"
    REJECTED = "rejected"


class Decision(StrEnum):
    APPROVE = "approve"
    RETURN = "return"
    REJECT = "reject"


class SendChannel(StrEnum):
    TELEGRAM = "telegram"
    CABINET = "cabinet"
    EMAIL = "email"


class DecisionIn(Strict):
    decision: Decision
    comment: Annotated[str | None, Field(max_length=4000, validate_default=True)] = None
    channels: list[SendChannel] | None = None

    @field_validator("comment")
    @classmethod
    def _comment_required(cls, value: str | None, info: ValidationInfo) -> str | None:
        """`return` и `reject` без комментария — 422 (runbook §2.3)."""
        if info.data.get("decision") in (Decision.RETURN, Decision.REJECT) and not (value or "").strip():
            raise ValueError("comment is required for return and reject")
        return value


class StepAssignee(BaseModel):
    crm_user_id: int | None
    permission: str | None


class ApprovalStep(BaseModel):
    index: int
    label: str
    assignee: StepAssignee
    status: Literal["pending", "current", "approved", "returned", "rejected", "skipped"]
    decided_by: PersonRef | None
    decided_at: dt.datetime | None
    comment: str | None


class ApprovalObject(BaseModel):
    kind: ApprovalTemplate
    document_id: uuid.UUID | None = None
    number: str | None = None
    erp_quote_id: int | None = None
    quote_number: str | None = None
    quote_version: int | None = None
    erp_deal_id: int | None = None
    deal_number: str | None = None

    @model_serializer(mode="wrap")
    def _only_applicable(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Документ EDS и КП ERP описываются разными полями: неприменимые не выводятся (у КП `erp_deal_id` и
        `deal_number` обязательны и могут быть `null`)."""
        data: dict[str, Any] = handler(self)
        keep_null = {"erp_deal_id", "deal_number"} if self.kind is ApprovalTemplate.QUOTE else set()
        return {key: value for key, value in data.items() if value is not None or key in keep_null}


class QuoteVisaAuthor(BaseModel):
    crm_user_id: int | None
    full_name: str


class ChecklistItem(BaseModel):
    code: Literal["visa_goods", "visa_services", "margin", "due"]
    label: str
    ok: bool
    by: QuoteVisaAuthor | None
    at: dt.datetime | None
    value: str | None


class QuoteVisa(BaseModel):
    zone: Literal["goods", "services"]
    by: QuoteVisaAuthor
    at: dt.datetime


class QuoteSnapshot(BaseModel):
    erp_quote_id: int
    number: str
    version: int
    client_name: str | None
    total: Amount
    currency: Currency
    cost: Amount | None
    margin_amount: Amount | None
    margin_pct: str
    min_margin_pct: MarginPct | None
    required_zones: list[Literal["goods", "services"]]
    visas: list[QuoteVisa]
    due: dt.date | None
    ready_at: dt.datetime
    valid_until: dt.date | None


class ApprovalListItem(BaseModel):
    id: uuid.UUID
    template: ApprovalTemplate
    title: str
    object: ApprovalObject
    status: RouteStatus
    round: int
    current_step: ApprovalStep | None
    created_at: dt.datetime


class ApprovalPage(BaseModel):
    items: list[ApprovalListItem]
    next_cursor: str | None


class Approval(BaseModel):
    id: uuid.UUID
    template: ApprovalTemplate
    title: str
    object: ApprovalObject
    status: RouteStatus
    round: int
    steps: list[ApprovalStep]
    checklist: list[ChecklistItem]
    quote: QuoteSnapshot | None
    can_decide: bool
    allowed_decisions: list[Decision]
    outgoing_number: str | None
    created_at: dt.datetime
    closed_at: dt.datetime | None
