"""Схемы очереди заявок кандидатов в партнёры (PART-ONBOARD-2)."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_company import Body, ident, text

PartnerApplicationSource = Literal["public", "client_cabinet", "letter", "lead"]
PartnerApplicationStatus = Literal[
    "submitted", "contract_sent", "candidate_agreed", "approved", "rejected"
]
PartnerApplicationKind = Literal["", "manufacturer", "supplier", "principal", "other"]
Language = Literal["ru", "uz", "en"]
CompanyMatchPending = Literal["inn", "registration_number"]
InviteDelivery = Literal["queued", "sent", "failed"]
ContractSource = Literal["", "template", "upload"]
ContractApproval = Literal["", "requested", "approved", "returned"]
ContractBlocker = Literal[
    "CONTRACT_NOT_PREPARED", "CONTRACT_APPROVAL_PENDING", "CONTRACT_APPROVAL_RETURNED"
]


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartnerApplicationItem(Out):
    id: str
    source: PartnerApplicationSource
    # План 1.9: номер ВХ, если заявку завёл сотрудник по письму
    source_ref: str = ""
    status: PartnerApplicationStatus
    kind: PartnerApplicationKind
    company_name: str
    inn: str
    contact_name: str
    email: str
    phone: str
    language: Language
    categories_description: str
    contract_number: str
    contract_date: str | None
    rejected_reason: str
    created_at: str
    reviewed_at: str | None
    matching_company_id: str | None
    matching_company_name: str | None
    company_match_pending: CompanyMatchPending | None
    invite_delivery: InviteDelivery | None
    # ПД-1: договорная часть карточки — всё выведено ERP из фактов заявки
    contract_source: ContractSource
    contract_template_id: str | None
    contract_template_name: str | None
    contract_template_edition: int | None
    contract_language: str
    contract_deviation_text: str
    contract_approval: ContractApproval
    contract_approval_requested_by: str | None
    contract_approval_decided_by: str | None
    contract_approval_note: str
    contract_blocker: ContractBlocker | None
    contract_approvers: list[str]
    can_decide_contract: bool
    decision_needs_confirmation: bool
    candidate_notes: str
    candidate_returned_at: str | None
    has_signed_scan: bool
    signed_scan_at: str | None


class PartnerApplicationListResponse(Out):
    items: list[PartnerApplicationItem]
    pending_count: int


class PartnerApplicationSendContractRequest(Body):
    """Отправка подготовленного договора: номер и дата заданы при подготовке (ПД-1)."""

    contract_number: str | None = Field(default=None, max_length=64)
    contract_date: str | None = None
    company_id: str | None = None
    create_new_company: bool | None = None


class PartnerApplicationApproveRequest(Body):
    contract_number: str = Field(min_length=1, max_length=64)
    contract_date: str | None = None
    company_id: str | None = None
    create_new_company: bool | None = None
    kind: PartnerApplicationKind | None = None
    override_reason: str | None = Field(default=None, max_length=1000)


class PartnerApplicationCreateRequest(Body):
    """«Передать в работу» по входящему письму (план 1.9): заявку кандидата заводит снабжение."""

    company_name: str = Field(min_length=1, max_length=255)
    inn: str = Field(default="", max_length=32)
    kind: Literal["manufacturer", "supplier", "principal", "other"] = "supplier"
    categories_description: str = Field(min_length=1, max_length=4000)
    contact_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=32)
    language: Language = "ru"
    source_ref: str = Field(min_length=1, max_length=32)


class PartnerContractPrepareRequest(Body):
    """«Подготовить договор» из шаблона библиотеки; свой файл — отдельным запросом multipart."""

    template_id: str | None = None
    language: Language | None = None
    deviation_text: str | None = Field(default=None, max_length=4000)
    contract_number: str | None = Field(default=None, max_length=64)
    contract_date: str | None = None


class PartnerContractDecisionRequest(Body):
    decision: Literal["approve", "return"]
    confirm_self: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class PartnerContractTemplateOption(Out):
    id: str
    name: str
    edition: int
    languages: list[Language]
    is_default: bool


class PartnerContractOptions(Out):
    templates: list[PartnerContractTemplateOption]
    default_template_id: str | None
    deviations_allowed: bool
    approvers: list[str]
    can_decide: bool


class PartnerApplicationRejectRequest(Body):
    rejected_reason: str = Field(min_length=1, max_length=1000)


def _one_of(value: Any, allowed: tuple[str, ...]) -> Any:
    return value if value in allowed else None


def to_partner_application(raw: Mapping[str, Any]) -> PartnerApplicationItem:
    matching_id = raw.get("matching_company_id")
    raw_status = raw.get("status")
    allowed_statuses = ("submitted", "contract_sent", "candidate_agreed", "approved", "rejected")
    status: PartnerApplicationStatus = raw_status if raw_status in allowed_statuses else "submitted"
    raw_source = raw.get("source")
    source: PartnerApplicationSource = (
        raw_source if raw_source in ("public", "client_cabinet", "letter", "lead") else "public"
    )
    if raw.get("from_lead") is True:  # ERP отдаёт заявку из лида как письмо с признаком (ЛП-1)
        source = "lead"
    raw_kind = raw.get("kind")
    allowed_kinds = ("", "manufacturer", "supplier", "principal", "other")
    kind: PartnerApplicationKind = raw_kind if raw_kind in allowed_kinds else ""
    raw_lang = raw.get("language")
    language: Language = raw_lang if raw_lang in ("ru", "uz", "en") else "ru"
    matching_name = raw.get("matching_company_name")
    return PartnerApplicationItem(
        id=ident(raw.get("id")),
        source=source,
        source_ref=text(raw.get("source_ref")),
        status=status,
        kind=kind,
        company_name=text(raw.get("company_name")),
        inn=text(raw.get("inn")),
        contact_name=text(raw.get("contact_name")),
        email=text(raw.get("email")),
        phone=text(raw.get("phone")),
        language=language,
        categories_description=text(raw.get("categories_description")),
        contract_number=text(raw.get("contract_number")),
        contract_date=raw.get("contract_date") or None,
        rejected_reason=text(raw.get("rejected_reason")),
        created_at=str(raw.get("created_at") or ""),
        reviewed_at=str(raw.get("reviewed_at")) if raw.get("reviewed_at") else None,
        matching_company_id=str(matching_id) if matching_id is not None else None,
        matching_company_name=text(matching_name) if matching_name else None,
        company_match_pending=_one_of(
            raw.get("company_match_pending"), ("inn", "registration_number")
        ),
        invite_delivery=_one_of(raw.get("invite_delivery"), ("queued", "sent", "failed")),
        contract_source=_one_of(raw.get("contract_source"), ("template", "upload")) or "",
        contract_template_id=(
            str(raw["contract_template_id"])
            if raw.get("contract_template_id") is not None
            else None
        ),
        contract_template_name=raw.get("contract_template_name") or None,
        contract_template_edition=raw.get("contract_template_edition"),
        contract_language=text(raw.get("contract_language")),
        contract_deviation_text=text(raw.get("contract_deviation_text")),
        contract_approval=_one_of(
            raw.get("contract_approval"), ("requested", "approved", "returned")
        )
        or "",
        contract_approval_requested_by=raw.get("contract_approval_requested_by") or None,
        contract_approval_decided_by=raw.get("contract_approval_decided_by") or None,
        contract_approval_note=text(raw.get("contract_approval_note")),
        contract_blocker=_one_of(
            raw.get("contract_blocker"),
            ("CONTRACT_NOT_PREPARED", "CONTRACT_APPROVAL_PENDING", "CONTRACT_APPROVAL_RETURNED"),
        ),
        contract_approvers=[str(name) for name in raw.get("contract_approvers") or []],
        can_decide_contract=bool(raw.get("can_decide_contract")),
        decision_needs_confirmation=bool(raw.get("decision_needs_confirmation")),
        candidate_notes=text(raw.get("candidate_notes")),
        candidate_returned_at=(
            str(raw["candidate_returned_at"]) if raw.get("candidate_returned_at") else None
        ),
        has_signed_scan=bool(raw.get("has_signed_scan")),
        signed_scan_at=str(raw["signed_scan_at"]) if raw.get("signed_scan_at") else None,
    )


def to_partner_applications_list(raw: Mapping[str, Any]) -> PartnerApplicationListResponse:
    items = [to_partner_application(item) for item in raw.get("items") or []]
    return PartnerApplicationListResponse(
        items=items,
        pending_count=int(raw.get("pending_count") or 0),
    )


def to_contract_options(raw: Mapping[str, Any]) -> PartnerContractOptions:
    templates = [
        PartnerContractTemplateOption(
            id=ident(item.get("id")),
            name=text(item.get("name")),
            edition=int(item.get("edition") or 1),
            languages=[lang for lang in item.get("languages") or [] if lang in ("ru", "uz", "en")]
            or ["ru"],
            is_default=bool(item.get("is_default")),
        )
        for item in raw.get("templates") or []
    ]
    default_id = raw.get("default_template_id")
    return PartnerContractOptions(
        templates=templates,
        default_template_id=str(default_id) if default_id is not None else None,
        deviations_allowed=bool(raw.get("deviations_allowed", True)),
        approvers=[str(name) for name in raw.get("approvers") or []],
        can_decide=bool(raw.get("can_decide")),
    )
