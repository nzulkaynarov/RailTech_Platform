"""Схемы очереди заявок кандидатов в партнёры (PART-ONBOARD-2)."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_company import Body, ident, text

PartnerApplicationSource = Literal["public", "client_cabinet"]
PartnerApplicationStatus = Literal["submitted", "contract_sent", "approved", "rejected"]
PartnerApplicationKind = Literal["", "manufacturer", "supplier", "principal", "other"]
Language = Literal["ru", "uz", "en"]


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartnerApplicationItem(Out):
    id: str
    source: PartnerApplicationSource
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


class PartnerApplicationListResponse(Out):
    items: list[PartnerApplicationItem]
    pending_count: int


class PartnerApplicationSendContractRequest(Body):
    contract_number: str | None = Field(default=None, max_length=64)
    contract_date: str | None = None


class PartnerApplicationApproveRequest(Body):
    contract_number: str = Field(min_length=1, max_length=64)
    contract_date: str | None = None
    company_id: str | None = None
    kind: PartnerApplicationKind | None = None


class PartnerApplicationRejectRequest(Body):
    rejected_reason: str = Field(min_length=1, max_length=1000)


def to_partner_application(raw: Mapping[str, Any]) -> PartnerApplicationItem:
    matching_id = raw.get("matching_company_id")
    raw_status = raw.get("status")
    allowed_statuses = ("submitted", "contract_sent", "approved", "rejected")
    status: PartnerApplicationStatus = raw_status if raw_status in allowed_statuses else "submitted"
    raw_source = raw.get("source")
    source: PartnerApplicationSource = (
        raw_source if raw_source in ("public", "client_cabinet") else "public"
    )
    raw_kind = raw.get("kind")
    allowed_kinds = ("", "manufacturer", "supplier", "principal", "other")
    kind: PartnerApplicationKind = raw_kind if raw_kind in allowed_kinds else ""
    raw_lang = raw.get("language")
    language: Language = raw_lang if raw_lang in ("ru", "uz", "en") else "ru"
    matching_name = raw.get("matching_company_name")
    return PartnerApplicationItem(
        id=ident(raw.get("id")),
        source=source,
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
    )


def to_partner_applications_list(raw: Mapping[str, Any]) -> PartnerApplicationListResponse:
    items = [to_partner_application(item) for item in raw.get("items") or []]
    return PartnerApplicationListResponse(
        items=items,
        pending_count=int(raw.get("pending_count") or 0),
    )
