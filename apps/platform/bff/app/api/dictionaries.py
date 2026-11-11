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
from typing import Annotated, Any, Final, Literal

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ValidationError

from app import dictionary_files as files
from app.clients.base import Backend
from app.clients.eds import eds_error
from app.deps import Authed, AuthedDep, Rule, require, require_any, require_any_section
from app.errors import PlatformError, backend_reason, backend_unavailable, from_backend
from app.rbac import allows
from app.schemas_dictionaries import (
    CODE,
    KIND,
    Dictionary,
    DictionaryAttrOption,
    DictionaryImportError,
    DictionaryImportResult,
    DictionaryImportRow,
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
    #: Кто правит вручную; загрузку файла запускает только администратор (решение 2026-11-11)
    writers: tuple[Rule, ...] = (("admin", "full"),)


# Справочники документооборота читают те, кто работает с письмами, и администратор;
# меняет — `admin: full`.
_DOCUMENTS = Owner(
    "eds", "documents", (("eds.inbox", "read"), ("eds.inbox.register", "full"), ("admin", "read"))
)
# Типы писем читает первая линия (она ставит и меняет тип), правит администратор.
_MAIL = Owner("crm", "mail", (("crm.leads.triage", "read"), ("admin", "read")))
# Виды документов полномочий подписи (SIGN-2): читает держатель реестра, правит администратор.
_SIGNING = Owner("eds", "documents", (("eds.signing.manage", "full"), ("admin", "read")))
# Причины «Закрыть без ответа» читает любой сотрудник (исполнитель поручения), правит администратор.
_CLOSE_REASONS = Owner("eds", "documents", ())
# Справочники «Расчёта» (ERP; решение владельца 2026-11-11 — один механизм): читает тот, кто
# видит настройки компании, и администратор; правит администратор (ERP проверяет `settings.edit`).
_CALC = Owner(
    "erp",
    "calc",
    (("company.settings", "read"), ("admin", "read")),
    (("admin", "full"), ("company.settings", "full")),
)
OWNERS: Final[dict[str, Owner]] = {
    "countries": _CALC,
    "currencies": _CALC,
    "units": _CALC,
    "delivery-basis": _CALC,
    "signing-kinds": _SIGNING,
    "close-reasons": _CLOSE_REASONS,
    "letter-kinds": _DOCUMENTS,
    "receipt-methods": _DOCUMENTS,
    "resolution-kinds": _DOCUMENTS,
    "mail-types": _MAIL,
}
# Причины CRM, которые экран знает под именами справочника документов.
_CRM_REASONS: Final = {"mail_type_name_taken": "name_taken", "mail_type_in_use": "value_in_use"}

Admin = Annotated[Authed, Depends(require("admin", "full"))]
Kind = Annotated[str, Path(pattern=KIND)]
Code = Annotated[str, Path(pattern=CODE)]
# Проверка разделов по владельцу вида: зависимость строится один раз на набор правил.
_READERS = {
    kind: require_any(*owner.readers) if owner.readers else require_any_section
    for kind, owner in OWNERS.items()
}
_WRITERS = {kind: require_any(*owner.writers) for kind, owner in OWNERS.items()}


def _can_read(authed: Authed, owner: Owner) -> bool:
    # Без списка читающих справочник читает любой сотрудник (вход уже проверен).
    if not owner.readers:
        return True
    return any(allows(authed.access, res, need) for res, need in owner.readers)


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
async def list_dictionaries(authed: AuthedDep) -> DictionaryList:
    """Каталог справочников доменов; BFF добавляет домен-владельца и область экрана.

    Домен не ответил — справочники остальных всё равно показываются, недоступный назван в
    `unavailable` (все домены не ответили — ошибка). Варианты поля «вид документа» у типов писем
    (`letter_kind`) BFF берёт из справочника EDS «Виды входящих документов». Сотрудник видит те
    справочники, которые ему положено читать; ни одного — 403."""
    owners = [o for o in (_DOCUMENTS, _MAIL, _CALC) if _can_read(authed, o)]
    if not owners:
        raise PlatformError(
            "FORBIDDEN",
            "Раздел или действие не положены вашей роли.",
            status_code=403,
            details={"resource": "admin", "need": "read"},
        )
    items: list[Dictionary] = []
    unavailable: list[Literal["eds", "crm", "erp"]] = []
    failure: PlatformError | None = None
    for owner in owners:  # по одному запросу на домен-владельца
        try:
            raw = (await _call(authed, owner, "GET", "")).json()
            for entry in raw["items"]:
                found = OWNERS.get(entry.get("kind"))
                if found is not None and found.domain == owner.domain and _can_read(authed, found):
                    items.append(
                        Dictionary.model_validate(
                            {**entry, "owner": found.domain, "area": found.area}
                        )
                    )
        except PlatformError as exc:
            failure = failure or exc
            unavailable.append(owner.domain)
        except (KeyError, TypeError, AttributeError, ValidationError, ValueError):
            failure = failure or backend_unavailable(owner.domain, "bad_dictionary")
            unavailable.append(owner.domain)
    if failure is not None and not items:
        raise failure
    if "eds" not in unavailable:
        await _letter_kind_options(authed, items)
    return DictionaryList(items=items, unavailable=unavailable)


async def _letter_kind_options(authed: Authed, items: list[Dictionary]) -> None:
    """Подставить в `letter_kind` типов писем действующие виды документа EDS (нет — пусто)."""
    targets = [
        a for d in items if d.kind == "mail-types" for a in d.attrs if a.key == "letter_kind"
    ]
    if not targets:
        return
    try:
        response = await _call(authed, _DOCUMENTS, "GET", "/letter-kinds")
        kinds = _parse(DictionaryItemList, response, _DOCUMENTS).items
    except PlatformError:
        return
    options = [DictionaryAttrOption(value=k.code, name=k.name) for k in kinds if k.active]
    for attr in targets:
        attr.options = options


@router.get("/{kind}", response_model=DictionaryItemList, operation_id="listDictionaryItems")
async def list_dictionary_items(
    authed: AuthedDep, kind: Kind, include_hidden: Annotated[bool, Query()] = False
) -> DictionaryItemList:
    owner = _owner(kind)
    await _READERS[kind](authed)
    params = {"include_hidden": "true"} if include_hidden else None
    response = await _call(authed, owner, "GET", f"/{kind}", params=params)
    return _parse(DictionaryItemList, response, owner)


# --- файл: выгрузка и загрузка с проверкой (решение владельца 2026-11-11) ---------------------

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FILE_REASONS: Final = {
    "empty_file": "Файл пустой.",
    "file_too_large": "Файл больше 1 МБ.",
    "unreadable_file": "Файл не читается: нужен xlsx или csv.",
    "not_utf8": "csv должен быть в кодировке UTF-8.",
    "too_many_rows": "В файле больше {detail} строк.",
    "missing_columns": "В шапке нет столбцов: {detail}.",
    "unknown_columns": "В шапке лишние столбцы: {detail}. Скачайте шаблон — это выгрузка списка.",
}


async def _dictionary(authed: Authed, kind: str) -> tuple[Owner, Dictionary]:
    """Описание вида у домена-владельца (поля, закрыт ли); у типов писем — варианты вида
    документа."""
    owner = _owner(kind)
    raw = (await _call(authed, owner, "GET", "")).json()
    entry = next((e for e in raw.get("items", []) if e.get("kind") == kind), None)
    if entry is None:
        raise PlatformError("NOT_FOUND", "Такого справочника нет.", status_code=404)
    try:
        found = Dictionary.model_validate({**entry, "owner": owner.domain, "area": owner.area})
    except ValidationError as exc:
        raise backend_unavailable(owner.domain, "bad_dictionary") from exc
    await _letter_kind_options(authed, [found])
    return owner, found


async def _rows(authed: Authed, owner: Owner, kind: str) -> list[DictionaryItem]:
    response = await _call(authed, owner, "GET", f"/{kind}", params={"include_hidden": "true"})
    return _parse(DictionaryItemList, response, owner).items


@router.get(
    "/{kind}/export",
    response_class=Response,
    operation_id="exportDictionary",
    responses={200: {"content": {_XLSX: {}, "text/csv": {}}}},
)
async def export_dictionary(
    authed: AuthedDep, kind: Kind, format: Annotated[Literal["xlsx", "csv"], Query()] = "xlsx"
) -> Response:
    """Выгрузка списка — она же шаблон загрузки (все строки, и скрытые)."""
    _owner(kind)
    await _READERS[kind](authed)
    owner, dictionary = await _dictionary(authed, kind)
    body = files.export(dictionary, await _rows(authed, owner, kind), format)
    return Response(
        content=body,
        media_type=_XLSX if format == "xlsx" else "text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.{format}"'},
    )


@router.post(
    "/{kind}/import", response_model=DictionaryImportResult, operation_id="importDictionary"
)
async def import_dictionary(
    authed: Admin,
    kind: Kind,
    request: Request,
    dry_run: Annotated[bool, Query()] = True,
) -> DictionaryImportResult:
    """Загрузка файла (тело — xlsx или csv как есть). `dry_run` — только проверка; иначе
    применяются строки, если в файле нет ни одной ошибки. Пишет домен своими обычными действиями;
    строк, которых нет в файле, загрузка не касается."""
    owner, dictionary = await _dictionary(authed, kind)
    raw = await request.body()
    try:
        header, rows = files.read(raw)
        plans = files.plan(dictionary, await _rows(authed, owner, kind), header, rows)
    except files.FileProblemError as exc:
        message = _FILE_REASONS.get(exc.reason, "Файл не подходит.").format(detail=exc.detail)
        raise PlatformError(
            "VALIDATION_FAILED",
            message,
            status_code=422,
            details={"fields": ["file"], "reason": exc.reason},
        ) from exc
    failed = sum(1 for p in plans if p.action == "error")
    applied = False
    if not dry_run and failed == 0:
        applied = True
        for item in plans:
            try:
                if item.create is not None:
                    created = await _call(
                        authed, owner, "POST", f"/{kind}", ok=201, json=item.create
                    )
                    item.code = _parse(DictionaryItem, created, owner).code
                elif item.patch is not None and item.code:
                    await _call(authed, owner, "PATCH", f"/{kind}/{item.code}", json=item.patch)
            except PlatformError as exc:
                item.action = "error"
                reason = (exc.body.details or {}).get("reason")
                item.errors.append(("name", str(reason) if reason else "rejected"))
        failed = sum(1 for p in plans if p.action == "error")
    return DictionaryImportResult(
        applied=applied,
        added=sum(1 for p in plans if p.action == "add"),
        updated=sum(1 for p in plans if p.action == "update"),
        unchanged=sum(1 for p in plans if p.action == "unchanged"),
        failed=failed,
        rows=[
            DictionaryImportRow(
                line=p.line,
                code=p.code,
                name=p.name,
                action=p.action,
                fields=p.fields,
                errors=[DictionaryImportError(field=f, reason=r) for f, r in p.errors],
            )
            for p in plans
        ],
    )


@router.post(
    "/{kind}", response_model=DictionaryItem, status_code=201, operation_id="createDictionaryItem"
)
async def create_dictionary_item(
    authed: AuthedDep, kind: Kind, body: DictionaryItemIn
) -> DictionaryItem:
    owner = _owner(kind)
    await _WRITERS[kind](authed)
    payload = body.model_dump()
    if payload.get("code") is None:
        payload.pop("code", None)  # код создаёт домен из названия (EDS, CRM)
    response = await _call(authed, owner, "POST", f"/{kind}", ok=201, json=payload)
    return _parse(DictionaryItem, response, owner)


@router.put(
    "/{kind}/order", response_model=DictionaryItemList, operation_id="reorderDictionaryItems"
)
async def reorder_dictionary_items(
    authed: AuthedDep, kind: Kind, body: DictionaryOrderIn
) -> DictionaryItemList:
    owner = _owner(kind)
    await _WRITERS[kind](authed)
    response = await _call(authed, owner, "PUT", f"/{kind}/order", json=body.model_dump())
    return _parse(DictionaryItemList, response, owner)


@router.patch("/{kind}/{code}", response_model=DictionaryItem, operation_id="updateDictionaryItem")
async def update_dictionary_item(
    authed: AuthedDep, kind: Kind, code: Code, body: DictionaryItemPatch
) -> DictionaryItem:
    owner = _owner(kind)
    await _WRITERS[kind](authed)
    payload = body.model_dump(exclude_unset=True)
    response = await _call(authed, owner, "PATCH", f"/{kind}/{code}", json=payload)
    return _parse(DictionaryItem, response, owner)


@router.delete(
    "/{kind}/{code}", status_code=204, response_class=Response, operation_id="deleteDictionaryItem"
)
async def delete_dictionary_item(authed: AuthedDep, kind: Kind, code: Code) -> Response:
    owner = _owner(kind)
    await _WRITERS[kind](authed)
    await _call(authed, owner, "DELETE", f"/{kind}/{code}", ok=204)
    return Response(status_code=204)
