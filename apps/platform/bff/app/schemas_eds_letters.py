"""EDS · Входящие письма и резолюция: схемы `Letter*` и `Resolution*` из
packages/contracts/openapi/platform-bff.yaml (0.16.0) и перевод письма EDS в карточку Платформы.

BFF не решает: статус письма, права `letters.*`, срок и исполнителей проверяет EDS. Здесь — модели
запросов (форма, без решений), разбор ответа EDS (`eds.yaml` `Letter`) и сборка карточки: связи
письма (клиент, заявка), шаг пути заявки по `docs/architecture/integration-map.md` §2 и поле
«маржа» только тем, у кого есть группа `cost_margin`.
"""

import datetime as dt
import re
import uuid
from typing import Any, Literal
from urllib.parse import quote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from app.errors import backend_unavailable
from app.feeds.models import PersonRef, Sources, StepCode
from app.feeds.numbers import deal_kind, deal_step, request_path
from app.schemas import initials_of

LetterStatus = Literal[
    "awaiting_resolution",
    "resolved",
    "returned",
    "rejected",
    # P8b (SPEC-v3 §3.2a): путь делопроизводства
    "in_execution",
    "executed",
    "noted",
]
# P8b: путь резолюции (решает EDS) и тип резолюции делопроизводства.
LetterTrack = Literal["calc", "office"]
ResolutionKind = Literal["execute", "reply", "info"]
InstructionRole = Literal["responsible", "co_executor"]
InstructionStatus = Literal["in_work", "executed"]
ExtensionStatus = Literal["pending", "approved", "rejected"]
_USER_ID = r"^[1-9][0-9]*$"
LetterZone = Literal["goods", "services", "payment_terms"]
# P8 (SPEC-v3 §3.2a п. 1): способ получения входящего.
ReceiptMethod = Literal["post", "paper", "taxpayer_cabinet", "courier", "email"]
RelatedKind = Literal["letter_in", "letter_out"]
_KIND_CODE = r"^[a-z][a-z_]{0,31}$"
ZONES: tuple[LetterZone, ...] = ("goods", "services", "payment_terms")

_MARGIN = r"^(100(\.0{1,2})?|\d{1,2}(\.\d{1,2})?)$"
# Шаги шкалы 1–7 (SPEC-v3 §2.3): резолюция — второй, расчёт — третий.
_ORDER: tuple[StepCode, ...] = (
    "REQUEST",
    "RESOLUTION",
    "CALCULATION",
    "QUOTE",
    "CONTRACT",
    "PAYMENT",
    "DONE",
)
RESOLUTION_STEP = 2

# --- ответ BFF ---------------------------------------------------------------------------------


class LetterSender(BaseModel):
    name: str | None
    inn: str | None
    contact: str | None


class LetterSenderRef(BaseModel):
    number: str | None
    date: dt.date | None


class LetterRow(BaseModel):
    id: str
    number: str
    subject: str
    client_name: str | None
    request_number: str | None
    received_at: dt.date
    status: LetterStatus
    urgent: bool
    due: dt.date | None
    kind: str | None = None
    track: LetterTrack = "calc"
    on_control: bool = False
    overdue: bool = False
    executor: PersonRef | None = None


class LetterPage(BaseModel):
    items: list[LetterRow]
    next_cursor: str | None


class LetterFile(BaseModel):
    id: str
    name: str
    content_type: str
    size: int = Field(ge=0)
    uploaded_at: dt.datetime


class LetterClient(BaseModel):
    id: str
    name: str | None
    inn: str | None
    path: str


class LetterRequest(BaseModel):
    number: str
    title: str | None
    path: str


class LetterAssignee(BaseModel):
    person: PersonRef
    zone: LetterZone


class LetterResolution(BaseModel):
    text: str
    assignees: list[LetterAssignee]
    due: dt.date
    # Без группы `cost_margin` поле не передаётся совсем (ответ с `exclude_unset`).
    min_margin_pct: str | None = None
    decided_by: PersonRef
    decided_at: dt.datetime


class LetterJournalEntry(BaseModel):
    at: dt.datetime
    action: str
    by: PersonRef | None
    comment: str | None


class LetterRelated(BaseModel):
    kind: RelatedKind
    number: str
    path: str


