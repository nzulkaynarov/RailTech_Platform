"""Органайзер · Люди: контакты клиентов и партнёров (FR-11, пункт 0.11 плана 2026-11-12).

BFF читает ERP `parties/people/` с токеном сотрудника: контакты клиентов своей компании (туда же
ERP проецирует контакты клиентов CRM) и партнёров. Раздел `chats.internal` — чтение; ERP сам
ограничивает книгой своей компании. Телефон и почта в список не входят (NAVIGATION «Люди»): их
открывает `reveal` — сначала запись `contact.reveal` в журнал CRM, потом ERP по одному человеку;
журнал не принял запись — контактов нет.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require, require_any
from app.errors import PlatformError
from app.schemas_erp_catalog import page_meta, rows_of

router = APIRouter(tags=["chats"])

Reader = Annotated[Authed, Depends(require("chats.internal", "read"))]
Kind = Literal["client", "partner"]


class CounterpartyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str


class CounterpartyPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    position: str | None
    has_email: bool
    has_phone: bool
    is_primary: bool
    company: CounterpartyRef
    kind: Kind


class CounterpartyContacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    phone: str | None
    email: str | None


class CounterpartyPersonPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CounterpartyPerson]
    total: int
    page: int
    page_size: int


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def to_person(row: dict[str, Any]) -> CounterpartyPerson:
    raw = row.get("company")
    company: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return CounterpartyPerson(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        position=_text(row.get("position")),
        has_email=bool(row.get("has_email")),
        has_phone=bool(row.get("has_phone")),
        is_primary=bool(row.get("is_primary")),
        company=CounterpartyRef(id=str(company.get("id", "")), name=str(company.get("name") or "")),
        kind="client" if row.get("kind") == "client" else "partner",
    )


@router.get(
    "/people/contacts",
    response_model=CounterpartyPersonPage,
    operation_id="listCounterpartyPeople",
)
async def list_people(
    authed: Reader,
    kind: Kind | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> CounterpartyPersonPage:
    wanted = {"kind": kind, "q": q, "page": page, "page_size": page_size}
    params = {k: v for k, v in wanted.items() if v not in (None, "")}
    data = await ErpCompany(authed.call).data("GET", "parties/people/", params=params)
    items = [to_person(row) for row in rows_of(data) if "id" in row]
    return CounterpartyPersonPage(items=items, **page_meta(data, page, page_size))


ContactId = Annotated[str, Path(pattern=r"^[0-9]+$")]


@router.post(
    "/people/contacts/{id}/reveal",
    response_model=CounterpartyContacts,
    operation_id="revealCounterpartyContacts",
)
async def reveal_contacts(id: ContactId, authed: Reader) -> CounterpartyContacts:
    erp = ErpCompany(authed.call)
    raw = await erp.data("GET", f"parties/people/{id}/")
    row: dict[str, Any] = raw if isinstance(raw, dict) else {}
    name = str(row.get("name") or id)
    # Сначала журнал: показ без записи «кто, когда, чьи» не допускается.
    try:
        response = await authed.call(
            "crm", "POST", "/api/v1/audit/contact-reveal", json={"contact": id, "name": name}
        )
        recorded = response.status_code == status.HTTP_204_NO_CONTENT
    except PlatformError:
        recorded = False
    if not recorded:
        raise PlatformError(
            "BACKEND_UNAVAILABLE",
            "Журнал недоступен — контакты не показаны, повторите чуть позже.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return CounterpartyContacts(
        id=str(row.get("id", id)), phone=_text(row.get("phone")), email=_text(row.get("email"))
    )


# --- Карточка контрагента: одна компания во всех ролях (ADR-0028, СУЩ-2.5) -----------------------

# Карточку открывают из «Контактов»: клиентов видит `crm.clients`, партнёров каталога — `erp.stock`
CardReader = Annotated[Authed, Depends(require_any(("crm.clients", "read"), ("erp.stock", "read")))]
# Роли «поставщик» и «изготовитель» отмечает тот, кто ведёт поставщиков (ERP `supply.manage`)
CardWriter = Annotated[Authed, Depends(require("erp.stock", "full"))]
CompanyId = Annotated[str, Path(pattern=r"^[0-9]+$")]
RoleCode = Literal["supplier", "manufacturer"]


class CounterpartyRoles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client: bool
    supplier: bool
    manufacturer: bool
    partner: bool
    organization: bool


class CounterpartyCardPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    position: str | None
    is_primary: bool
    has_cabinet: bool
    has_phone: bool
    has_email: bool


class CounterpartyAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    currency: str | None
    bank_name: str
    bank_country: str | None
    account: str
    mfo: str
    swift: str
    is_default: bool


class CounterpartyCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    inn: str | None
    registration_number: str | None
    country: str | None
    legal_address: str | None
    crm_client_id: int | None
    roles: CounterpartyRoles
    people: list[CounterpartyCardPerson]
    bank_accounts: list[CounterpartyAccount]
    accounts_masked: bool
    brands: list[CounterpartyRef]


class CounterpartyRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleCode
    on: bool


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def to_card(raw: Any) -> CounterpartyCard:
    row: dict[str, Any] = raw if isinstance(raw, dict) else {}
    roles: dict[str, Any] = row["roles"] if isinstance(row.get("roles"), dict) else {}
    client = row.get("crm_client_id")
    return CounterpartyCard(
        id=str(row.get("id", "")),
        name=str(row.get("name") or ""),
        inn=_text(row.get("inn")),
        registration_number=_text(row.get("registration_number")),
        country=_text(row.get("country")),
        legal_address=_text(row.get("legal_address")),
        crm_client_id=client if isinstance(client, int) else None,
        roles=CounterpartyRoles(
            client=bool(roles.get("client")),
            supplier=bool(roles.get("supplier")),
            manufacturer=bool(roles.get("manufacturer")),
            partner=bool(roles.get("partner")),
            organization=bool(roles.get("organization")),
        ),
        people=[
            CounterpartyCardPerson(
                id=str(person.get("id", "")),
                name=str(person.get("name") or ""),
                position=_text(person.get("position")),
                is_primary=bool(person.get("is_primary")),
                has_cabinet=bool(person.get("has_cabinet")),
                has_phone=bool(person.get("has_phone")),
                has_email=bool(person.get("has_email")),
            )
            for person in _rows(row.get("people"))
        ],
        bank_accounts=[
            CounterpartyAccount(
                id=str(account.get("id", "")),
                currency=_text(account.get("currency")),
                bank_name=str(account.get("bank_name") or ""),
                bank_country=_text(account.get("bank_country")),
                account=str(account.get("account") or ""),
                mfo=str(account.get("mfo") or ""),
                swift=str(account.get("swift") or ""),
                is_default=bool(account.get("is_default")),
            )
            for account in _rows(row.get("bank_accounts"))
        ],
        accounts_masked=bool(row.get("accounts_masked")),
        brands=[
            CounterpartyRef(id=str(brand.get("id", "")), name=str(brand.get("name") or ""))
            for brand in _rows(row.get("brands"))
        ],
    )


@router.get(
    "/people/counterparties/{id}",
    response_model=CounterpartyCard,
    operation_id="getCounterparty",
)
async def get_counterparty(id: CompanyId, authed: CardReader) -> CounterpartyCard:
    return to_card(await ErpCompany(authed.call).data("GET", f"parties/organizations/{id}/"))


@router.get(
    "/people/clients/{id}/counterparty",
    response_model=CounterpartyCard,
    operation_id="getCounterpartyByClient",
)
async def get_counterparty_by_client(id: CompanyId, authed: CardReader) -> CounterpartyCard:
    """Компания ERP клиента CRM; клиент ещё не передан в ERP — 404."""
    data = await ErpCompany(authed.call).data("GET", f"parties/crm-clients/{id}/organization/")
    return to_card(data)


@router.post(
    "/people/counterparties/{id}/roles",
    response_model=CounterpartyCard,
    operation_id="setCounterpartyRole",
)
async def set_counterparty_role(
    id: CompanyId, body: CounterpartyRoleIn, authed: CardWriter
) -> CounterpartyCard:
    data = await ErpCompany(authed.call).data(
        "POST", f"parties/organizations/{id}/roles/", json={"role": body.role, "on": body.on}
    )
    return to_card(data)


class CounterpartyRequisitesIn(BaseModel):
    """Реквизиты контрагента (СУЩ-2.7): только переданные поля; их ведёт ERP, CRM — снимок."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    inn: str | None = Field(default=None, pattern=r"^\d{9}$")
    registration_number: str | None = Field(default=None, max_length=64)
    legal_address: str | None = Field(default=None, max_length=1000)


