"""Модели EDS · Создать документ и «Мои документы» (контракт platform-bff.yaml 0.17.0, тег `eds-
documents`).

Ответы BFF — подмножество ответов EDS (`eds.yaml`): документ, шаги маршрута, вложения, строки
реестра. Тела запросов
повторяют ограничения EDS (тема до 300 знаков, текст до 20 000, сумма больше нуля), чтобы отказ
приходил из BFF
до сети; «нужно до» не в прошлом по часовому поясу компании (Asia/Tashkent). Право на тип документа
и сам маршрут решает EDS.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.feeds.models import Sources

COMPANY_TZ = ZoneInfo("Asia/Tashkent")

DocumentKind = Literal["memo", "application", "report", "letter_out"]
RegistryKind = Literal[
    "letter_in",
    "letter_out",
    "quote",
    "memo",
    "application",
    "report",
    "contract",
    "invoice",
    "act",
]
DocumentStatus = Literal[
    "draft", "on_approval", "returned", "rejected", "approved", "to_accountant", "paid", "sent"
]
StepStatus = Literal["pending", "current", "approved", "returned", "rejected", "skipped"]
Decision = Literal["approve", "return", "reject"]
StatusFilter = Annotated[str, StringConstraints(pattern=r"^[a-z_]+$", max_length=32)]

DOCUMENT_KINDS: tuple[str, ...] = ("memo", "application", "report", "letter_out")


class EdsPerson(BaseModel):
    crm_user_id: int
    full_name: str


class EdsMoney(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(pattern=r"^\d+\.\d{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: str) -> str:
        if float(value) <= 0:
            raise ValueError("amount must be positive")
        return value


class EdsRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=32)


class EdsFile(BaseModel):
    id: str
    name: str
    content_type: str
    size: int


class EdsDocumentRow(BaseModel):
    kind: RegistryKind
    id: str
    number: str | None
    subject: str
    status: str
    author: EdsPerson | None
    amount: EdsMoney | None
    due_date: date | None
    created_at: datetime
    openable: bool
    project_ref: str | None = None


class EdsDocumentPage(BaseModel):
    items: list[EdsDocumentRow]
    next_cursor: str | None


class EdsRouteStep(BaseModel):
    label: str
    status: StepStatus
    decided_by: EdsPerson | None
    decided_at: datetime | None
    comment: str | None


class EdsDecision(BaseModel):
    round: int
    step: int
    decision: Decision
    comment: str | None
    by: EdsPerson
    at: datetime


class EdsDealRef(BaseModel):
    erp_deal_id: int
    number: str | None


class EdsDocument(BaseModel):
    id: str
    kind: DocumentKind
    number: str | None
    status: DocumentStatus
    version: int
    subject: str
    text: str
    author: EdsPerson
    addressee: EdsPerson | None
    amount: EdsMoney | None
    due_date: date | None
    files: list[EdsFile]
    deal: EdsDealRef | None
    recipient: EdsRecipient | None
    route: list[EdsRouteStep]
    decisions: list[EdsDecision]
    can_edit: bool
    created_at: datetime
    updated_at: datetime


def _today() -> date:
    return datetime.now(UTC).astimezone(COMPANY_TZ).date()


def _clean(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


class _Form(BaseModel):
    """Поля формы документа, общие для создания и сохранения."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=20000)
    amount: EdsMoney | None = None
    due_date: date | None = None
    file_ids: list[str] = Field(default_factory=list, max_length=50)
    erp_deal_id: int | None = None
    recipient: EdsRecipient | None = None
    submit: bool = False

    @field_validator("subject", "text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _clean(value)

    @field_validator("due_date")
    @classmethod
    def _not_past(cls, value: date | None) -> date | None:
        if value is not None and value < _today():
            raise ValueError("due_date is in the past")
        return value

    @field_validator("file_ids")
    @classmethod
    def _unique_uuids(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            canonical = str(UUID(item))
            if canonical not in seen:
                seen.append(canonical)
        return seen


class EdsDocumentIn(_Form):
    kind: DocumentKind


class EdsDocumentUpdateIn(_Form):
    pass


class EdsDealOption(BaseModel):
    erp_deal_id: int
    number: str
    title: str
    company: str | None


class EdsDealOptions(BaseModel):
    items: list[EdsDealOption]
    sources: Sources
