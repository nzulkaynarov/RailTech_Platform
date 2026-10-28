"""EDS · Проекты: схемы `Project*` из platform-bff.yaml (0.26.0, D2-5) и разбор ответа ERP.

BFF не решает: шаг пути, статус для клиента, «проблемы» и действия, доступные сотруднику сейчас
(`actions`, `can_create_contract`, `act_blocker`), считает ERP (`GET /crm/projects/`). Здесь —
модели ответа BFF (с номерами ПР и ЗВ, которых у сделки в ERP нет, B-010), тела действий (причина
отказа проверяется до сети) и «сырые» модели ответа ERP только с нужными полями.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.errors import backend_unavailable

ProjectStage = Literal["CONTRACT", "PAYMENT", "DONE"]
ClientStatus = Literal[
    "contract_review",
    "contract_signing",
    "awaiting_payment",
    "fulfilling",
    "awaiting_acceptance",
    "done",
]
ProjectProblem = Literal["no_contract", "contract_rejected", "act_returned", "invoice_overdue"]
ContractWord = Literal[
    "project", "client_agreed", "issued_at_operator", "signed", "rejected", "cancelled"
]
InvoiceWord = Literal["to_issue", "issued", "partial", "paid", "overdue", "cancelled"]
ActWord = Literal["project", "returned", "issued", "signed", "cancelled"]
ContractAction = Literal["send_to_client", "client_agreed", "reject", "revise", "mark_issued"]
ContractActionCode = Literal[
    "send_to_client", "client_agreed", "reject", "revise", "mark_issued", "attach_scan"
]
ActAction = Literal["issue", "return", "reissue"]
ActActionCode = Literal["attach_scan", "return", "reissue"]
ActBlocker = Literal["no_invoice", "act_exists", "forbidden"]
JournalDocument = Literal["contract", "act", "invoice", "quote", "project"]
FileKind = Literal["contract", "invoice", "act"]
FileVariant = Literal["pdf", "scan"]


class ProjectMoney(BaseModel):
    amount: str = Field(pattern=r"^-?\d+\.\d{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ProjectPerson(BaseModel):
    id: int
    name: str


class ProjectQuoteRef(BaseModel):
    id: int
    number: str
    status: Literal["accepted"]
    version: int


class ProjectContractRef(BaseModel):
    id: int
    number: str
    status: ContractWord
    sent_to_client: bool


class ProjectInvoiceRef(BaseModel):
    id: int
    number: str
    status: InvoiceWord
    count: int


class ProjectActRef(BaseModel):
    id: int
    number: str
    status: ActWord


class ProjectDocuments(BaseModel):
    quote: ProjectQuoteRef | None
    contract: ProjectContractRef | None
    invoice: ProjectInvoiceRef | None
    act: ProjectActRef | None


class ProjectRow(BaseModel):
    number: str
    request_number: str
    title: str
    client_name: str
    step: ProjectStage
    client_status: ClientStatus
    total: ProjectMoney | None
    due_date: dt.date | None
    manager: ProjectPerson | None
    responsible: ProjectPerson | None
    documents: ProjectDocuments
    problems: list[ProjectProblem]
    created_at: dt.datetime


class ProjectPage(BaseModel):
    items: list[ProjectRow]
    total: int
    offset: int
    limit: int


class ProjectJournalEntry(BaseModel):
    at: dt.datetime
    code: str
    text: str
    actor_name: str | None
    document: JournalDocument | None
    number: str | None
    reason: str


class ProjectQuote(ProjectQuoteRef):
    outgoing_number: str | None
    valid_until: dt.date | None


class ProjectContract(ProjectContractRef):
    total: ProjectMoney | None
    created_at: dt.datetime
    client_agreed_at: dt.datetime | None
    signed_at: dt.datetime | None
    has_pdf: bool
    has_scan: bool
    actions: list[ContractActionCode]
    history: list[ProjectJournalEntry]


class ProjectInvoice(BaseModel):
    id: int
    number: str
    status: InvoiceWord
    total: ProjectMoney | None
    paid: ProjectMoney | None
    balance_due: ProjectMoney | None
    issued_at: dt.date | None
    due_date: dt.date | None
    has_pdf: bool


class ProjectAct(ProjectActRef):
    total: ProjectMoney | None
    issued_at: dt.date | None
    signed_at: dt.datetime | None
    rejection_reason: str | None
    has_pdf: bool
    has_scan: bool
    actions: list[ActActionCode]
    history: list[ProjectJournalEntry]


class ProjectFulfillment(BaseModel):
    status: str | None
    status_name: str | None
    expected_delivery_date: dt.date | None
    shipped_at: dt.datetime | None
    delivered_at: dt.datetime | None
    accepted_at: dt.datetime | None
    tracking_number: str | None
    carrier: str | None


class ProjectDeliveryLine(BaseModel):
    line_no: int
    title: str
    quantity: int | None
    unit: str
    status: str
    eta: dt.date | None
    shipped_at: dt.datetime | None
    tracking: str


class ProjectCard(ProjectRow):
    quote: ProjectQuote | None
    contract: ProjectContract | None
    can_create_contract: bool
    invoices: list[ProjectInvoice]
    act: ProjectAct | None
    act_blocker: ActBlocker | None
    fulfillment: ProjectFulfillment | None
    delivery_lines: list[ProjectDeliveryLine]
    journal: list[ProjectJournalEntry]


# --- тела действий ----------------------------------------------------------------------------


class ContractActionIn(BaseModel):
    """Действие по договору. `reason` обязательна для `reject`: пустую BFF отклоняет (422)."""

    model_config = ConfigDict(extra="forbid")

    action: ContractAction
    reason: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _reason_for_reject(self) -> "ContractActionIn":
        if self.action == "reject" and not (self.reason or "").strip():
            raise ValueError("reason")
        return self


class ActActionIn(BaseModel):
    """Действие по акту. `reason` обязательна для `return`: возврат без причины не бывает."""

    model_config = ConfigDict(extra="forbid")

    action: ActAction
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reason_for_return(self) -> "ActActionIn":
        if self.action == "return" and not (self.reason or "").strip():
            raise ValueError("reason")
        return self


class FileGenerating(BaseModel):
    detail: Literal["GENERATING"]
    retry_after: int


# --- ответ ERP ----------------------------------------------------------------------------------


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RawRow(_Raw):
    deal_id: int
    title: str = ""
    company_name: str = ""
    created_at: dt.datetime
    step: ProjectStage
    client_status: ClientStatus
    total: ProjectMoney | None = None
    manager: ProjectPerson | None = None
    responsible: ProjectPerson | None = None
    due_date: dt.date | None = None
    documents: ProjectDocuments
    problems: list[ProjectProblem] = Field(default_factory=list)


class RawPage(_Raw):
    count: int
    results: list[RawRow]


class RawCard(RawRow):
    quote: ProjectQuote | None = None
    contract: ProjectContract | None = None
    can_create_contract: bool = False
    invoices: list[ProjectInvoice] = Field(default_factory=list)
    act: ProjectAct | None = None
    act_blocker: ActBlocker | None = None
    fulfillment: ProjectFulfillment | None = None
    delivery_lines: list[ProjectDeliveryLine] = Field(default_factory=list)
    journal: list[ProjectJournalEntry] = Field(default_factory=list)


def parse[T: BaseModel](model: type[T], body: Any, what: str) -> T:
    """Ответ ERP по модели; не по форме — 503 (ERP отвечает не так, как обещает контракт)."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise backend_unavailable("erp", f"bad_response:{what}") from exc