RequisitesWriter = Annotated[
    Authed, Depends(require_any(("crm.clients", "full"), ("erp.stock", "full")))
]


@router.patch(
    "/people/counterparties/{id}",
    response_model=CounterpartyCard,
    operation_id="updateCounterpartyRequisites",
)
async def update_counterparty_requisites(
    id: CompanyId, body: CounterpartyRequisitesIn, authed: RequisitesWriter
) -> CounterpartyCard:
    sent = body.model_dump(exclude_unset=True)
    if "inn" in sent:
        sent["tin"] = sent.pop("inn")
    data = await ErpCompany(authed.call).data("PATCH", f"parties/organizations/{id}/", json=sent)
    return to_card(data)


# --- «Ш»: адресат письма из контрагентов ---------------------------------------------------------

Writer = Annotated[Authed, Depends(require("eds.memo.create", "full"))]


class EdsAddressee(BaseModel):
    """Организация-контрагент для поля «Организация» письма: реквизиты, не личные контакты."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    inn: str | None
    email: str | None
    attention: str | None
    kind: Kind


class EdsAddresseeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, pattern=r"^\d{9}$")
    legal_address: str | None = Field(default=None, max_length=500)


class EdsAddresseeList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EdsAddressee]


def to_addressee(row: dict[str, Any]) -> EdsAddressee:
    return EdsAddressee(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        inn=_text(row.get("inn")),
        email=_text(row.get("email")),
        attention=_text(row.get("contact_person")),
        kind="client" if row.get("kind") == "client" else "partner",
    )


@router.get(
    "/eds/addressees",
    response_model=EdsAddresseeList,
    operation_id="searchEdsAddressees",
    tags=["eds-documents"],
)
async def search_addressees(
    authed: Writer,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> EdsAddresseeList:
    """Клиенты и партнёры из ERP по названию или ИНН — первые 10; ручной ввод адресата остаётся."""
    data = await ErpCompany(authed.call).data(
        "GET", "parties/organizations/", params={"q": q, "page_size": 10}
    )
    return EdsAddresseeList(
        items=[to_addressee(row) for row in rows_of(data) if "id" in row and row.get("name")]
    )


@router.post(
    "/eds/addressees",
    response_model=EdsAddressee,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEdsAddressee",
    tags=["eds-documents"],
)
async def create_addressee(authed: Writer, body: EdsAddresseeIn) -> EdsAddressee:
    """Адресата нет в контрагентах — организация заводится из письма (ADR-0028 п. 5)."""
    card = await ErpCompany(authed.call).data(
        "POST",
        "parties/organizations/",
        json={
            "name": body.name,
            "tin": body.inn,
            "legal_address": body.legal_address or "",
        },
    )
    return to_addressee({**card, "kind": "client" if card["roles"]["client"] else "partner"})


class EdsAddresseePerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    position: str | None


class EdsAddresseePeople(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EdsAddresseePerson]


@router.get(
    "/eds/addressees/{id}/people",
    response_model=EdsAddresseePeople,
    operation_id="listEdsAddresseePeople",
    tags=["eds-documents"],
)
async def addressee_people(id: CompanyId, authed: Writer) -> EdsAddresseePeople:
    """«Кому — человек» письма (СУЩ-2.6): люди компании из карточки ERP, без телефонов и почты."""
    card = await ErpCompany(authed.call).data("GET", f"parties/organizations/{id}/")
    return EdsAddresseePeople(
        items=[
            EdsAddresseePerson(
                id=str(person["id"]),
                name=str(person.get("name") or ""),
                position=_text(person.get("position")),
            )
            for person in card.get("people") or []
            if "id" in person
        ]
    )


# --- Контрагенты для выбора: одно поле компании и человека во всех формах (ЕД-6) ------------------

# Поле выбора стоит в формах разных разделов: заявка (`erp.calc`), заказ поставщику и бренд
# (`erp.stock`),
# клиенты (`crm.clients`), письмо (`eds.memo.create`). Достаточно любого; решающее слово за ERP.
PickerReader = Annotated[
    Authed,
    Depends(
        require_any(
            ("crm.clients", "read"),
            ("erp.stock", "read"),
            ("erp.calc", "read"),
            ("eds.memo.create", "read"),
        )
    ),
]
PickerWriter = Annotated[
    Authed,
    Depends(
        require_any(
            ("crm.clients", "full"),
            ("erp.stock", "full"),
            ("erp.calc", "full"),
            ("eds.memo.create", "full"),
        )
    ),
]
PickerRole = Literal["client", "supplier", "manufacturer", "partner", "organization"]
NewRole = Literal["organization", "supplier", "manufacturer"]


class CounterpartyPick(BaseModel):
    """Строка поля выбора контрагента: название, ИНН, страна и роли для подсказки."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    inn: str | None
    country: str | None
    roles: CounterpartyRoles
    crm_client_id: int | None
    email: str | None


