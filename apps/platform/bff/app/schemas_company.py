"""Модели Admin · Компания — схемы `Company*`, `Brand*`, `Numbering*`, `QuoteDefaults*`, `Charge*`,
`DocumentTemplate*`, `EmailTemplate*`, `Reference*`, `Catalog*`, `CategoryRequest*`,
`PlatformSettings*` из packages/contracts/openapi/platform-bff.yaml (0.8.0) и перевод ответов ERP.

Поля с ограничением (правило 6 CONVENTIONS): маржа в условиях КП — группа `cost_margin`.
"""

import hashlib
from collections.abc import Collection, Mapping
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.clients.erp_company import media_path

DocumentKind = Literal["quote", "contract", "invoice", "act", "letter"]
ResetPeriod = Literal["never", "yearly", "monthly"]
ReferenceKind = Literal["countries", "currencies", "units", "delivery-basis"]
RequestStatus = Literal["pending", "approved", "rejected"]

# Вид документа контракта <-> код ERP.
KIND_TO_ERP: dict[str, str] = {
    "quote": "KP",
    "contract": "CT",
    "invoice": "INV",
    "act": "ACT",
    "letter": "DOC",
}
KIND_FROM_ERP: dict[str, DocumentKind] = {
    "KP": "quote",
    "CT": "contract",
    "INV": "invoice",
    "ACT": "act",
    "DOC": "letter",
}
MARGIN_FIELDS = ("default_margin_percent", "min_margin_percent", "target_margin_percent")
COST_MARGIN_GROUP = "cost_margin"

_PREFIX = r"^[A-Za-z0-9_-]*$"
_ID = r"^[0-9]+$"


# --- общее ------------------------------------------------------------------------------------


class Body(BaseModel):
    """Тело запроса: лишних полей нет; `sent()` — только присланные поля (для запроса к ERP)."""

    model_config = ConfigDict(extra="forbid")

    def sent(self) -> dict[str, Any]:
        return self.model_dump(include=self.model_fields_set)


class Patch(Body):
    """Тело изменения: не присланное не меняется; хотя бы одно поле; `null` — где разрешён."""

    nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("укажите хотя бы одно поле")
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable:
                raise ValueError(f"{name} не может быть null")
        return self


def text(value: Any) -> str:
    return "" if value is None else str(value)


def dec(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def ident(value: Any) -> str:
    return str(value)


def opt_ident(value: Any) -> str | None:
    return None if value is None else str(value)


def flag(value: Any) -> bool:
    return bool(value)


def whole(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def maybe_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# --- реквизиты ----------------------------------------------------------------------------------


class CompanyProfile(BaseModel):
    name: str
    inn: str | None
    bank_account: str
    mfo: str
    legal_address: str
    phone: str
    contact_person: str
    website: str
    email: str
    country: int | None
    has_iso9001: bool
    logo_url: str | None


class CompanyProfileUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"inn", "country"})

    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = None
    bank_account: str | None = Field(default=None, max_length=50)
    mfo: str | None = Field(default=None, max_length=10)
    legal_address: str | None = None
    phone: str | None = Field(default=None, max_length=50)
    contact_person: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=254)
    country: int | None = None
    has_iso9001: bool | None = None


COMPANY_LOGO_IMAGE = "/api/v1/admin/company/logo/image"
BRAND_LOGO_IMAGE = "/api/v1/admin/company/brand/logo/image"


def logo_ref(url: Any, endpoint: str) -> str | None:
    """Логотип для `<img>`: адрес BFF (тот же origin), не ERP; `v` сбрасывает кэш при замене."""
    path = media_path(url)
    return None if path is None else f"{endpoint}?v={hashlib.sha1(path.encode()).hexdigest()[:10]}"  # noqa: S324


def to_company(raw: Mapping[str, Any]) -> CompanyProfile:
    return CompanyProfile(
        name=text(raw.get("name")),
        inn=None if raw.get("inn") in (None, "") else text(raw["inn"]),
        bank_account=text(raw.get("bank_account")),
        mfo=text(raw.get("mfo")),
        legal_address=text(raw.get("legal_address")),
        phone=text(raw.get("phone")),
        contact_person=text(raw.get("contact_person")),
        website=text(raw.get("website")),
        email=text(raw.get("email")),
        country=maybe_int(raw.get("country")),
        has_iso9001=flag(raw.get("has_iso9001")),
        logo_url=logo_ref(raw.get("logo"), COMPANY_LOGO_IMAGE),
    )


