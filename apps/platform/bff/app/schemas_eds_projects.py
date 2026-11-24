"""EDS · Проекты: схемы `Project*` из platform-bff.yaml (0.26.0, D2-5) и разбор ответа ERP.

BFF не решает: шаг пути, статус для клиента, «проблемы» и действия, доступные сотруднику сейчас
(`actions`, `can_create_contract`, `act_blocker`), считает ERP (`GET /crm/projects/`). Здесь —
модели ответа BFF (с номерами ПР и ЗВ, которых у сделки в ERP нет, B-010), тела действий (причина
отказа проверяется до сети) и «сырые» модели ответа ERP только с нужными полями.
"""

import datetime as dt
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.errors import backend_unavailable
from app.schemas_do_not_work import DoNotWork

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
ContractAction = Literal[
    "send_to_client",
    "client_agreed",
    "reject",
    "revise",
    "mark_issued",
    # ДОК-10: договор по утверждённому шаблону
    "sign_ours",
    "request_deviation",
    "decide_deviation",
]
TemplateActionCode = Literal["sign_ours", "request_deviation", "decide_deviation"]
DeviationState = Literal["none", "requested", "approved", "rejected"]
ContractPathStepKey = Literal["assembled", "our_signature", "in_cabinet", "signed_both"]
ContractPathStepState = Literal["done", "current", "next"]
ContractActionCode = Literal[
    "send_to_client", "client_agreed", "reject", "revise", "mark_issued", "attach_scan"
]
ActAction = Literal["issue", "return", "reissue"]
ActActionCode = Literal["attach_scan", "return", "reissue"]
ActBlocker = Literal["no_invoice", "act_exists", "forbidden", "not_delivered"]
DeliveryAction = Literal["in_transit", "delivered"]
JournalDocument = Literal["contract", "act", "invoice", "quote", "project"]
FileKind = Literal["contract", "invoice", "act"]
FileVariant = Literal["pdf", "scan"]


class DocumentClientLink(BaseModel):
    """Ссылка получателя на договор, счёт или акт в Кабинете (ДК-3б): адрес замаскирован ERP."""

    recipient_hint: str
    sent_at: dt.datetime
    first_opened_at: dt.datetime | None
    last_opened_at: dt.datetime | None
    expires_at: dt.datetime
    state: Literal["active", "revoked", "expired", "superseded"]


class DocumentClientLinks(BaseModel):
    """Ссылки документа проекта; «Отозвать» — пока есть живая ссылка и право отправлять документ."""

    links: list[DocumentClientLink]
    can_revoke: bool


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


class ProjectSigningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["contract", "invoice", "act"]
    document_id: int


# One ERP check (`contract_flow.send_blocker`): route visas (Х-1) and template rules (ДОК-10).
SendBlockerCode = Literal[
    "visas_not_requested",
    "visas_declined",
    "visas_pending",
    "visas_returned",
    "no_visa_holder",
    "CONTRACT_DEVIATION_PENDING",
    "CONTRACT_NEEDS_OUR_SIGNATURE",
]


class ProjectContractRef(BaseModel):
    id: int
    number: str
    status: ContractWord
    sent_to_client: bool
    # Х-1/ДОК-10: why the unsent project cannot go to the client; older ERP omits it.
    send_blocker_code: SendBlockerCode | None = None


class ProjectInvoiceRef(BaseModel):
    id: int
    number: str
    status: InvoiceWord
    count: int


class ProjectActRef(BaseModel):
    id: int
    number: str
    status: ActWord
    # ERP before СЦ-8 P6 does not send it in list rows; no scan is the safe reading.
    has_scan: bool = False


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
    #: Компания клиента в ERP и наш путь её логотипа (ЕД-3): строка реестра рисует `CompanyCell`
    client_id: int | None = None
    client_logo_url: str | None = None


class ProjectPage(BaseModel):
    items: list[ProjectRow]
    total: int
    offset: int
    limit: int


OnBehalfChannel = Literal["phone", "email", "messenger", "in_person", "paper"]


class OnBehalfNote(BaseModel):
    """Действие контрагента записал сотрудник (A1, A2 волны 18a): канал и лицо клиента."""

    channel: OnBehalfChannel
    counterparty_person: str


class ProjectJournalEntry(BaseModel):
    at: dt.datetime
    code: str
    text: str
    actor_name: str | None
    document: JournalDocument | None
    number: str | None
    reason: str
    on_behalf: OnBehalfNote | None = None


class ProjectQuote(ProjectQuoteRef):
    outgoing_number: str | None
    valid_until: dt.date | None


class ContractPathStep(BaseModel):
    key: ContractPathStepKey
    state: ContractPathStepState
    at: dt.datetime | None = None


class ProjectContractTemplate(BaseModel):
    """Договор по утверждённому шаблону (ДОК-10): имя и редакция, отступление, путь по фактам."""

    id: int | None
    name: str
    edition: int
    deviation: DeviationState
    deviation_text: str
    visas_required: bool
    steps: list[ContractPathStep]
    actions: list[TemplateActionCode]


