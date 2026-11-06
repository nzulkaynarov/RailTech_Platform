"""Модели блока «Доступ в кабинет» карточки поставщика — схемы `SupplierCabinet*` из platform-
bff.yaml (PART-1, ADR-0022).

ERP `catalog/supplier-access/{id}/`: отношение «партнёр» поставщика (статус, вид, включённые
модули), контакты компании, приглашение с кодом входа и приостановка. Права решает ERP
(`supply.manage`); BFF проверяет раздел `erp.stock` и переводит идентификаторы в строки.
"""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_company import Body, Patch, ident, opt_ident, text

CabinetRole = Literal["client", "partner"]
RelationshipStatus = Literal["invited", "active", "suspended"]
PartnerKind = Literal["", "manufacturer", "supplier", "principal", "other"]
PartnerModule = Literal["my_products", "catalog_requests"]
# PART-3: цены товаров партнёра в каталоге — пусто «как у компании», показывать, по запросу
PartnerPriceVisibility = Literal["", "cabinet", "on_request"]
Language = Literal["ru", "uz", "en"]
CrmClientStatus = Literal[
    "none", "requested", "pending_confirmation", "held", "unverified", "linked", "conflict"
]


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CabinetPerson(Out):
    id: str
    name: str


class SupplierCabinetContact(Out):
    id: str
    name: str
    email: str
    phone: str
    language: Language
    can_act: bool
    invited_at: str | None
    last_login_at: str | None


class SupplierCabinetRelationship(Out):
    role: Literal["partner"]
    kind: PartnerKind
    modules: list[PartnerModule]
    catalog_price_visibility: PartnerPriceVisibility
    status: RelationshipStatus
    contract_number: str = ""
    contract_date: str | None = None
    invited_at: str | None
    activated_at: str | None
    suspended_at: str | None
    responsible: CabinetPerson | None
    invited_by: CabinetPerson | None


class SupplierCabinetModules(Out):
    allowed: list[PartnerModule]
    default: list[PartnerModule]


class SupplierCabinetCrmClient(Out):
    status: CrmClientStatus
    crm_client_id: str | None
    crm_client_name: str | None = None
    inn: str | None = None


class SupplierCabinetAccess(Out):
    company_id: str
    company_name: str
    crm_client: SupplierCabinetCrmClient
    relationship: SupplierCabinetRelationship | None
    contacts: list[SupplierCabinetContact]
    partner_modules: SupplierCabinetModules
    cabinet_roles: list[CabinetRole]
    cabinet_modules: list[str]
    can_manage: bool


class SupplierCabinetContactCreate(Body):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    language: Language | None = None
    can_act: bool | None = None


class SupplierCabinetContactUpdate(Patch):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    language: Language | None = None
    can_act: bool | None = None


class SupplierCabinetRightsUpdate(Patch):
    modules: list[PartnerModule] | None = None
    kind: PartnerKind | None = None
    contract_number: str | None = None
    contract_date: str | None = None
    catalog_price_visibility: PartnerPriceVisibility | None = None


class SupplierCabinetInvite(Body):
    contact_id: str = Field(pattern=r"^[0-9]+$")
    modules: list[PartnerModule] | None = None
    kind: PartnerKind | None = None
    contract_number: str | None = None
    contract_date: str | None = None


def _person(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    return {"id": ident(raw.get("id")), "name": text(raw.get("name"))}


def to_contact(raw: Mapping[str, Any]) -> SupplierCabinetContact:
    return SupplierCabinetContact(
        **{
            "id": ident(raw.get("id")),
            "name": text(raw.get("name")),
            "email": text(raw.get("email")),
            "phone": text(raw.get("phone")),
            "language": raw.get("language") if raw.get("language") in ("ru", "uz", "en") else "ru",
            "can_act": bool(raw.get("can_act")),
            "invited_at": raw.get("invited_at"),
            "last_login_at": raw.get("last_login_at"),
        }
    )


def _crm_client(raw: Any) -> dict[str, Any]:
    """Клиент партнёра в CRM (PART-CRM); ответ ERP без поля — «не просили»."""
    if not isinstance(raw, Mapping) or raw.get("status") not in (
        "requested",
        "pending_confirmation",
        "held",
        "unverified",
        "linked",
        "conflict",
    ):
        return {"status": "none", "crm_client_id": None}
    out: dict[str, Any] = {
        "status": raw["status"],
        "crm_client_id": opt_ident(raw.get("crm_client_id")),
    }
    if raw["status"] == "unverified":
        out["crm_client_name"] = raw.get("crm_client_name") or None
        out["inn"] = raw.get("inn") or None
    return out


def to_access(raw: Mapping[str, Any]) -> SupplierCabinetAccess:
    relationship = raw.get("relationship")
    modules = raw.get("partner_modules") or {}
    return SupplierCabinetAccess(
        **{
            "company_id": ident(raw.get("company_id")),
            "company_name": text(raw.get("company_name")),
            "relationship": None
            if not isinstance(relationship, Mapping)
            else {
                "role": "partner",
                "kind": text(relationship.get("kind")),
                "modules": list(relationship.get("modules") or []),
                "catalog_price_visibility": text(relationship.get("catalog_price_visibility")),
                "status": relationship.get("status"),
                "contract_number": text(relationship.get("contract_number")),
                "contract_date": relationship.get("contract_date") or None,
                "invited_at": relationship.get("invited_at"),
                "activated_at": relationship.get("activated_at"),
                "suspended_at": relationship.get("suspended_at"),
                "responsible": _person(relationship.get("responsible")),
                "invited_by": _person(relationship.get("invited_by")),
            },
            "contacts": [to_contact(c) for c in raw.get("contacts") or []],
            "partner_modules": {
                "allowed": list(modules.get("allowed") or []),
                "default": list(modules.get("default") or []),
            },
            "cabinet_roles": list(raw.get("cabinet_roles") or []),
            "cabinet_modules": list(raw.get("cabinet_modules") or []),
            "crm_client": _crm_client(raw.get("crm_client")),
            "can_manage": bool(raw.get("can_manage")),
        }
    )


def invite_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    out = dict(sent)
    out["contact_id"] = int(out["contact_id"])
    return out
