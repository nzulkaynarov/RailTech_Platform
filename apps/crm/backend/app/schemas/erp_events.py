"""Схемы событий ERP → CRM (M3-CRM-04, CONTRACTS §3, packages/contracts/events.schema.json)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EventType = Literal[
    "request.created",
    "deal.stage_changed",
    "quote.sent",
    "quote.viewed",
    "quote.accepted",
    "quote.rejected",
    "contract.signed",
    "invoice.issued",
    "invoice.paid",
    "invoice.overdue",
    "delivery.status_changed",
    "delivery.eta_changed",
    "act.issued",
    "act.accepted",
    "act.returned",
    "deal.won",
    "deal.lost",
    "document.created",
    "invite.sent",
    "delivery.line_accepted",
    "delivery.line_disputed",
]

DealStage = Literal[
    "request",
    "quoting",
    "quote_sent",
    "accepted",
    "contract",
    "invoiced",
    "paid",
    "fulfilment",
    "closing",
    "won",
    "lost",
]

AmountStr = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{2}$")]
CurrencyStr = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class DealRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_deal_id: int
    number: str
    title: str
    stage: DealStage
    # Сумма последнего КП, отправленного клиенту; None — КП ещё не отправлялось (FIX-29).
    amount: AmountStr | None
    currency: CurrencyStr


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["system", "staff", "client"]
    name: str | None = None


class RequestCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["crm", "cabinet", "erp"]
    erp_request_id: int | None = None
    summary: str | None = None


class DealStageChanged(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: DealStage = Field(alias="from")
    to: DealStage
    reason: str | None = None


class QuoteSent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_quote_id: int
    version: int = Field(ge=1)
    public_url: str
    valid_until: date | None = None
    total: AmountStr | None = None
    currency: CurrencyStr | None = None


class QuoteOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_quote_id: int
    version: int = Field(ge=1)
    reason: str | None = None


class ContractSigned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_contract_id: int
    number: str | None = None
    by: Literal["client", "company", "both"]


class InvoiceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_invoice_id: int
    number: str
    amount: AmountStr
    currency: CurrencyStr
    due_date: date
    link: str | None = None
    erp_document_id: int | None = None


class DeliveryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_summary: str
    line_nos: list[int] | None = None
    status: Literal["assembling", "in_transit", "ready_to_ship", "shipped", "delivered"]
    eta: date | None = None
    previous_eta: date | None = None
    tracking: str | None = None


class ActEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_act_id: int
    number: str
    reason: str | None = None
    erp_document_id: int | None = None


class DealOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: AmountStr
    currency: CurrencyStr
    lost_reason: str | None = None


class DocumentCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    erp_document_id: int
    kind: Literal["quote", "contract", "invoice", "act", "waybill", "receipt", "other"]
    number: str
    title: str | None = None


class InviteSent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[Literal["telegram", "email"]]
    erp_contact_id: int | None = None
    crm_contact_id: int | None = None


#: Тип события → статус строки в его теле (`DeliveryLineDecision.status`).
DELIVERY_LINE_EVENTS = {"delivery.line_accepted": "accepted", "delivery.line_disputed": "disputed"}


class DeliveryLineDecision(BaseModel):
    """Решение клиента по строке поставки (FIX-22/FIX-37): принял или оспорил с замечанием."""

    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(ge=1)
    title: str
    status: Literal["accepted", "disputed"]
    remark: str | None = Field(default=None, max_length=2000)
    decided_at: datetime

    @model_validator(mode="after")
    def _disputed_needs_remark(self) -> "DeliveryLineDecision":
        if self.status == "disputed" and not (self.remark or "").strip():
            raise ValueError("remark is required when status is disputed")
        return self


class ErpEventEnvelope(BaseModel):
    """Конверт входящего события ERP по events.schema.json."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    event: EventType
    occurred_at: datetime
    erp_company_id: int
    crm_client_id: int
    deal: DealRef | None = None
    actor: Actor
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _delivery_line_decision(self) -> "ErpEventEnvelope":
        """`delivery.line_*`: сделка обязательна, решает клиент, тело — DeliveryLineDecision."""
        if self.event not in DELIVERY_LINE_EVENTS:
            return self
        if self.deal is None:
            raise ValueError(f"{self.event} requires deal")
        if self.actor.type != "client":
            raise ValueError(f"{self.event} requires actor.type=client")
        decision = DeliveryLineDecision.model_validate(self.payload)
        if decision.status != DELIVERY_LINE_EVENTS[self.event]:
            raise ValueError(f"{self.event} does not match payload status {decision.status}")
        return self


class ErpWebhookReceipt(BaseModel):
    status: Literal["ok"] = "ok"
    duplicate: bool = False