class LetterResolutionDraft(BaseModel):
    kind: ResolutionKind | None
    responsible: PersonRef | None
    due: dt.date | None
    text: str | None
    co_executors: list[PersonRef]
    acquaint: list[PersonRef]
    drafted_by: PersonRef
    drafted_at: dt.datetime


class LetterOfficeResolution(BaseModel):
    kind: ResolutionKind
    text: str
    due: dt.date | None
    responsible: PersonRef | None
    co_executors: list[PersonRef]
    acquaint: list[PersonRef]
    decided_by: PersonRef
    decided_at: dt.datetime


class LetterInstructionExtension(BaseModel):
    id: str
    old_due: dt.date
    new_due: dt.date
    reason: str
    status: ExtensionStatus
    requested_by: PersonRef
    requested_at: dt.datetime
    decided_by: PersonRef | None
    decided_at: dt.datetime | None
    comment: str | None


class LetterInstructionOutgoing(BaseModel):
    number: str
    path: str


class LetterInstruction(BaseModel):
    id: str
    kind: ResolutionKind
    role: InstructionRole
    person: PersonRef
    due: dt.date
    text: str
    status: InstructionStatus
    overdue: bool
    report: str | None
    files: list[LetterFile]
    outgoing: LetterInstructionOutgoing | None
    executed_at: dt.datetime | None
    extensions: list[LetterInstructionExtension]


class LetterAcquaintance(BaseModel):
    person: PersonRef
    acknowledged_at: dt.datetime | None


class LetterCard(BaseModel):
    id: str
    number: str
    status: LetterStatus
    subject: str
    summary: str
    urgent: bool
    received_at: dt.date
    registered_at: dt.datetime
    registered_by: PersonRef | None
    addressee: PersonRef
    manager: PersonRef | None
    sender: LetterSender
    sender_ref: LetterSenderRef
    client: LetterClient | None
    request: LetterRequest | None
    stage: StepCode
    lost_at_step: int | None
    files: list[LetterFile]
    resolution: LetterResolution | None
    return_comment: str | None
    reject_reason: str | None
    journal: list[LetterJournalEntry]
    sources: Sources
    # Карточка делопроизводства (P8); у писем по заявкам — `null`.
    kind: str | None = None
    receipt_method: ReceiptMethod | None = None
    signed_by: str | None = None
    document_due: dt.date | None = None
    related: LetterRelated | None = None
    # P8b: путь резолюции, проект, резолюция делопроизводства, поручения и ознакомление.
    track: LetterTrack = "calc"
    on_control: bool = False
    suggested_due: dt.date | None = None
    resolution_draft: LetterResolutionDraft | None = None
    office_resolution: LetterOfficeResolution | None = None
    instructions: list[LetterInstruction] = []
    acquaintances: list[LetterAcquaintance] = []
    executed_at: dt.datetime | None = None


class LetterKindName(BaseModel):
    ru: str
    uz: str
    en: str


class LetterKind(BaseModel):
    code: str
    name: LetterKindName
    urgent: bool


class LetterKindList(BaseModel):
    items: list[LetterKind]


class LetterDuplicate(BaseModel):
    id: str
    number: str
    subject: str
    received_at: dt.date
    status: LetterStatus
    path: str


class LetterDuplicateList(BaseModel):
    items: list[LetterDuplicate]


class ResolutionCandidate(BaseModel):
    id: str
    name: str
    initials: str = Field(max_length=3)
    position: str | None


class ResolutionZone(BaseModel):
    zone: LetterZone
    candidates: list[ResolutionCandidate]


class ResolutionAssignees(BaseModel):
    zones: list[ResolutionZone]
    directory: Literal["ok", "forbidden", "unavailable"]


class EdsStaffMember(BaseModel):
    id: str
    name: str
    position: str | None


class EdsStaffList(BaseModel):
    items: list[EdsStaffMember]


# --- запросы (форма; решения — в EDS) ---------------------------------------------------------


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("не может быть пустым")
    return value.strip()


class ResolutionAssigneeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[1-9][0-9]*$")
    zone: LetterZone


class ResolutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    assignees: list[ResolutionAssigneeIn] = Field(min_length=1, max_length=12)
    due: dt.date
    min_margin_pct: str | None = Field(default=None, pattern=_MARGIN)

    _text = field_validator("text")(_not_blank)

    def for_eds(self) -> dict[str, Any]:
        """Тело EDS `ResolutionIn`: сотрудники числом, срок датой, маржа строкой или `null`."""
        return {
            "text": self.text,
            "assignees": [{"crm_user_id": int(a.id), "zone": a.zone} for a in self.assignees],
            "due": self.due.isoformat(),
            "min_margin_pct": self.min_margin_pct,
        }


def _check_ids(value: list[str]) -> list[str]:
    for item in value:
        if not re.fullmatch(_USER_ID, item):
            raise ValueError("ожидается crm_user_id")
    return value


def _ids(values: list[str]) -> list[int]:
    return [int(v) for v in dict.fromkeys(values)]


def _user(value: str | None) -> int | None:
    return int(value) if value is not None else None


class ResolutionDraftIn(BaseModel):
    """Проект резолюции делопроизводителя (P8b); все поля необязательны, решения — в EDS."""

    model_config = ConfigDict(extra="forbid")

    kind: ResolutionKind | None = None
    responsible_id: str | None = Field(default=None, pattern=_USER_ID)
    due: dt.date | None = None
    text: str | None = Field(default=None, max_length=4000)
    co_executor_ids: list[str] = Field(default_factory=list, max_length=20)
    acquaint_ids: list[str] = Field(default_factory=list, max_length=50)

    _lists = field_validator("co_executor_ids", "acquaint_ids")(_check_ids)

    def for_eds(self) -> dict[str, Any]:
        text = self.text.strip() if self.text is not None else None
        return {
            "kind": self.kind,
            "responsible_crm_user_id": _user(self.responsible_id),
            "due": self.due.isoformat() if self.due else None,
            "text": text or None,
            "co_executor_ids": _ids(self.co_executor_ids),
            "acquaint_ids": _ids(self.acquaint_ids),
        }


class OfficeResolutionIn(BaseModel):
    """Резолюция делопроизводства (P8b): тип, ответственный, срок, текст и люди."""

    model_config = ConfigDict(extra="forbid")

    kind: ResolutionKind
    responsible_id: str | None = Field(default=None, pattern=_USER_ID)
    due: dt.date | None = None
    text: str = Field(min_length=1, max_length=4000)
    co_executor_ids: list[str] = Field(default_factory=list, max_length=20)
    acquaint_ids: list[str] = Field(default_factory=list, max_length=50)

    _text = field_validator("text")(_not_blank)
    _lists = field_validator("co_executor_ids", "acquaint_ids")(_check_ids)

    def for_eds(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "responsible_crm_user_id": _user(self.responsible_id),
            "due": self.due.isoformat() if self.due else None,
            "text": self.text,
            "co_executor_ids": _ids(self.co_executor_ids),
            "acquaint_ids": _ids(self.acquaint_ids),
        }


class InstructionCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: str | None = Field(default=None, max_length=10000)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    outgoing_number: str | None = Field(default=None, min_length=1, max_length=32)

    def for_eds(self) -> dict[str, Any]:
        report = self.report.strip() if self.report is not None else None
        number = self.outgoing_number.strip() if self.outgoing_number is not None else None
        return {
            "report": report or None,
            "file_ids": [str(f) for f in dict.fromkeys(self.file_ids)],
            "outgoing_number": number or None,
        }


class InstructionExtensionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_due: dt.date
    reason: str = Field(min_length=1, max_length=2000)

    _reason = field_validator("reason")(_not_blank)

    def for_eds(self) -> dict[str, Any]:
        return {"new_due": self.new_due.isoformat(), "reason": self.reason}


class InstructionExtensionDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)

    def for_eds(self) -> dict[str, Any]:
        comment = self.comment.strip() if self.comment is not None else None
        return {"decision": self.decision, "comment": comment or None}


