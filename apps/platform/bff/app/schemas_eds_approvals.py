"""EDS · КП на одобрение и документы на согласовании: схемы `Quote*` и `Memo*` из
packages/contracts/openapi/platform-bff.yaml (0.18.0) и разбор ответов EDS.

BFF не решает: статус маршрута, чек-лист КП, кто может решать шаг и что можно сделать сейчас
считает EDS. Здесь — модели ответов BFF, тела решений (обязательный комментарий проверяется до
сети) и «сырые» модели ответа EDS (`eds.yaml` `Approval`, `Document`) только с нужными полями.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.errors import backend_unavailable
from app.feeds.models import Sources, StepCode
from app.schemas_eds_documents import (
    EdsDealRef,
    EdsDecision,
    EdsFile,
    EdsMoney,
    EdsPerson,
    EdsRouteStep,
)

RouteStatus = Literal["open", "approved", "returned", "rejected"]
Decision = Literal["approve", "return", "reject"]
Channel = Literal["telegram", "cabinet", "email"]
ChecklistCode = Literal["visa_goods", "visa_services", "margin", "due"]
MemoKind = Literal["memo", "application", "report"]
MEMO_KINDS: tuple[MemoKind, ...] = ("memo", "application", "report")
DocumentStatus = Literal[
    "draft", "on_approval", "returned", "rejected", "approved", "to_accountant", "paid", "sent"
]

# --- ответ BFF: КП --------------------------------------------------------------------------------


class QuoteApprovalRow(BaseModel):
    id: str
    number: str
    version: int
    request_number: str | None
    client_name: str | None
    total: EdsMoney | None
    due: dt.date | None
    status: RouteStatus
    can_decide: bool
    outgoing_number: str | None
    created_at: dt.datetime


class QuoteApprovalPage(BaseModel):
    items: list[QuoteApprovalRow]
    next_cursor: str | None


class QuoteLine(BaseModel):
    position: int
    name: str
    quantity: int
    unit: str | None
    unit_price: str
    amount: str
    lead_time_days: int | None
    optional: bool


class QuoteTotals(BaseModel):
    currency: str
    subtotal: str | None
    vat_rate: str | None
    vat_amount: str | None
    total: str


class QuoteInternal(BaseModel):
    cost: str | None
    margin_amount: str | None
    margin_pct: str
    min_margin_pct: str | None
    payment_terms: str | None
    valid_until: dt.date | None
    supplier_price_until: dt.date | None


class QuoteChecklistLine(BaseModel):
    code: ChecklistCode
    ok: bool
    blocking: bool
    by_name: str | None
    at: dt.datetime | None
    # Значение маржи — только с группой `cost_margin`: без неё поле не передаётся совсем.
    value: str | None = None


class QuoteChannels(BaseModel):
    contact_name: str | None
    telegram: bool
    cabinet: bool
    email: bool


class QuoteLetterRef(BaseModel):
    number: str
    path: str


class QuoteCalculator(BaseModel):
    name: str
    zone: Literal["goods", "services"]


class QuoteRequestRef(BaseModel):
    number: str
    title: str | None
    path: str


class QuoteApprovalCard(BaseModel):
    id: str
    number: str
    version: int
    round: int
    status: RouteStatus
    stage: StepCode
    can_decide: bool
    allowed_decisions: list[Decision]
    approved_late: bool
    outgoing_number: str | None
    created_at: dt.datetime
    ready_at: dt.datetime | None
    due: dt.date | None
    client_name: str | None
    request: QuoteRequestRef | None
    letter: QuoteLetterRef | None
    calculated_by: list[QuoteCalculator]
    lines: list[QuoteLine] | None
    totals: QuoteTotals | None
    # Внутренний блок — группа `cost_margin`: без неё поле не передаётся совсем.
    internal: QuoteInternal | None = None
    checklist: list[QuoteChecklistLine]
    steps: list[EdsRouteStep]
    channels: QuoteChannels | None
    sources: Sources


# --- ответ BFF: документы на согласовании ---------------------------------------------------------


class MemoApprovalRow(BaseModel):
    id: str
    approval_id: str
    number: str | None
    kind: MemoKind
    subject: str
    author: EdsPerson | None
    amount: EdsMoney | None
    due_date: dt.date | None
    status: RouteStatus
    step_label: str | None
    can_decide: bool
    created_at: dt.datetime


class MemoApprovalPage(BaseModel):
    items: list[MemoApprovalRow]
    next_cursor: str | None


class MemoApprovalCard(BaseModel):
    id: str
    approval_id: str
    number: str | None
    kind: MemoKind
    subject: str
    text: str
    document_status: DocumentStatus
    status: RouteStatus
    round: int
    author: EdsPerson
    addressee: EdsPerson | None
    amount: EdsMoney | None
    due_date: dt.date | None
    files: list[EdsFile]
    deal: EdsDealRef | None
    steps: list[EdsRouteStep]
    decisions: list[EdsDecision]
    can_decide: bool
    allowed_decisions: list[Decision]
    created_at: dt.datetime
    updated_at: dt.datetime


# --- запросы --------------------------------------------------------------------------------------


class _DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    comment: str | None = Field(default=None, max_length=4000)

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        stripped = value.strip() if value is not None else None
        return stripped or None

    @model_validator(mode="after")
    def _comment_required(self) -> "_DecisionIn":
        # «Вернуть» и «Отклонить» без комментария EDS не принимает; отказ приходит из BFF до сети.
        if self.decision in ("return", "reject") and self.comment is None:
            raise ValueError("comment is required")
        return self

    def for_eds(self) -> dict[str, Any]:
        body: dict[str, Any] = {"decision": self.decision}
        if self.comment is not None:
            body["comment"] = self.comment
        return body


class MemoDecisionIn(_DecisionIn):
    pass


class QuoteDecisionIn(_DecisionIn):
    channels: list[Channel] = Field(default_factory=list, max_length=3)

    @field_validator("channels")
    @classmethod
    def _unique(cls, value: list[Channel]) -> list[Channel]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _channels_only_for_approve(self) -> "QuoteDecisionIn":
        if self.channels and self.decision != "approve":
            raise ValueError("channels are for approve only")
        return self

    def for_eds(self) -> dict[str, Any]:
        body = super().for_eds()
        if self.decision == "approve" and self.channels:
            body["channels"] = self.channels
        return body


# --- ответ EDS (`eds.yaml`, только нужные поля) ---------------------------------------------


class RawPerson(BaseModel):
    crm_user_id: int | None = None
    full_name: str


class RawStep(BaseModel):
    index: int
    label: str
    status: Literal["pending", "current", "approved", "returned", "rejected", "skipped"]
    decided_by: RawPerson | None = None
    decided_at: dt.datetime | None = None
    comment: str | None = None


class RawChecklist(BaseModel):
    code: ChecklistCode
    ok: bool
    blocking: bool = True
    by: RawPerson | None = None
    at: dt.datetime | None = None
    value: str | None = None


class RawVisa(BaseModel):
    zone: Literal["goods", "services"]
    by: RawPerson
    at: dt.datetime


class RawSnapshot(BaseModel):
    """`QuoteSnapshot`; поля маржи BFF мог вырезать (нет `cost_margin`) — они необязательны."""

    erp_quote_id: int
    total: str
    currency: str
    client_name: str | None = None
    cost: str | None = None
    margin_amount: str | None = None
    margin_pct: str | None = None
    min_margin_pct: str | None = None
    visas: list[RawVisa] = []
    due: dt.date | None = None
    ready_at: dt.datetime | None = None
    valid_until: dt.date | None = None


class RawObject(BaseModel):
    kind: str
    document_id: str | None = None
    number: str | None = None
    erp_quote_id: int | None = None
    quote_number: str | None = None
    quote_version: int | None = None
    erp_deal_id: int | None = None
    deal_number: str | None = None


class RawApproval(BaseModel):
    id: str
    template: Literal["memo", "application", "report", "quote"]
    title: str
    object: RawObject
    status: RouteStatus
    round: int = 1
    steps: list[RawStep] = []
    checklist: list[RawChecklist] = []
    quote: RawSnapshot | None = None
    can_decide: bool = False
    allowed_decisions: list[Decision] = []
    outgoing_number: str | None = None
    approved_late: bool = False
    created_at: dt.datetime


class RawListItem(BaseModel):
    id: str
    template: Literal["memo", "application", "report", "quote"]
    title: str
    object: RawObject
    status: RouteStatus
    current_step: RawStep | None = None
    created_at: dt.datetime


class RawPage(BaseModel):
    items: list[RawListItem]
    next_cursor: str | None = None


class RawDecision(BaseModel):
    round: int
    step: int
    decision: Decision
    comment: str | None = None
    by: RawPerson
    at: dt.datetime


class RawFile(BaseModel):
    id: str
    name: str
    content_type: str
    size: int


class RawMoney(BaseModel):
    amount: str
    currency: str


class RawDocument(BaseModel):
    id: str
    kind: str
    number: str | None = None
    status: DocumentStatus
    subject: str
    text: str
    author: RawPerson
    addressee: RawPerson | None = None
    amount: RawMoney | None = None
    due_date: dt.date | None = None
    files: list[RawFile] = []
    erp_deal_id: int | None = None
    deal_number: str | None = None
    approval_id: str | None = None
    decisions: list[RawDecision] = []
    created_at: dt.datetime
    updated_at: dt.datetime


def parse[T: BaseModel](model: type[T], raw: Any, what: str) -> T:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", f"bad_{what}") from exc


def person(p: RawPerson | None) -> EdsPerson | None:
    if p is None or p.crm_user_id is None:
        return None
    return EdsPerson(crm_user_id=p.crm_user_id, full_name=p.full_name)


def route_step(step: RawStep) -> EdsRouteStep:
    return EdsRouteStep(
        label=step.label,
        status=step.status,
        decided_by=person(step.decided_by),
        decided_at=step.decided_at,
        comment=step.comment,
    )
