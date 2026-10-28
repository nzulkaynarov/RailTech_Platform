"""Вызовы EDS для «Создать документ» и «Мои документы» (контракт BFF 0.17.0, тег `eds-documents`).

Вызовы идут от имени сотрудника через `Authed.call` (токен доступа EDS из сессии — обмен SSO-токена
CRM `aud=eds`).
Право на тип документа, маршрут согласования, номера и видимость («мои», «все») решает EDS; здесь —
разбор ответов,
перевод ошибок EDS в формат `Error` контракта и сборка карточки (документ и шаги его маршрута).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from app.clients.base import Backend
from app.errors import PlatformError, backend_unavailable
from app.schemas_eds_documents import (
    DOCUMENT_KINDS,
    EdsDealRef,
    EdsDecision,
    EdsDocument,
    EdsDocumentPage,
    EdsDocumentRow,
    EdsFile,
    EdsMoney,
    EdsPerson,
    EdsRecipient,
    EdsRouteStep,
)

log = structlog.get_logger()

Call = Callable[..., Awaitable[httpx.Response]]
API = "/api/v1"

_CODES: dict[int, str] = {
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED",
}


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _field_names(raw: Any) -> tuple[list[str], dict[str, str]]:
    """
    `details.fields` EDS — `[{field, message, type}]`; наружу — имена верхнего уровня и «поле ->
    причина».
    """
    names: list[str] = []
    messages: dict[str, str] = {}
    if not isinstance(raw, list):
        return names, messages
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("field"), str):
            continue
        name = item["field"].split(".")[0]
        if name not in names:
            names.append(name)
        reason = item.get("message")
        if isinstance(reason, str) and name not in messages:
            messages[name] = reason
    return names, messages


def eds_error(response: httpx.Response) -> PlatformError:
    """Ответ EDS не 2xx -> ошибка контракта. Текст EDS сохраняется: он написан для сотрудника."""
    status = response.status_code
    code = _CODES.get(status)
    if code is None:
        return backend_unavailable("eds", f"HTTP {status}")
    body = _body(response)
    message = body.get("message")
    raw = body.get("details")
    details: dict[str, Any] = {"backend_status": status}
    if isinstance(raw, dict):
        for key in ("reason", "permission", "max_bytes", "status"):
            value = raw.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                details[key] = value
        if status == 422:
            fields, messages = _field_names(raw.get("fields"))
            details["fields"] = fields
            if messages:
                details["messages"] = messages
    return PlatformError(
        code,
        message if isinstance(message, str) and message else "Запрос не выполнен.",
        status_code=status,
        source="eds",
        details=details,
    )


class EdsProxy:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def raw(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        backend: Backend = "eds"
        return await self._call(
            backend,
            method,
            path,
            json=json,
            params=params,
            content=content,
            content_type=content_type,
            stream=stream,
            headers=headers,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: int = 200,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.raw(
            method,
            path,
            params=params,
            json=json,
            content=content,
            content_type=content_type,
            headers=headers,
        )
        if response.status_code != expected:
            raise eds_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise backend_unavailable("eds", "bad_response") from exc

    async def model[T: BaseModel](
        self,
        model: type[T],
        method: str,
        path: str,
        *,
        expected: int = 200,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> T:
        """Ответ EDS, разобранный моделью; не та форма — `BACKEND_UNAVAILABLE`."""
        body = await self.request(
            method,
            path,
            expected=expected,
            params=params,
            json=json,
            content=content,
            content_type=content_type,
        )
        try:
            return model.model_validate(body)
        except ValidationError as exc:
            log.warning("eds_bad_response", path=path, errors=len(exc.errors()))
            raise backend_unavailable("eds", "bad_response") from exc


# --- разбор ответов EDS (подмножество eds.yaml) --------------------------------------------------


class _RawDecision(BaseModel):
    round: int
    step: int
    decision: str
    comment: str | None
    by: EdsPerson
    at: Any


class _RawDocument(BaseModel):
    id: str
    kind: str
    number: str | None
    status: str
    version: int
    subject: str
    text: str
    author: EdsPerson
    addressee: EdsPerson | None
    amount: EdsMoney | None
    due_date: str | None
    files: list[EdsFile]
    erp_deal_id: int | None
    deal_number: str | None
    recipient: EdsRecipient | None = None
    approval_id: str | None
    decisions: list[_RawDecision]
    created_at: Any
    updated_at: Any


class _RawStep(BaseModel):
    label: str
    status: str
    decided_by: EdsPerson | None
    decided_at: Any
    comment: str | None


class _RawApproval(BaseModel):
    steps: list[_RawStep]


class _RawListItem(BaseModel):
    id: str
    kind: str
    number: str | None
    status: str
    subject: str
    author: EdsPerson
    amount: EdsMoney | None
    due_date: str | None
    created_at: Any


class _RawRegistryItem(BaseModel):
    kind: str
    id: str
    number: str | None
    title: str
    status: str
    registered_at: Any
    responsible: EdsPerson | None
    links: dict[str, Any] | None = None


def _parse[T: BaseModel](model: type[T], body: Any, path: str) -> T:
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        log.warning("eds_bad_response", path=path, errors=len(exc.errors()))
        raise backend_unavailable("eds", "bad_response") from exc


async def present(proxy: EdsProxy, body: Any, *, me: int) -> EdsDocument:
    """Карточка документа: ответ EDS и шаги маршрута текущего круга (если документ отправлялся).

    Маршрут недоступен (нет права читать маршрут, не найден) — карточка без шагов, решения остаются.
    """
    raw = _parse(_RawDocument, body, f"{API}/documents")
    steps: list[EdsRouteStep] = []
    if raw.approval_id is not None:
        try:
            approval = await proxy.model(_RawApproval, "GET", f"{API}/approvals/{raw.approval_id}")
        except PlatformError as exc:
            if exc.status_code not in (403, 404):
                raise
        else:
            steps = [EdsRouteStep.model_validate(s.model_dump()) for s in approval.steps]
    deal = (
        EdsDealRef(erp_deal_id=raw.erp_deal_id, number=raw.deal_number)
        if raw.erp_deal_id is not None
        else None
    )
    editable = raw.author.crm_user_id == me and (
        raw.status == "draft" or (raw.status == "returned" and raw.kind != "letter_out")
    )
    return EdsDocument.model_validate(
        {
            "id": raw.id,
            "kind": raw.kind,
            "number": raw.number,
            "status": raw.status,
            "version": raw.version,
            "subject": raw.subject,
            "text": raw.text,
            "author": raw.author,
            "addressee": raw.addressee,
            "amount": raw.amount,
            "due_date": raw.due_date,
            "files": [EdsFile.model_validate(f.model_dump()) for f in raw.files],
            "deal": deal,
            "recipient": raw.recipient,
            "route": steps,
            "decisions": [EdsDecision.model_validate(d.model_dump()) for d in raw.decisions],
            "can_edit": editable,
            "created_at": raw.created_at,
            "updated_at": raw.updated_at,
        }
    )


def documents_page(body: Any) -> EdsDocumentPage:
    """`GET /documents` EDS -> страница «Мои документы»."""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise backend_unavailable("eds", "bad_response")
    rows = []
    for entry in items:
        item = _parse(_RawListItem, entry, f"{API}/documents")
        rows.append(
            EdsDocumentRow.model_validate(
                {
                    "kind": item.kind,
                    "id": item.id,
                    "number": item.number,
                    "subject": item.subject,
                    "status": item.status,
                    "author": item.author,
                    "amount": item.amount,
                    "due_date": item.due_date,
                    "created_at": item.created_at,
                    "openable": item.kind in DOCUMENT_KINDS,
                }
            )
        )
    cursor = body.get("next_cursor")
    return EdsDocumentPage(items=rows, next_cursor=cursor if isinstance(cursor, str) else None)


_PROJECT_KINDS = ("contract", "invoice", "act")


def _project_ref(item: _RawRegistryItem) -> str | None:
    """Договор, счёт и акт проекта (проекция ERP, D2-5) ведут в карточку проекта по id сделки."""
    deal_id = (item.links or {}).get("erp_deal_id")
    if item.kind in _PROJECT_KINDS and isinstance(deal_id, int) and not isinstance(deal_id, bool):
        return str(deal_id)
    return None


def registry_page(body: Any) -> EdsDocumentPage:
    """`GET /registry` EDS -> страница реестра «Все документы» (суммы и сроков в реестре нет)."""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise backend_unavailable("eds", "bad_response")
    rows = []
    for entry in items:
        item = _parse(_RawRegistryItem, entry, f"{API}/registry")
        rows.append(
            EdsDocumentRow.model_validate(
                {
                    "kind": item.kind,
                    "id": item.id,
                    "number": item.number,
                    "subject": item.title,
                    "status": item.status,
                    "author": item.responsible,
                    "amount": None,
                    "due_date": None,
                    "created_at": item.registered_at,
                    "openable": item.kind in DOCUMENT_KINDS,
                    "project_ref": _project_ref(item),
                }
            )
        )
    cursor = body.get("next_cursor")
    return EdsDocumentPage(items=rows, next_cursor=cursor if isinstance(cursor, str) else None)