# --- бланк и бренд -----------------------------------------------------------------------------

BRAND_TEXT = (
    "legal_name",
    "inn",
    "legal_address",
    "bank_details",
    "signatory_name",
    "signatory_position",
    "footer_text",
    "accent_color",
    "secondary_color",
    "cover_letter_text",
    "contract_acceptance_text",
    "contract_liability_text",
    "contract_extra_terms_text",
    "act_closing_text",
)
BRAND_FLAGS = (
    "show_cover_letter",
    "show_bank_in_header",
    "use_company_defaults",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
)
_PRESETS = ("light", "boxed", "bold", "striped")
_FONTS = ("sans", "serif")


class BrandProfile(BaseModel):
    legal_name: str
    inn: str
    legal_address: str
    bank_details: str
    signatory_name: str
    signatory_position: str
    footer_text: str
    accent_color: str
    secondary_color: str
    cover_letter_text: str
    contract_acceptance_text: str
    contract_liability_text: str
    contract_extra_terms_text: str
    act_closing_text: str
    layout_preset: Literal["light", "boxed", "bold", "striped"]
    font_family: Literal["sans", "serif"]
    show_cover_letter: bool
    show_bank_in_header: bool
    use_company_defaults: bool
    show_logo: bool
    show_lead_time: bool
    show_fx_note: bool
    logo_url: str | None
    inherited: dict[str, str] | None


class BrandProfileUpdate(Patch):
    legal_name: str | None = None
    inn: str | None = None
    legal_address: str | None = None
    bank_details: str | None = None
    signatory_name: str | None = None
    signatory_position: str | None = None
    footer_text: str | None = None
    accent_color: str | None = None
    secondary_color: str | None = None
    cover_letter_text: str | None = None
    contract_acceptance_text: str | None = None
    contract_liability_text: str | None = None
    contract_extra_terms_text: str | None = None
    act_closing_text: str | None = None
    layout_preset: Literal["light", "boxed", "bold", "striped"] | None = None
    font_family: Literal["sans", "serif"] | None = None
    show_cover_letter: bool | None = None
    show_bank_in_header: bool | None = None
    use_company_defaults: bool | None = None
    show_logo: bool | None = None
    show_lead_time: bool | None = None
    show_fx_note: bool | None = None


class BrandPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DocumentKind
    draft: BrandProfileUpdate | None = None


class DocumentPreview(BaseModel):
    html: str
    warnings: list[str] | None = None


def to_brand(raw: Mapping[str, Any]) -> BrandProfile:
    inherited = raw.get("inherited_preview")
    preset = raw.get("layout_preset")
    font = raw.get("font_family")
    return BrandProfile(
        **{name: text(raw.get(name)) for name in BRAND_TEXT},
        **{name: flag(raw.get(name)) for name in BRAND_FLAGS},
        layout_preset=preset if preset in _PRESETS else "light",
        font_family=font if font in _FONTS else "sans",
        logo_url=logo_ref(raw.get("logo_url") or raw.get("logo"), BRAND_LOGO_IMAGE),
        inherited={k: text(v) for k, v in inherited.items()}
        if isinstance(inherited, dict)
        else None,
    )


# --- нумерация ---------------------------------------------------------------------------------


class NumberingScheme(BaseModel):
    pattern: str
    padding: int
    reset_period: ResetPeriod
    start_value: int
    type_labels: dict[str, str]
    prefix: str
    is_effective: bool


class NumberingUpdate(Patch):
    pattern: str | None = Field(default=None, min_length=1, max_length=100)
    padding: int | None = Field(default=None, ge=1, le=10)
    reset_period: ResetPeriod | None = None
    start_value: int | None = Field(default=None, ge=0)
    type_labels: dict[str, str] | None = None
    prefix: str | None = Field(default=None, max_length=16, pattern=_PREFIX)


class NumberingPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=100)
    padding: int = Field(ge=1, le=10)
    reset_period: ResetPeriod
    start_value: int = Field(ge=0)
    type_labels: dict[str, str] | None = None
    prefix: str | None = Field(default=None, max_length=16, pattern=_PREFIX)


