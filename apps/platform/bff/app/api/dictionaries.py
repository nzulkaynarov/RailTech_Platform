"""Справочники как данные (контракт BFF: tag `dictionaries`; EDS-REG, исследование 2026-11-02
«Настройки» §4.3).

Один экран «Настройки · Процессы · Справочники» для справочников всех доменов. BFF держит
только каталог «вид → домен-владелец, область экрана, кто читает» (`OWNERS`) и проксирует ресурс
домена `/api/v1/dictionaries/{kind}` от имени сотрудника; код значения, «использовано», поля вида и
права решает домен (CONVENTIONS.md §2 п. 2). Новый справочник другого домена — строка в `OWNERS` и
тот же ресурс у домена. «Типы входящих писем» (`mail-types`, MAIL-TYPES) принадлежат CRM: у неё
письма и правила.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Final

import httpx
from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, ValidationError

from app.clients.base import Backend
from app.clients.eds import eds_error
from app.deps import Authed, AuthedDep, Rule, require, require_any
from app.errors import PlatformError, backend_reason, backend_unavailable, from_backend
from app.schemas_dictionaries import (
    CODE,
    KIND,
    Dictionary,
    DictionaryItem,
    DictionaryItemIn,
    DictionaryItemList,
    DictionaryItemPatch,
    DictionaryList,
    DictionaryOrderIn,
)

router = APIRouter(prefix="/dictionaries", tags=["dictionaries"])


@dataclass(frozen=True, slots=True)
class Owner:
    domain: Backend
    area: str
    readers: tuple[Rule, ...]


# Справочники документооборота читают те, кто работает с письмами, и администратор;
# меняет — `admin: full`.
_DOCUMENTS = Owner(
    "eds", "documents", (("eds.inbox", "read"), ("eds.inbox.register", "full"), ("admin", "read"))
)
# Типы писем читает первая линия (она ставит и меняет тип), правит администратор.
_MAIL = Owner("crm", "mail", (("crm.leads.triage", "read"), ("admin", "read")))
OWNERS: Final[dict[str, Owner]] = {
    "letter-kinds": _DOCUMENTS,
    "receipt-methods": _DOCUMENTS,
    "resolution-kinds": _DOCUMENTS,
    "mail-types": _MAIL,
}
# Причины CRM, которые экран знает под именами справочника документов.
_CRM_REASONS: Final = {"mail_type_name_taken": "name_taken", "mail_type_in_use": "value_in_use"}

Admin = Annotated[Authed, Depends(require("admin", "full"))]
CatalogReader = Annotated[Authed, Depends(require("admin", "read"))]
Kind = Annotated[str, Path(pattern=KIND)]
Code = Annotated[str, Path(pattern=CODE)]
# Проверка разделов по владельцу вида: зависимость строится один раз на набор правил.
_READERS = {kind: require_any(*owner.readers) for kind, owner in OWNERS.items()}


def _owner(kind: str) -> Owner:
    owner = OWNERS.get(kind)
    if owner is None:
        raise PlatformError("NOT_FOUND", "Такого справочника нет.", status_code=404)
    return owner


async def _call(
    authed: Authed, owner: Owner, method: str, path: str, ok: int = 200, **kw: Any
) -> httpx.Response:
    response = await authed.call(owner.domain, method, f"/api/v1/dictionaries{path}", **kw)
    if response.status_code != ok:
        raise _error(owner, response)
    return response


def _error(owner: Owner, response: httpx.Response) -> PlatformError:
    if owner.domain == "eds":
        return eds_error(response)
    err = from_backend(owner.domain, response)
    reason = backend_reason(response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = _CRM_REASONS.get(reason, reason)
    return err


def _parse[M: BaseModel](model: type[M], response: httpx.Response, owner: Owner) -> M:
    try:
        return model.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise backend_unavailable(owner.domain, "bad_dictionary") from exc


@router.get("", response_model=DictionaryList, operation_id="listDictionaries")
async def list_dictionaries(authed: CatalogReader) -> DictionaryList:
    """Каталог справочников доменов; BFF добавляет домен-владельца и область экрана."""
    items: list[Dictionary] = []
    for owner in (_DOCUMENTS, _MAIL):  # по одному запросу на домен-владельца
        raw = (await _call(authed, owner, "GET", "")).json()
        try:
            for entry in raw["items"]:
                found = OWNERS.get(entry.get("kind"))
                if found is not None and found.domain == owner.domain:
                    items.append(
                        Dictionary.model_validate(
                            {**entry, "owner": found.domain, "area": found.area}
                        )
                    )
        except (KeyError, TypeError, AttributeError, ValidationError) as exc:
            raise backend_unavailable(owner.domain, "bad_dictionary") from exc
    return DictionaryList(items=items)


@router.get("/{kind}", response_model=DictionaryItemList, operation_id="listDictionaryItems")
async def list_dictionary_items(
    authed: AuthedDep, kind: Kind, include_hidden: Annotated[bool, Query()] = False
) -> DictionaryItemList:
    owner = _owner(kind)
    await _READERS[kind](authed)
    params = {"include_hidden": "true"} if include_hidden else None
    response = await _call(authed, owner, "GET", f"/{kind}", params=params)
    return _parse(DictionaryItemList, response, owner)


@router.post(
    "/{kind}", response_model=DictionaryItem, status_code=201, operation_id="createDictionaryItem"
)
async def create_dictionary_item(
    authed: Admin, kind: Kind, body: DictionaryItemIn
) -> DictionaryItem:
    owner = _owner(kind)
    response = await _call(authed, owner, "POST", f"/{kind}", ok=201, json=body.model_dump())
    return _parse(DictionaryItem, response, owner)


@router.put(
    "/{kind}/order", response_model=DictionaryItemList, operation_id="reorderDictionaryItems"
)
async def reorder_dictionary_items(
    authed: Admin, kind: Kind, body: DictionaryOrderIn
) -> DictionaryItemList:
    owner = _owner(kind)
    response = await _call(authed, owner, "PUT", f"/{kind}/order", json=body.model_dump())
    return _parse(DictionaryItemList, response, owner)


@router.patch("/{kind}/{code}", response_model=DictionaryItem, operation_id="updateDictionaryItem")
async def update_dictionary_item(
    authed: Admin, kind: Kind, code: Code, body: DictionaryItemPatch
) -> DictionaryItem:
    owner = _owner(kind)
    payload = body.model_dump(exclude_unset=True)
    response = await _call(authed, owner, "PATCH", f"/{kind}/{code}", json=payload)
    return _parse(DictionaryItem, response, owner)


@router.delete(
    "/{kind}/{code}", status_code=204, response_class=Response, operation_id="deleteDictionaryItem"
)
async def delete_dictionary_item(authed: Admin, kind: Kind, code: Code) -> Response:
    owner = _owner(kind)
    await _call(authed, owner, "DELETE", f"/{kind}/{code}", ok=204)
    return Response(status_code=204)
