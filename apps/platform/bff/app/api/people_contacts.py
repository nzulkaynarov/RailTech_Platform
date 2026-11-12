"""Органайзер · Люди: контакты клиентов и партнёров (FR-11, пункт 0.11 плана 2026-11-12).

BFF читает ERP `parties/people/` с токеном сотрудника: контакты клиентов своей компании (туда же
ERP проецирует контакты клиентов CRM) и партнёров. Раздел `chats.internal` — чтение; ERP сам
ограничивает книгой своей компании.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
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
    email: str | None
    phone: str | None
    is_primary: bool
    company: CounterpartyRef
    kind: Kind


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
        email=_text(row.get("email")),
        phone=_text(row.get("phone")),
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