class NumberingPreviewItem(BaseModel):
    kind: DocumentKind
    label: str
    number: str


class NumberingPreview(BaseModel):
    items: list[NumberingPreviewItem]


def labels_to_erp(labels: Mapping[str, str]) -> dict[str, str]:
    """Обозначения видов документов контракта -> коды ERP; неизвестный вид пропускается."""
    return {KIND_TO_ERP[k]: v for k, v in labels.items() if k in KIND_TO_ERP}


def to_numbering(raw: Mapping[str, Any]) -> NumberingScheme:
    labels = raw.get("type_labels")
    period = raw.get("reset_period")
    return NumberingScheme(
        pattern=text(raw.get("pattern")),
        padding=whole(raw.get("padding"), 5),
        reset_period=period if period in ("never", "yearly", "monthly") else "yearly",
        start_value=whole(raw.get("start_value")),
        type_labels={
            KIND_FROM_ERP[k]: text(v)
            for k, v in (labels.items() if isinstance(labels, dict) else [])
            if k in KIND_FROM_ERP
        },
        prefix=text(raw.get("prefix")),
        is_effective=flag(raw.get("is_effective")),
    )


def to_numbering_preview(raw: Mapping[str, Any]) -> NumberingPreview:
    items: list[NumberingPreviewItem] = []
    for row in raw.get("results") or []:
        if isinstance(row, dict) and row.get("type_code") in KIND_FROM_ERP:
            items.append(
                NumberingPreviewItem(
                    kind=KIND_FROM_ERP[row["type_code"]],
                    label=text(row.get("label")),
                    number=text(row.get("number")),
                )
            )
    return NumberingPreview(items=items)


# --- условия КП --------------------------------------------------------------------------------


class QuoteDefaults(BaseModel):
    default_cost_currency: str | None
    default_delivery_basis: str | None
    default_vat_rate: str | None
    default_margin_percent: str | None = None
    min_margin_percent: str | None = None
    target_margin_percent: str | None = None
    default_offer_validity_days: int | None
    payment_terms_days: int | None
    default_payment_terms: str
    default_warranty_months: int | None
    catalog_price_visibility: Literal["cabinet", "on_request"]
    catalog_publish_threshold: int
    fx_rate_max_age_days: int


class QuoteDefaultsUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset(
        {
            "default_cost_currency",
            "default_delivery_basis",
            "default_vat_rate",
            "default_margin_percent",
            "default_offer_validity_days",
            "payment_terms_days",
            "default_warranty_months",
        }
    )

    default_cost_currency: str | None = None
    default_delivery_basis: str | None = None
    default_vat_rate: str | None = Field(default=None, pattern=r"^-?[0-9]+(\.[0-9]+)?$")
    default_margin_percent: str | None = Field(default=None, pattern=r"^-?[0-9]+(\.[0-9]+)?$")
    min_margin_percent: str | None = Field(default=None, pattern=r"^-?[0-9]+(\.[0-9]+)?$")
    target_margin_percent: str | None = Field(default=None, pattern=r"^-?[0-9]+(\.[0-9]+)?$")
    default_offer_validity_days: int | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0)
    default_payment_terms: str | None = None
    default_warranty_months: int | None = Field(default=None, ge=0)
    catalog_price_visibility: Literal["cabinet", "on_request"] | None = None
    catalog_publish_threshold: int | None = Field(default=None, ge=1, le=100)
    fx_rate_max_age_days: int | None = Field(default=None, ge=1, le=90)


def to_quote_defaults(raw: Mapping[str, Any], visible_groups: Collection[str]) -> QuoteDefaults:
    """Условия КП; поля маржи — только при праве на группу `cost_margin` (иначе в ответе их нет)."""
    visibility = raw.get("catalog_price_visibility")
    values: dict[str, Any] = {
        "default_cost_currency": raw.get("default_cost_currency_code") or None,
        "default_delivery_basis": raw.get("default_delivery_basis_code") or None,
        "default_vat_rate": dec(raw.get("default_vat_rate")),
        "default_offer_validity_days": maybe_int(raw.get("default_offer_validity_days")),
        "payment_terms_days": maybe_int(raw.get("payment_terms_days")),
        "default_payment_terms": text(raw.get("default_payment_terms")),
        "default_warranty_months": maybe_int(raw.get("default_warranty_months")),
        "catalog_price_visibility": visibility if visibility == "cabinet" else "on_request",
        "catalog_publish_threshold": whole(raw.get("catalog_publish_threshold"), 70),
        "fx_rate_max_age_days": whole(raw.get("fx_rate_max_age_days"), 7),
    }
    if COST_MARGIN_GROUP in visible_groups:
        for name in MARGIN_FIELDS:
            values[name] = dec(raw.get(name))
    return QuoteDefaults(**values)