class CounterpartyPickList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CounterpartyPick]


class CounterpartyPickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, pattern=r"^\d{9}$")
    country_id: int | None = Field(default=None, ge=1)
    address: str | None = Field(default=None, max_length=500)
    role: NewRole = "organization"


class CounterpartyPersonPick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    position: str | None
    email: str | None
    is_primary: bool


class CounterpartyPersonPickList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CounterpartyPersonPick]


def _roles(raw: Any) -> CounterpartyRoles:
    roles: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return CounterpartyRoles(
        client=bool(roles.get("client")),
        supplier=bool(roles.get("supplier")),
        manufacturer=bool(roles.get("manufacturer")),
        partner=bool(roles.get("partner")),
        organization=bool(roles.get("organization")),
    )


def to_pick(row: dict[str, Any]) -> CounterpartyPick:
    client = row.get("crm_client_id")
    return CounterpartyPick(
        id=str(row["id"]),
        name=str(row.get("name") or ""),
        inn=_text(row.get("inn")),
        country=_text(row.get("country")),
        roles=_roles(row.get("roles")),
        crm_client_id=client if isinstance(client, int) else None,
        email=_text(row.get("email")),
    )


@router.get(
    "/people/counterparties",
    response_model=CounterpartyPickList,
    operation_id="searchCounterparties",
)
async def search_counterparties(
    authed: PickerReader,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: PickerRole | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> CounterpartyPickList:
    """Название или точный ИНН; `role` поднимает компании с ролью, остальных не скрывает."""
    wanted = {"q": (q or "").strip(), "role": role, "limit": limit}
    params = {k: v for k, v in wanted.items() if v not in (None, "")}
    data = await ErpCompany(authed.call).data("GET", "parties/organizations/", params=params)
    return CounterpartyPickList(
        items=[to_pick(row) for row in rows_of(data) if "id" in row and row.get("name")]
    )


@router.post(
    "/people/counterparties",
    response_model=CounterpartyPick,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCounterparty",
)
async def create_counterparty(authed: PickerWriter, body: CounterpartyPickIn) -> CounterpartyPick:
    """Строка «завести» поля выбора. Дубль по ИНН — 409 с `details.existing_id`."""
    sent: dict[str, Any] = {"name": body.name, "role": body.role}
    if body.inn:
        sent["tin"] = body.inn
    if body.country_id is not None:
        sent["country_id"] = body.country_id
    if body.address:
        sent["legal_address"] = body.address
    erp = ErpCompany(authed.call)
    try:
        card = await erp.data("POST", "parties/organizations/", json=sent)
    except PlatformError as exc:
        await _attach_existing(erp, exc)
        raise
    return to_pick(card)


async def _attach_existing(erp: ErpCompany, exc: PlatformError) -> None:
    """Дубль по ИНН: строка выбора уже существующей компании — в `details.existing`.

    Компания без роли поиск не показывает, поэтому форма берёт её из этого ответа. Карточка не
    прочиталась — остаётся только `existing_id`, как раньше.
    """
    details = exc.body.details or {}
    existing = details.get("existing_id")
    if exc.status_code != 409 or details.get("reason") != "company_exists" or not existing:
        return
    try:
        card = await erp.data("GET", f"parties/organizations/{existing}/")
    except PlatformError:
        return
    if isinstance(card, dict) and card.get("name"):
        details["existing"] = to_pick({**card, "id": existing}).model_dump()


@router.get(
    "/people/counterparties/{id}/people",
    response_model=CounterpartyPersonPickList,
    operation_id="listCounterpartyPickerPeople",
)
async def counterparty_picker_people(
    id: CompanyId, authed: PickerReader
) -> CounterpartyPersonPickList:
    """Поле выбора человека компании: имя, должность и почта; телефон — только через «Люди»."""
    data = await ErpCompany(authed.call).data("GET", f"parties/organizations/{id}/people/")
    return CounterpartyPersonPickList(
        items=[
            CounterpartyPersonPick(
                id=str(row["id"]),
                name=str(row.get("name") or ""),
                position=_text(row.get("position")),
                email=_text(row.get("email")),
                is_primary=bool(row.get("is_primary")),
            )
            for row in rows_of(data)
            if "id" in row
        ]
    )
