"""Шаблоны договоров с утверждением (ДОК-10, DECISIONS 2026-11-23).

Список, редакции, утверждение, предложение в сделке. Данные и права — в ERP (`DocumentTemplate`,
право `contract.approve_template` держателя зоны «Право»). BFF переводит ответ ERP в контракт.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_company import ident, opt_ident, text

TemplateStatus = Literal["draft", "on_approval", "approved"]
Counterparty = Literal["client", "partner"]
Subject = Literal["supply", "services"]
Lang = Literal["ru", "uz", "en"]


class ContractTemplate(BaseModel):
    id: str
    name: str
    edition: int
    status: TemplateStatus
    counterparty: Counterparty | None
    subject: Subject | None
    approved_by: str | None
    approved_at: dt.datetime | None
    submitted_at: dt.datetime | None
    is_active: bool
    locked: bool = Field(description="Закреплённый текст: правится только новой редакцией")
    languages: list[Lang]
    updated_at: str


class ContractTemplateList(BaseModel):
    items: list[ContractTemplate]


class ContractTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    counterparty: Counterparty
    subject: Subject


class OfferedContractTemplates(BaseModel):
    """Предлагаемые в сделке шаблоны: утверждённые, вида контрагента; `default_id` — из настроек."""

    counterparty: Counterparty
    default_id: str | None
    items: list[ContractTemplate]


def _when(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def to_contract_template(raw: Mapping[str, Any]) -> ContractTemplate:
    status = raw.get("approval_status")
    counterparty = raw.get("counterparty_kind")
    subject = raw.get("subject")
    langs = [lang for lang in raw.get("languages") or [] if lang in ("ru", "uz", "en")]
    return ContractTemplate(
        id=ident(raw.get("id")),
        name=text(raw.get("name")),
        edition=raw.get("edition") if isinstance(raw.get("edition"), int) else 1,
        status=status if status in ("draft", "on_approval", "approved") else "draft",
        counterparty=counterparty if counterparty in ("client", "partner") else None,
        subject=subject if subject in ("supply", "services") else None,
        approved_by=text(raw.get("approved_by_name")) or None,
        approved_at=_when(raw.get("approved_at")),
        submitted_at=_when(raw.get("submitted_at")),
        is_active=raw.get("is_active") is True,
        locked=raw.get("is_locked") is True,
        languages=langs or ["ru"],
        updated_at=text(raw.get("updated_at")),
    )


def to_offered(raw: Mapping[str, Any]) -> OfferedContractTemplates:
    kind = raw.get("counterparty_kind")
    return OfferedContractTemplates(
        counterparty=kind if kind in ("client", "partner") else "client",
        default_id=opt_ident(raw.get("default_id")),
        items=[to_contract_template(r) for r in raw.get("items") or [] if isinstance(r, dict)],
    )