class LetterRegisterIn(BaseModel):
    """Форма «Зарегистрировать входящее» (P8, SPEC-v3 §3.2a п. 1); решения — в EDS (вид, связь)."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=_KIND_CODE)
    receipt_method: ReceiptMethod
    sender_name: str = Field(min_length=1, max_length=255)
    sender_inn: str | None = Field(default=None, pattern=r"^\d{9,14}$")
    received_at: dt.date
    subject: str = Field(min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=10000)
    sender_ref_number: str | None = Field(default=None, max_length=64)
    sender_ref_date: dt.date | None = None
    signed_by: str | None = Field(default=None, max_length=255)
    document_due: dt.date | None = None
    urgent: bool = False
    erp_deal_id: int | None = Field(default=None, ge=1)
    deal_number: str | None = Field(default=None, max_length=64)
    crm_client_id: int | None = Field(default=None, ge=1)
    related_number: str | None = Field(default=None, min_length=1, max_length=32)
    # P8b: адресат (нет — директор) и проект резолюции делопроизводителя.
    addressee_id: str | None = Field(default=None, pattern=_USER_ID)
    resolution_draft: ResolutionDraftIn | None = None
    # W18A-P2: письмо общего ящика (очередь «Входящая почта») — EDS вернёт его в `letter.registered`
    source_mail_id: int | None = Field(default=None, ge=1)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    _sender = field_validator("sender_name")(_not_blank)

    @field_validator("file_ids")
    @classmethod
    def _file_required(cls, value: list[uuid.UUID], info: ValidationInfo) -> list[uuid.UUID]:
        """Нужен хотя бы один файл; письмо общего ящика без вложений — исключение."""
        if not value and info.data.get("source_mail_id") is None:
            raise ValueError("at least one file is required")
        return value

    _subject = field_validator("subject")(_not_blank)

    def for_eds(self) -> dict[str, Any]:
        """Тело EDS `LetterCreate`: пустые строки — `null`, связи — `links`."""

        def text(value: str | None) -> str | None:
            return value.strip() or None if value is not None else None

        ref_number = text(self.sender_ref_number)
        links = {
            key: value
            for key, value in (
                ("erp_deal_id", self.erp_deal_id),
                ("deal_number", text(self.deal_number)),
                ("crm_client_id", self.crm_client_id),
            )
            if value is not None
        }
        body: dict[str, Any] = {
            "kind": self.kind,
            "receipt_method": self.receipt_method,
            "subject": self.subject,
            "sender": {"name": self.sender_name, "inn": self.sender_inn},
            "received_at": self.received_at.isoformat(),
            "urgent": self.urgent,
            "file_ids": [str(f) for f in dict.fromkeys(self.file_ids)],
            "signed_by": text(self.signed_by),
            "document_due": self.document_due.isoformat() if self.document_due else None,
            "related_number": text(self.related_number),
        }
        summary = text(self.summary)
        if summary is not None:
            body["summary"] = summary
        if ref_number is not None or self.sender_ref_date is not None:
            body["sender_ref"] = {
                "number": ref_number,
                "date": self.sender_ref_date.isoformat() if self.sender_ref_date else None,
            }
        if links:
            body["links"] = links
        if self.addressee_id is not None:
            body["addressee_crm_user_id"] = int(self.addressee_id)
        if self.resolution_draft is not None:
            body["resolution_draft"] = self.resolution_draft.for_eds()
        if self.source_mail_id is not None:
            body["source"] = {"crm_inbound_mail_id": self.source_mail_id}
        return body


class LetterReturnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=4000)

    _comment = field_validator("comment")(_not_blank)


class LetterRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)

    _reason = field_validator("reason")(_not_blank)


# --- ответ EDS (`eds.yaml`, только нужные поля) ------------------------------------------------


class _Person(BaseModel):
    crm_user_id: int
    full_name: str


class _Sender(BaseModel):
    name: str | None = None
    inn: str | None = None
    contact: str | None = None


class _SenderRef(BaseModel):
    number: str | None = None
    date: dt.date | None = None


class _Links(BaseModel):
    erp_request_id: int | None = None
    erp_deal_id: int | None = None
    deal_number: str | None = None
    crm_client_id: int | None = None
    erp_company_id: int | None = None


class _File(BaseModel):
    id: str
    name: str
    content_type: str
    size: int
    uploaded_at: dt.datetime


class _Assignee(BaseModel):
    crm_user_id: int
    zone: LetterZone
    full_name: str | None = None


class _Resolution(BaseModel):
    text: str
    assignees: list[_Assignee]
    due: dt.date
    min_margin_pct: str | None = None
    decided_by: _Person
    decided_at: dt.datetime


class _Related(BaseModel):
    kind: RelatedKind
    id: str
    number: str


class _Draft(BaseModel):
    kind: ResolutionKind | None = None
    responsible: _Person | None = None
    due: dt.date | None = None
    text: str | None = None
    co_executors: list[_Person] = []
    acquaint: list[_Person] = []
    drafted_by: _Person
    drafted_at: dt.datetime


class _OfficeResolution(BaseModel):
    kind: ResolutionKind
    text: str
    due: dt.date | None = None
    responsible: _Person | None = None
    co_executors: list[_Person] = []
    acquaint: list[_Person] = []
    decided_by: _Person
    decided_at: dt.datetime


class _Outgoing(BaseModel):
    id: str
    number: str


class _Extension(BaseModel):
    id: str
    old_due: dt.date
    new_due: dt.date
    reason: str
    status: ExtensionStatus
    requested_by: _Person
    requested_at: dt.datetime
    decided_by: _Person | None = None
    decided_at: dt.datetime | None = None
    comment: str | None = None


class _Instruction(BaseModel):
    id: str
    kind: ResolutionKind
    role: InstructionRole
    person: _Person
    due: dt.date
    text: str
    status: InstructionStatus
    overdue: bool = False
    report: str | None = None
    files: list[_File] = []
    outgoing: _Outgoing | None = None
    executed_at: dt.datetime | None = None
    extensions: list[_Extension] = []


class _Acquaintance(BaseModel):
    person: _Person
    acknowledged_at: dt.datetime | None = None


class _Journal(BaseModel):
    at: dt.datetime
    action: str
    by: _Person | None = None
    comment: str | None = None


class EdsLetter(BaseModel):
    """`Letter` EDS: карточка с резолюцией и журналом."""

    id: str
    number: str
    status: LetterStatus
    subject: str
    summary: str
    sender: _Sender
    sender_ref: _SenderRef = _SenderRef()
    received_at: dt.date
    registered_at: dt.datetime
    registered_by: _Person | None = None
    addressee: _Person
    manager: _Person | None = None
    urgent: bool = False
    links: _Links
    files: list[_File] = []
    resolution: _Resolution | None = None
    return_comment: str | None = None
    reject_reason: str | None = None
    journal: list[_Journal] = []
    kind: str | None = None
    receipt_method: ReceiptMethod | None = None
    signed_by: str | None = None
    document_due: dt.date | None = None
    related: _Related | None = None
    track: LetterTrack | None = None
    on_control: bool = False
    suggested_due: dt.date | None = None
    resolution_draft: _Draft | None = None
    office_resolution: _OfficeResolution | None = None
    instructions: list[_Instruction] = []
    acquaintances: list[_Acquaintance] = []
    executed_at: dt.datetime | None = None


class _EdsRow(BaseModel):
    id: str
    number: str
    subject: str
    sender: _Sender
    received_at: dt.date
    status: LetterStatus
    links: _Links
    urgent: bool = False
    due: dt.date | None = None
    kind: str | None = None
    track: LetterTrack | None = None
    on_control: bool = False
    overdue: bool = False
    executor: _Person | None = None


class _EdsPage(BaseModel):
    items: list[_EdsRow]
    next_cursor: str | None = None


def track_of(track: LetterTrack | None, links: _Links, kind: str | None) -> LetterTrack:
    """Путь резолюции: решает EDS; старый EDS без поля — то же правило (SPEC-v3 §3.2a)."""
    if track is not None:
        return track
    if links.erp_request_id is not None or (kind is None and links.erp_deal_id is not None):
        return "calc"
    return "office"


def parse_letter(raw: Any) -> EdsLetter:
    try:
        return EdsLetter.model_validate(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_letter") from exc


def to_page(raw: Any) -> LetterPage:
    try:
        page = _EdsPage.model_validate(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_page") from exc
    return LetterPage(
        items=[
            LetterRow(
                id=row.id,
                number=row.number,
                subject=row.subject,
                client_name=row.sender.name,
                request_number=row.links.deal_number,
                received_at=row.received_at,
                status=row.status,
                urgent=row.urgent,
                due=row.due,
                kind=row.kind,
                track=track_of(row.track, row.links, row.kind),
                on_control=row.on_control,
                overdue=row.overdue,
                executor=person(row.executor) if row.executor else None,
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
    )


# --- карточка ----------------------------------------------------------------------------------


def letter_path(number: str) -> str:
    """Карточка ВХ в SPA по номеру (`/eds/inbox/ВХ-104%2F26`)."""
    return f"/eds/inbox/{quote(number, safe='')}"


def outgoing_path(document_id: str) -> str:
    """Наш ИСХ в реестре «Все документы» с открытой карточкой."""
    return f"/eds/documents?scope=all&doc={quote(document_id, safe='')}&panel=open"


def _related(related: _Related | None) -> LetterRelated | None:
    if related is None:
        return None
    path = letter_path(related.number) if related.kind == "letter_in" else outgoing_path(related.id)
    return LetterRelated(kind=related.kind, number=related.number, path=path)


def person(p: _Person) -> PersonRef:
    return PersonRef(id=str(p.crm_user_id), name=p.full_name, initials=initials_of(p.full_name, ""))


def letter_stage(status: LetterStatus, deal: dict[str, Any] | None) -> tuple[StepCode, int | None]:
    """Шаг пути заявки по письму (integration-map §2, процесс v3) и данным заявки ERP.

    Закрытая заявка ERP (`CLOSED_LOST`) — «Отказ» при любом статусе письма; отклонено — «Отказ» на
    шаге 2. Иначе: ждёт резолюции — «Резолюция»; возвращено — письмо у менеджера, «Заявка».
    Резолюция наложена — «Расчёт», а если заявка в ERP уже дальше (КП, договор, оплата,
    выполнено) — её шаг; закрытая заявка — «Отказ». ERP не ответил (`deal` нет) — «Расчёт»: так
    письмо видно по его собственному статусу.
    """
    # Отказ — первым (integration-map §2): закрытая заявка — «Отказ» при любом статусе письма.
    deal_lost = deal is not None and deal_step(deal) == "LOST"
    if status == "rejected":
        return "LOST", RESOLUTION_STEP
    if deal_lost:
        return "LOST", None
    if status == "awaiting_resolution":
        return "RESOLUTION", None
    if status == "returned":
        return "REQUEST", None
    if status in ("in_execution", "executed", "noted"):
        # Путь делопроизводства (P8b): расчёта нет, шкала заявки не применяется.
        return "RESOLUTION", None
    if deal is not None:
        step = deal_step(deal)
        if step in _ORDER and _ORDER.index(step) > _ORDER.index("CALCULATION"):
            return step, None
    return "CALCULATION", None


def _request_path(number: str, deal: dict[str, Any] | None) -> str:
    """Заявка открывается в «Заявках в расчёте» (окно «Задание», B-UIA-1), а после принятия КП
    клиентом (договор и дальше) — проект в EDS под тем же сквозным номером (`ЗВ-2026-104` ->
    `ПР-2026-104`, SPEC-v3 §2.2)."""
    if deal is not None and deal_kind(deal_step(deal)) == "project":
        project = f"ПР-{number.removeprefix('ЗВ-')}" if number.startswith("ЗВ-") else number
        return f"/eds/projects/{quote(project, safe='')}?panel=open&tab=card"
    return request_path(number)


def _deal_title(deal: dict[str, Any] | None) -> str | None:
    title = deal.get("title") if deal is not None else None
    return title.strip() if isinstance(title, str) and title.strip() else None


def _file(f: _File) -> LetterFile:
    return LetterFile(
        id=f.id, name=f.name, content_type=f.content_type, size=f.size, uploaded_at=f.uploaded_at
    )


def _people(items: list[_Person]) -> list[PersonRef]:
    return [person(p) for p in items]


def _draft(d: _Draft | None) -> LetterResolutionDraft | None:
    if d is None:
        return None
    return LetterResolutionDraft(
        kind=d.kind,
        responsible=person(d.responsible) if d.responsible else None,
        due=d.due,
        text=d.text,
        co_executors=_people(d.co_executors),
        acquaint=_people(d.acquaint),
        drafted_by=person(d.drafted_by),
        drafted_at=d.drafted_at,
    )


def _office(r: _OfficeResolution | None) -> LetterOfficeResolution | None:
    if r is None:
        return None
    return LetterOfficeResolution(
        kind=r.kind,
        text=r.text,
        due=r.due,
        responsible=person(r.responsible) if r.responsible else None,
        co_executors=_people(r.co_executors),
        acquaint=_people(r.acquaint),
        decided_by=person(r.decided_by),
        decided_at=r.decided_at,
    )


def _instruction(i: _Instruction) -> LetterInstruction:
    return LetterInstruction(
        id=i.id,
        kind=i.kind,
        role=i.role,
        person=person(i.person),
        due=i.due,
        text=i.text,
        status=i.status,
        overdue=i.overdue,
        report=i.report,
        files=[_file(f) for f in i.files],
        outgoing=(
            LetterInstructionOutgoing(number=i.outgoing.number, path=outgoing_path(i.outgoing.id))
            if i.outgoing
            else None
        ),
        executed_at=i.executed_at,
        extensions=[
            LetterInstructionExtension(
                id=e.id,
                old_due=e.old_due,
                new_due=e.new_due,
                reason=e.reason,
                status=e.status,
                requested_by=person(e.requested_by),
                requested_at=e.requested_at,
                decided_by=person(e.decided_by) if e.decided_by else None,
                decided_at=e.decided_at,
                comment=e.comment,
            )
            for e in i.extensions
        ],
    )


def to_card(
    letter: EdsLetter, *, deal: dict[str, Any] | None, sources: Sources, show_margin: bool
) -> LetterCard:
    links = letter.links
    client = (
        LetterClient(
            id=str(links.crm_client_id),
            name=letter.sender.name,
            inn=letter.sender.inn,
            path=f"/crm/clients/{links.crm_client_id}",
        )
        if links.crm_client_id is not None
        else None
    )
    request = (
        LetterRequest(
            number=links.deal_number,
            title=_deal_title(deal),
            path=_request_path(links.deal_number, deal),
        )
        if links.deal_number
        else None
    )
    stage, lost_at = letter_stage(letter.status, deal)
    resolution: LetterResolution | None = None
    if letter.resolution is not None:
        res = letter.resolution
        shown: dict[str, Any] = {"min_margin_pct": res.min_margin_pct} if show_margin else {}
        resolution = LetterResolution(
            text=res.text,
            assignees=[
                LetterAssignee(
                    person=PersonRef(
                        id=str(a.crm_user_id),
                        name=a.full_name or f"№{a.crm_user_id}",
                        initials=initials_of(a.full_name or "", ""),
                    ),
                    zone=a.zone,
                )
                for a in res.assignees
            ],
            due=res.due,
            decided_by=person(res.decided_by),
            decided_at=res.decided_at,
            **shown,
        )
    return LetterCard(
        id=letter.id,
        number=letter.number,
        status=letter.status,
        subject=letter.subject,
        summary=letter.summary,
        urgent=letter.urgent,
        received_at=letter.received_at,
        registered_at=letter.registered_at,
        registered_by=person(letter.registered_by) if letter.registered_by else None,
        addressee=person(letter.addressee),
        manager=person(letter.manager) if letter.manager else None,
        sender=LetterSender(
            name=letter.sender.name, inn=letter.sender.inn, contact=letter.sender.contact
        ),
        sender_ref=LetterSenderRef(number=letter.sender_ref.number, date=letter.sender_ref.date),
        client=client,
        request=request,
        stage=stage,
        lost_at_step=lost_at,
        files=[_file(f) for f in letter.files],
        resolution=resolution,
        return_comment=letter.return_comment,
        reject_reason=letter.reject_reason,
        journal=[
            LetterJournalEntry(
                at=j.at,
                action=j.action,
                by=person(j.by) if j.by else None,
                comment=j.comment,
            )
            for j in letter.journal
        ],
        sources=sources,
        kind=letter.kind,
        receipt_method=letter.receipt_method,
        signed_by=letter.signed_by,
        document_due=letter.document_due,
        related=_related(letter.related),
        track=track_of(letter.track, links, letter.kind),
        on_control=letter.on_control,
        suggested_due=letter.suggested_due,
        resolution_draft=_draft(letter.resolution_draft),
        office_resolution=_office(letter.office_resolution),
        instructions=[_instruction(i) for i in letter.instructions],
        acquaintances=[
            LetterAcquaintance(person=person(a.person), acknowledged_at=a.acknowledged_at)
            for a in letter.acquaintances
        ],
        executed_at=letter.executed_at,
    )


NUMBER_RE = re.compile(r"^ВХ-\d{3,}/\d{2}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
