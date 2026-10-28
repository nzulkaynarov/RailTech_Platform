"""Модели EDS · Счета и оплаты (контракт platform-bff.yaml, тег `eds-payments`; D2-4).

Счета, платёжки и оплаты — ERP (`/api/v1/finance/receivables/*`), служебки к оплате — EDS
(`/documents?status=to_accountant`,
`POST /documents/{id}/payment`). Ответы BFF — подмножество ответов доменов; себестоимости, маржи и
цен поставщиков в них нет
ни в одном источнике (бухгалтер видит только итоги счёта, решение архитектора Q-D2-1-4). Тела
запросов повторяют
ограничения доменов (сумма больше нуля, дата не в будущем по `Asia/Tashkent`), чтобы отказ
приходил из BFF до сети;
остаток, статус счёта, шаг маршрута и права решают ERP и EDS.
"""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas_eds_documents import EdsDealRef, EdsFile, EdsPerson

COMPANY_TZ = ZoneInfo("Asia/Tashkent")
Day = date  # у тела `PaymentConfirmIn` поле называется `date`: имя типа не затеняется

InvoiceTab = Literal["to_issue", "awaiting", "proofs", "overdue", "all"]
DisplayStatus = Literal[
    "draft", "issued", "proof_received", "partially_paid", "paid", "overdue", "cancelled"
]
ProofSource = Literal["CABINET", "BOT", "EMAIL", "MANUAL"]
ProofStatus = Literal["PENDING", "CONFIRMED"]
MemoPayStatus = Literal["to_pay", "paid"]
SourceState = Literal["ok", "unavailable"]
Amount = Annotated[str, StringConstraints(pattern=r"^\d{1,12}\.\d{2}$")]


def today() -> date:
    return datetime.now(UTC).astimezone(COMPANY_TZ).date()


class PaymentSources(BaseModel):
    erp: SourceState
    eds: SourceState


class PaymentMoney(BaseModel):
    amount: str
    currency: str


class PaymentCounts(BaseModel):
    to_issue: int
    awaiting: int
    proofs: int
    overdue: int


class PaymentRow(BaseModel):
    id: int
    number: str
    project_number: str
    deal_id: int
    client_name: str
    amount: PaymentMoney
    paid: PaymentMoney
    balance: PaymentMoney
    issued_at: date | None
    due_date: date | None
    status: DisplayStatus
    days_overdue: int | None
    has_pending_proof: bool
    proof_received_at: datetime | None


class PaymentBoard(BaseModel):
    tab: InvoiceTab
    count: int
    counts: PaymentCounts
    memos_to_pay: int | None
    items: list[PaymentRow]
    sources: PaymentSources


class PaymentItem(BaseModel):
    description: str
    quantity: int
    unit_price: str
    total: str


class PaymentRecord(BaseModel):
    id: int
    amount: str
    paid_at: date
    method: str
    reference: str
    receipt_number: str
    has_proof: bool
    recorded_by: str | None
    created_at: datetime


class PaymentProof(BaseModel):
    id: int
    source: ProofSource
    status: ProofStatus
    original_name: str
    claimed_amount: str | None
    claimed_date: date | None
    note: str
    received_at: datetime
    recorded_by: str | None
    payment_id: int | None


class PaymentHistoryEntry(BaseModel):
    at: datetime
    code: str
    text: str
    by: str | None


class PaymentCard(PaymentRow):
    subtotal: str
    vat: str
    notes: str
    has_pdf: bool
    items: list[PaymentItem]
    payments: list[PaymentRecord]
    proofs: list[PaymentProof]
    history: list[PaymentHistoryEntry]
    payment_doc_requested_at: datetime | None
    can_confirm: bool
    can_attach_proof: bool
    can_request_proof: bool
    replayed: bool


class PaymentConfirmIn(BaseModel):
    """«Подтвердить оплату»: сумма по выписке, дата поступления, номер операции банка, платёжка
    клиента (по желанию).
    """

    model_config = ConfigDict(extra="forbid")

    amount: Amount
    date: Day
    reference: str | None = Field(default=None, max_length=255)
    proof_id: int | None = Field(default=None, ge=1)

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: str) -> str:
        try:
            ok = Decimal(value) > 0
        except InvalidOperation:
            ok = False
        if not ok:
            raise ValueError("amount must be positive")
        return value

    @field_validator("date")
    @classmethod
    def _not_future(cls, value: Day) -> Day:
        if value > today():
            raise ValueError("date must not be in the future")
        return value


# --- служебки к оплате --------------------------------------------------------------------------


class PaymentMemoRow(BaseModel):
    id: str
    number: str | None
    subject: str
    author: EdsPerson
    amount: PaymentMoney | None
    due_date: date | None
    files_count: int
    invoice_attached: bool
    status: MemoPayStatus
    paid_on: date | None
    created_at: datetime


class PaymentMemoPage(BaseModel):
    items: list[PaymentMemoRow]
    next_cursor: str | None


class PaymentMemoPayment(BaseModel):
    paid_on: date
    amount: PaymentMoney
    receipt_file_id: str | None
    note: str | None
    paid_by: EdsPerson
    recorded_at: datetime


class PaymentMemoJournal(BaseModel):
    at: datetime
    action: str
    by: EdsPerson | None
    comment: str | None


class PaymentMemoCard(BaseModel):
    id: str
    approval_id: str | None
    number: str | None
    subject: str
    text: str
    author: EdsPerson
    amount: PaymentMoney | None
    due_date: date | None
    deal: EdsDealRef | None
    files: list[EdsFile]
    document_status: str
    status: MemoPayStatus | Literal["other"]
    can_pay: bool
    can_return: bool
    payment: PaymentMemoPayment | None
    journal: list[PaymentMemoJournal]
    created_at: datetime


class PaymentMemoPayIn(BaseModel):
    """«Оплачено»: дата платежа, сумма (не больше согласованной — это проверяет EDS), платёжка и
    заметка.
    """

    model_config = ConfigDict(extra="forbid")

    paid_on: date
    amount: Amount
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    receipt_file_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: str) -> str:
        try:
            ok = Decimal(value) > 0
        except InvalidOperation:
            ok = False
        if not ok:
            raise ValueError("amount must be positive")
        return value

    @field_validator("paid_on")
    @classmethod
    def _not_future(cls, value: date) -> date:
        if value > today():
            raise ValueError("paid_on must not be in the future")
        return value