# --- статьи расхода ----------------------------------------------------------------------------


class ChargeType(BaseModel):
    id: str
    code: str
    name: str


class ChargeTypeList(BaseModel):
    items: list[ChargeType]


class ChargeTemplate(BaseModel):
    id: str
    delivery_basis: str
    delivery_basis_name: str
    charge_type: str
    charge_type_name: str
    default_amount: str
    default_rate_percent: str | None
    is_deduction: bool
    sort_order: int
    is_active: bool


class ChargeTemplateList(BaseModel):
    items: list[ChargeTemplate]


_DECIMAL = r"^-?[0-9]+(\.[0-9]+)?$"


class ChargeTemplateIn(Body):
    delivery_basis: str = Field(min_length=1)
    charge_type: str = Field(min_length=1)
    default_amount: str | None = Field(default=None, pattern=_DECIMAL)
    default_rate_percent: str | None = Field(default=None, pattern=_DECIMAL)
    is_deduction: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ChargeTemplateUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"default_rate_percent"})

    delivery_basis: str | None = Field(default=None, min_length=1)
    charge_type: str | None = Field(default=None, min_length=1)
    default_amount: str | None = Field(default=None, pattern=_DECIMAL)
    default_rate_percent: str | None = Field(default=None, pattern=_DECIMAL)
    is_deduction: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


def to_charge_type(raw: Mapping[str, Any]) -> ChargeType:
    return ChargeType(
        id=ident(raw.get("id")), code=text(raw.get("code")), name=text(raw.get("name"))
    )


def to_charge_template(raw: Mapping[str, Any]) -> ChargeTemplate:
    return ChargeTemplate(
        id=ident(raw.get("id")),
        delivery_basis=text(raw.get("delivery_basis")),
        delivery_basis_name=text(raw.get("delivery_basis_name")),
        charge_type=text(raw.get("charge_type")),
        charge_type_name=text(raw.get("charge_type_name")),
        default_amount=text(raw.get("default_amount")) or "0",
        default_rate_percent=dec(raw.get("default_rate_percent")),
        is_deduction=flag(raw.get("is_deduction")),
        sort_order=whole(raw.get("sort_order")),
        is_active=flag(raw.get("is_active", True)),
    )


# --- шаблоны документов ------------------------------------------------------------------------


class DocumentTemplate(BaseModel):
    id: str
    name: str
    kind_name: str
    body_html: str
    is_sample: bool
    is_owned: bool
    is_active: bool
    placeholders_used: list[str]
    updated_at: str


class DocumentTemplateList(BaseModel):
    items: list[DocumentTemplate]


class DocumentTemplateIn(Body):
    name: str = Field(min_length=1, max_length=255)
    body_html: str | None = None
    is_active: bool | None = None


class DocumentTemplateUpdate(Patch):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    body_html: str | None = None
    is_active: bool | None = None


class DocumentTemplateCopyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class DocumentTemplatePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_html: str


class DocumentPlaceholder(BaseModel):
    code: str
    label: str


class DocumentPlaceholderGroup(BaseModel):
    key: str
    label: str
    items: list[DocumentPlaceholder]


class DocumentPlaceholders(BaseModel):
    groups: list[DocumentPlaceholderGroup]


def to_document_template(raw: Mapping[str, Any]) -> DocumentTemplate:
    used = raw.get("placeholders_used")
    return DocumentTemplate(
        id=ident(raw.get("id")),
        name=text(raw.get("name")),
        kind_name=text(raw.get("kind_name")),
        body_html=text(raw.get("body_html")),
        is_sample=flag(raw.get("is_sample")),
        is_owned=flag(raw.get("is_owned")),
        is_active=flag(raw.get("is_active", True)),
        placeholders_used=[str(p) for p in used] if isinstance(used, list) else [],
        updated_at=text(raw.get("updated_at")),
    )


