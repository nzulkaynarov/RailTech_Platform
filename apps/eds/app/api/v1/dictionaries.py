"""Справочники документооборота (`/api/v1/dictionaries…`, eds.yaml, тег `dictionaries`; EDS-REG); правила —
`services/dictionaries.py`.

Читают — те, кто работает с письмами, и администратор; меняет — администратор: `bus.manage` — код раздела `admin`
каталога Платформы в EDS (нового права нет).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_permission
from app.models import Employee
from app.schemas.dictionaries import (
    DICTIONARY_CODE,
    DICTIONARY_KIND,
    DictionaryItem,
    DictionaryItemIn,
    DictionaryItemList,
    DictionaryItemPatch,
    DictionaryList,
    DictionaryOrderIn,
)
from app.security.permissions import EdsPermission as P
from app.services import dictionaries

router = APIRouter(prefix="/api/v1/dictionaries", tags=["dictionaries"])

Reader = Annotated[Employee, Depends(require_permission(P.LETTERS_READ, P.LETTERS_REGISTER, P.BUS_MANAGE))]
Admin = Annotated[Employee, Depends(require_permission(P.BUS_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]
Kind = Annotated[str, Path(pattern=DICTIONARY_KIND)]
Code = Annotated[str, Path(pattern=DICTIONARY_CODE)]


@router.get("", response_model=DictionaryList, operation_id="listDictionaries")
async def list_dictionaries(_: Reader) -> DictionaryList:
    return dictionaries.catalog()


@router.get("/{kind}", response_model=DictionaryItemList, operation_id="listDictionaryItems")
async def list_dictionary_items(
    _: Reader, session: Session, kind: Kind, include_hidden: Annotated[bool, Query()] = False
) -> DictionaryItemList:
    return await dictionaries.list_items(session, kind, include_hidden=include_hidden)


@router.post(
    "/{kind}",
    response_model=DictionaryItem,
    status_code=status.HTTP_201_CREATED,
    operation_id="createDictionaryItem",
)
async def create_dictionary_item(admin: Admin, session: Session, kind: Kind, body: DictionaryItemIn) -> DictionaryItem:
    async with session.begin():
        return await dictionaries.create(session, kind, body, actor_id=admin.crm_user_id)


@router.put("/{kind}/order", response_model=DictionaryItemList, operation_id="reorderDictionaryItems")
async def reorder_dictionary_items(
    admin: Admin, session: Session, kind: Kind, body: DictionaryOrderIn
) -> DictionaryItemList:
    async with session.begin():
        return await dictionaries.reorder(session, kind, body.codes, actor_id=admin.crm_user_id)


@router.patch("/{kind}/{code}", response_model=DictionaryItem, operation_id="updateDictionaryItem")
async def update_dictionary_item(
    admin: Admin, session: Session, kind: Kind, code: Code, body: DictionaryItemPatch
) -> DictionaryItem:
    async with session.begin():
        return await dictionaries.update(session, kind, code, body, actor_id=admin.crm_user_id)


@router.delete(
    "/{kind}/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="deleteDictionaryItem",
)
async def delete_dictionary_item(admin: Admin, session: Session, kind: Kind, code: Code) -> Response:
    async with session.begin():
        await dictionaries.delete(session, kind, code, actor_id=admin.crm_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