class ProjectContractSendBlocker(BaseModel):
    """Х-1: почему проект договора нельзя отправить клиенту (визы не собраны); считает ERP."""

    code: SendBlockerCode
    message: str
    missing: list[str]
    # The same visas as route permission codes (`approvals.visa_finance`): the web translates them.
    missing_permissions: list[str] = []
    remark: str
    settings_link: bool


class ProjectContract(ProjectContractRef):
    template: ProjectContractTemplate | None = None
    total: ProjectMoney | None
    created_at: dt.datetime
    client_agreed_at: dt.datetime | None
    signed_at: dt.datetime | None
    has_pdf: bool
    has_scan: bool
    actions: list[ContractActionCode]
    # ERP до Х-1 поля не присылает: нет причины — действие решают `actions`.
    send_blocker: ProjectContractSendBlocker | None = None
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
    actions: list[DeliveryAction]
    goods_not_shipped: bool = False
    proof_name: str | None
    proof_url: str | None


class RawFulfillment(BaseModel):
    """Исполнение из ответа ERP: отметки доставки считает ERP; id вложения наружу не уходит."""

    model_config = ConfigDict(extra="ignore")

    status: str | None
    status_name: str | None
    expected_delivery_date: dt.date | None
    shipped_at: dt.datetime | None
    delivered_at: dt.datetime | None
    accepted_at: dt.datetime | None
    tracking_number: str | None
    carrier: str | None
    actions: list[DeliveryAction] = Field(default_factory=list)
    goods_not_shipped: bool = False
    proof_attachment_id: int | None = None
    proof_name: str | None = None


class ProjectDeliveryLine(BaseModel):
    line_no: int
    title: str
    quantity: float | None
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
    do_not_work: DoNotWork | None = None  # Х-8: полоса «С компанией не работаем»


# --- тела действий ----------------------------------------------------------------------------


class ContractActionIn(BaseModel):
    """Действие по договору. `reason` обязательна для `reject`, канал и лицо клиента — для
    `client_agreed` (A2): пустые BFF отклоняет (422)."""

    model_config = ConfigDict(extra="forbid")

    action: ContractAction
    reason: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=500)
    channel: OnBehalfChannel | None = None
    counterparty_person: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=4000, description="Отступление от шаблона")
    approve: bool | None = Field(default=None, description="Решение по отступлению")

    @model_validator(mode="after")
    def _reason_for_reject(self) -> "ContractActionIn":
        if self.action == "request_deviation" and not (self.text or "").strip():
            raise ValueError("text")
        if self.action == "decide_deviation" and self.approve is None:
            raise ValueError("approve")
        if self.action == "reject" and not (self.reason or "").strip():
            raise ValueError("reason")
        if self.action == "client_agreed":
            if self.channel is None:
                raise ValueError("channel")
            if not (self.counterparty_person or "").strip():
                raise ValueError("counterparty_person")
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
    number: str = ""  # `Deal.number` из ERP (erp-internal 1.8.0); BFF номер не составляет
    title: str = ""
    company_id: int | None = None
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
    act_blocker: ActBlocker | None = None  # без учёта прав (ERP: no_invoice, act_exists, forbidden)
    act_needs_delivery: bool = False  # ERP: акт иначе можно, но товар не доставлен (СЦ-9)

    @model_validator(mode="after")
    def _derive_not_delivered(self) -> Self:
        """BFF-блокер `not_delivered` выводится из флага ERP: счёт есть, акта нет, доставки нет."""
        if self.act_blocker is None and self.act_needs_delivery:
            self.act_blocker = "not_delivered"
        return self


class RawPage(_Raw):
    count: int
    results: list[RawRow]


class RawDocumentClientLinks(BaseModel):
    """Ответ ERP `…/client-links/`: лишнего наружу не отдаём (id ссылки не нужен)."""

    model_config = ConfigDict(extra="ignore")

    links: list[DocumentClientLink] = Field(default_factory=list)
    can_revoke: bool = False


class RawCard(RawRow):
    quote: ProjectQuote | None = None
    contract: ProjectContract | None = None
    can_create_contract: bool = False
    invoices: list[ProjectInvoice] = Field(default_factory=list)
    act: ProjectAct | None = None
    fulfillment: RawFulfillment | None = None
    delivery_lines: list[ProjectDeliveryLine] = Field(default_factory=list)
    journal: list[ProjectJournalEntry] = Field(default_factory=list)
    do_not_work: DoNotWork | None = None  # Х-8: отметка компании проекта


def parse[T: BaseModel](model: type[T], body: Any, what: str) -> T:
    """Ответ ERP по модели; не по форме — 503 (ERP отвечает не так, как обещает контракт)."""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise backend_unavailable("erp", f"bad_response:{what}") from exc