def to_placeholders(raw: Mapping[str, Any]) -> DocumentPlaceholders:
    groups: list[DocumentPlaceholderGroup] = []
    for group in raw.get("groups") or []:
        if not isinstance(group, dict):
            continue
        items = [
            DocumentPlaceholder(code=text(i.get("code")), label=text(i.get("label")))
            for i in group.get("items") or []
            if isinstance(i, dict)
        ]
        groups.append(
            DocumentPlaceholderGroup(
                key=text(group.get("key")), label=text(group.get("label")), items=items
            )
        )
    return DocumentPlaceholders(groups=groups)


# --- шаблоны писем -----------------------------------------------------------------------------


class EmailTemplate(BaseModel):
    id: str
    key: str
    language: str
    subject: str
    html_body: str
    text_body: str
    available_variables: str
    is_active: bool
    updated_at: str
    updated_by: str | None = None


class EmailTemplateList(BaseModel):
    items: list[EmailTemplate]


class EmailTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    language: str | None = None
    subject: str = Field(min_length=1)
    html_body: str | None = None
    text_body: str = Field(min_length=1)
    available_variables: str | None = None
    is_active: bool | None = None


class EmailTemplateUpdate(Patch):
    key: str | None = Field(default=None, min_length=1, max_length=100)
    language: str | None = None
    subject: str | None = Field(default=None, min_length=1)
    html_body: str | None = None
    text_body: str | None = Field(default=None, min_length=1)
    available_variables: str | None = None
    is_active: bool | None = None


class EmailTemplatePreview(BaseModel):
    subject: str
    text_body: str
    html_body: str


def to_email_template(raw: Mapping[str, Any]) -> EmailTemplate:
    values: dict[str, Any] = {
        "id": ident(raw.get("id")),
        "key": text(raw.get("key")),
        "language": text(raw.get("language")),
        "subject": text(raw.get("subject")),
        "html_body": text(raw.get("html_body")),
        "text_body": text(raw.get("text_body")),
        "available_variables": text(raw.get("available_variables")),
        "is_active": flag(raw.get("is_active", True)),
        "updated_at": text(raw.get("updated_at")),
    }
    if raw.get("updated_by_email"):
        values["updated_by"] = text(raw["updated_by_email"])
    return EmailTemplate(**values)


# --- справочники -------------------------------------------------------------------------------

REFERENCE_PATH: dict[str, str] = {
    "countries": "master-data/countries/",
    "currencies": "master-data/currencies/",
    "units": "master-data/units/",
    "delivery-basis": "master-data/delivery-basis/",
}
_CORE = ("code", "name", "sort_order", "is_active")
REFERENCE_EXTRAS: dict[str, tuple[str, ...]] = {
    "countries": ("alpha2", "alpha3", "iso_numeric", "vat_rate"),
    "currencies": ("symbol",),
    "units": (),
    "delivery-basis": (
        "description",
        "seller_pays_freight",
        "seller_pays_insurance",
        "seller_pays_import",
        "seller_pays_delivery",
    ),
}


class ReferenceItem(BaseModel):
    id: str
    code: str
    name: str
    sort_order: int
    is_active: bool
    symbol: str | None = None
    alpha2: str | None = None
    alpha3: str | None = None
    iso_numeric: str | None = None
    vat_rate: str | None = None
    description: str | None = None
    seller_pays_freight: bool | None = None
    seller_pays_insurance: bool | None = None
    seller_pays_import: bool | None = None
    seller_pays_delivery: bool | None = None


class ReferenceItemList(BaseModel):
    items: list[ReferenceItem]


class ReferenceItemIn(Body):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    sort_order: int | None = None
    is_active: bool | None = None
    symbol: str | None = None
    alpha2: str | None = None
    alpha3: str | None = None
    iso_numeric: str | None = None
    vat_rate: str | None = Field(default=None, pattern=_DECIMAL)
    description: str | None = None
    seller_pays_freight: bool | None = None
    seller_pays_insurance: bool | None = None
    seller_pays_import: bool | None = None
    seller_pays_delivery: bool | None = None


class ReferenceItemUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"vat_rate"})

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None
    is_active: bool | None = None
    symbol: str | None = None
    alpha2: str | None = None
    alpha3: str | None = None
    iso_numeric: str | None = None
    vat_rate: str | None = Field(default=None, pattern=_DECIMAL)
    description: str | None = None
    seller_pays_freight: bool | None = None
    seller_pays_insurance: bool | None = None
    seller_pays_import: bool | None = None
    seller_pays_delivery: bool | None = None


def foreign_reference_fields(kind: str, sent: Mapping[str, Any]) -> list[str]:
    """Поля, которых у этого справочника нет (например, `symbol` у стран)."""
    allowed = {*_CORE, *REFERENCE_EXTRAS[kind]}
    return sorted(name for name in sent if name not in allowed)


def to_reference_item(kind: str, raw: Mapping[str, Any]) -> ReferenceItem:
    values: dict[str, Any] = {
        "id": ident(raw.get("id")),
        "code": text(raw.get("code")),
        "name": text(raw.get("name")),
        "sort_order": whole(raw.get("sort_order")),
        "is_active": flag(raw.get("is_active", True)),
    }
    for name in REFERENCE_EXTRAS[kind]:
        if name in raw:
            value = raw[name]
            values[name] = (
                dec(value)
                if name == "vat_rate"
                else (flag(value) if name.startswith("seller_pays_") else text(value))
            )
    return ReferenceItem(**values)


# --- категории ---------------------------------------------------------------------------------


class CatalogCategory(BaseModel):
    id: str
    name: str
    parent_id: str | None


class CatalogCategoryList(BaseModel):
    items: list[CatalogCategory]


class CatalogCategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = Field(default=None, pattern=_ID)


class CatalogCategoryUpdate(Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"parent_id"})

    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: str | None = Field(default=None, pattern=_ID)


class CategoryRequest(BaseModel):
    id: str
    proposed_name: str
    parent_name: str | None = None
    justification: str | None = None
    status: RequestStatus
    company_name: str
    requested_by: str | None = None
    resulting_category_id: str | None = None
    resulting_category_name: str | None = None
    review_notes: str | None = None
    reviewed_at: str | None = None
    created_at: str


class CategoryRequestList(BaseModel):
    items: list[CategoryRequest]


class CategoryRequestApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str = Field(pattern=_ID)


class CategoryRequestRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


def to_category(raw: Mapping[str, Any]) -> CatalogCategory:
    return CatalogCategory(
        id=ident(raw.get("id")), name=text(raw.get("name")), parent_id=opt_ident(raw.get("parent"))
    )


def to_category_request(raw: Mapping[str, Any]) -> CategoryRequest:
    status = text(raw.get("status")).lower()
    values: dict[str, Any] = {
        "id": ident(raw.get("id")),
        "proposed_name": text(raw.get("proposed_name")),
        "status": status if status in ("pending", "approved", "rejected") else "pending",
        "company_name": text(raw.get("company_name")),
        "created_at": text(raw.get("created_at")),
    }
    optional = {
        "parent_name": raw.get("parent_name"),
        "justification": raw.get("justification"),
        "requested_by": raw.get("requested_by_email"),
        "resulting_category_id": opt_ident(raw.get("resulting_category")),
        "resulting_category_name": raw.get("resulting_category_name"),
        "review_notes": raw.get("review_notes"),
        "reviewed_at": raw.get("reviewed_at"),
    }
    values.update({k: v for k, v in optional.items() if v not in (None, "")})
    return CategoryRequest(**values)


# --- платформенные настройки -------------------------------------------------------------------


class PlatformSettings(BaseModel):
    vat_rate: str
    exchange_rate_usd_uzs: str | None
    updated_at: str


class PlatformSettingsUpdate(Patch):
    vat_rate: str | None = Field(default=None, pattern=_DECIMAL)


def to_platform_settings(raw: Mapping[str, Any]) -> PlatformSettings:
    return PlatformSettings(
        vat_rate=text(raw.get("vat_rate")) or "0",
        exchange_rate_usd_uzs=dec(raw.get("exchange_rate_usd_uzs")),
        updated_at=text(raw.get("updated_at")),
    )
