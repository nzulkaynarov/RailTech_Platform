"""«+ Создать заявку» (W16-D1-2b, контракт: tag `requests`): заявка из лида или клиента,
«Повторить отправку в ERP», письмо директору файлом в EDS.

Раздел каталога — `crm.clients` полный (403 — до CRM и EDS); «взять вложение из переписки» — ещё и
`crm.leads` от чтения. Заявку создаёт CRM: лид — `POST /leads/{id}/actions/create_request`, клиент —
`POST /clients/{id}/actions/create_request`; повтор формы с тем же `request_key` CRM отдаёт 200
с той же заявкой, BFF повторяет её статус. Отказы CRM (`handoff_no_consent`, `consent_via_bot`,
`request_not_allowed`, …) — `Error` с кодом в `details.reason`.

Файл письма идёт в EDS от имени сотрудника (обмен токена `aud=eds`) так же, как в «Создать
документ»: тело до 25 МБ передаётся как есть. Вложение переписки BFF читает из CRM потоком с тем же
пределом и отправляет EDS формой multipart с именем и типом файла из ответа CRM.

«Записка о звонке» (СЦ-6) — основание заявки по звонку: PDF строит EDS в воркере
(`POST /call-notes`, 202 и опрос), BFF проверяет лид в CRM (канал «телефон», согласие) и отдаёт EDS
поля лида; сам документ BFF не строит и не хранит.
"""

import re
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Path, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.crm_messages import _lead_id
from app.api.eds_documents import MAX_UPLOAD_BYTES, FileStream, _read_limited, _too_large
from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy, crm_error
from app.crm_clients_view import CrmRequestCreated, CrmRequestRetried
from app.deps import Authed, require, require_all
from app.eds_documents import EdsProxy, eds_error
from app.errors import PlatformError, backend_unavailable
from app.feeds.numbers import lead_number
from app.schemas_crm_leads import (
    CallNoteView,
    RequestCallNoteIn,
    RequestCreatedView,
    RequestFileFromMessageIn,
    RequestFormIn,
    RequestRetriedView,
)
from app.schemas_eds_documents import EdsFile

router = APIRouter(tags=["requests"])

API = "/api/v1"
Writer = Annotated[Authed, Depends(require("crm.clients", "full"))]
Copier = Annotated[Authed, Depends(require_all(("crm.leads", "read"), ("crm.clients", "full")))]

_FILENAME_STAR = re.compile(r"filename\*\s*=\s*UTF-8''([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r'filename\s*=\s*"([^"]*)"', re.IGNORECASE)


def _crm_body(body: RequestFormIn) -> dict[str, object]:
    """Тело CRM `RequestCreate`: поля формы как есть, без лида (он — в пути)."""
    return body.model_dump(exclude={"lead"})


@router.post(
    "/crm/requests",
    response_model=RequestCreatedView,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": RequestCreatedView}},
    operation_id="createCrmRequest",
)
async def create_request(
    body: RequestFormIn, authed: Writer, response: Response
) -> RequestCreatedView:
    if body.lead is not None:
        path = f"{API}/leads/{_lead_id(body.lead)}/actions/create_request"
    elif body.client_id is not None:
        path = f"{API}/clients/{body.client_id}/actions/create_request"
    else:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Выберите клиента или лида.",
            status_code=422,
            details={"fields": ["client_id"]},
        )
    upstream = await CrmProxy(authed.call).raw("POST", path, json=_crm_body(body))
    if upstream.status_code not in (200, 201):
        raise crm_error(upstream)
    try:
        out = CrmRequestCreated.model_validate(upstream.json())
    except ValueError as exc:
        raise backend_unavailable("crm", "bad_response") from exc
    response.status_code = upstream.status_code
    return RequestCreatedView(
        client_id=out.client_id,
        deal=out.deal_id,
        lead=lead_number(out.lead_id) if out.lead_id is not None else None,
        created=out.created and upstream.status_code == 201,
        transfer=out.erp_request_status,
    )


@router.post(
    "/crm/requests/{deal}/retry",
    response_model=RequestRetriedView,
    operation_id="retryCrmRequest",
)
async def retry_request(deal: Annotated[int, Path(ge=1)], authed: Writer) -> RequestRetriedView:
    out = await CrmProxy(authed.call).get_model(
        CrmRequestRetried, "POST", f"{API}/deals/{deal}/actions/retry_request"
    )
    return RequestRetriedView(
        deal=out.deal_id, client_id=out.client_id, transfer=out.erp_request_status
    )


@router.post(
    "/crm/request-files",
    response_model=EdsFile,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadCrmRequestFile",
)
async def upload_request_file(request: Request, authed: Writer) -> EdsFile:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    return await EdsProxy(authed.call).model(
        EdsFile, "POST", f"{API}/files", expected=201, content=body, content_type=content_type
    )


def filename_of(disposition: str) -> str:
    """Имя файла из `Content-Disposition` CRM: сначала UTF-8 (RFC 6266), затем запасное ASCII."""
    star = _FILENAME_STAR.search(disposition)
    if star:
        name = unquote(star.group(1).strip())
        if name:
            return name
    plain = _FILENAME.search(disposition)
    return plain.group(1) if plain and plain.group(1) else "file"


async def _attachment(authed: Authed, body: RequestFileFromMessageIn) -> tuple[bytes, str, str]:
    """Вложение сообщения из CRM потоком; больше 25 МБ — 413 без дочитывания."""
    path = f"{API}/leads/{_lead_id(body.lead)}/messages/{body.message}/attachments/{body.index}"
    upstream = await CrmProxy(authed.call).raw("GET", path, stream=True)
    try:
        if upstream.status_code != 200:
            await upstream.aread()
            raise crm_error(upstream)
        data = bytearray()
        async for chunk in upstream.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_UPLOAD_BYTES:
                raise _too_large()
        name = filename_of(upstream.headers.get("content-disposition", ""))
        mime = upstream.headers.get("content-type", "application/octet-stream")
        return bytes(data), name, mime.split(";")[0].strip() or "application/octet-stream"
    finally:
        await upstream.aclose()


@router.post(
    "/crm/request-files/from-message",
    response_model=EdsFile,
    status_code=status.HTTP_201_CREATED,
    operation_id="copyCrmMessageAttachmentToRequest",
)
async def copy_message_attachment(body: RequestFileFromMessageIn, authed: Copier) -> EdsFile:
    data, name, mime = await _attachment(authed, body)
    form = httpx.Request("POST", "http://eds.invalid/", files={"file": (name, data, mime)})
    content = form.read()
    return await EdsProxy(authed.call).model(
        EdsFile,
        "POST",
        f"{API}/files",
        expected=201,
        content=content,
        content_type=form.headers["content-type"],
    )


_NOT_PHONE = "Записка о звонке составляется только по лиду со звонка."
_NO_CONSENT = "Нет согласия клиента на обработку данных — записку о звонке не составить."


def _conflict(reason: str, message: str) -> PlatformError:
    return PlatformError(
        "CONFLICT", message, status_code=409, details={"reason": reason, "backend_status": 409}
    )


async def _lead_call_note(authed: Authed, body: RequestCallNoteIn, lead: str) -> dict[str, object]:
    """Тело EDS по лиду со звонка: телефонный лид и согласие (в CRM или отмеченное в форме)."""
    detail = await CrmProxy(authed.call).get_model(
        crm.LeadDetail, "GET", f"{API}/leads/{_lead_id(lead)}"
    )
    if detail.source != "phone":
        raise _conflict("call_note_not_phone", _NOT_PHONE)
    if detail.consent_given_at is None and not body.consent:
        raise _conflict("call_note_no_consent", _NO_CONSENT)
    return {
        "request_key": body.request_key,
        "lang": body.lang,
        "lead": lead_number(detail.id),
        "caller_name": detail.display_name,
        "company": detail.company_name,
        "phone": detail.phone_e164 or detail.client_phone_e164,
        "email": detail.email,
        "called_at": detail.created_at.isoformat(),
        "taken_by": detail.assigned_user_name,
        "need": detail.need_summary,
    }


def _form_call_note(body: RequestCallNoteIn) -> dict[str, object]:
    """Тело EDS без лида (повторный звонок): поля формы; «Когда» — сейчас, «Принял» — сотрудник."""
    caller = body.caller
    if caller is None:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Укажите, кто звонил.",
            status_code=422,
            details={"fields": ["caller"]},
        )
    return {
        "request_key": body.request_key,
        "lang": body.lang,
        "lead": None,
        "caller_name": caller.name,
        "company": caller.company,
        "phone": caller.phone,
        "email": caller.email,
        "called_at": datetime.now(UTC).isoformat(),
        "taken_by": None,
        "need": body.need,
    }


@router.post(
    "/crm/request-files/call-note",
    response_model=CallNoteView,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createCrmRequestCallNote",
)
async def create_call_note(body: RequestCallNoteIn, authed: Writer) -> CallNoteView:
    payload = (
        await _lead_call_note(authed, body, body.lead)
        if body.lead is not None
        else _form_call_note(body)
    )
    return await EdsProxy(authed.call).model(
        CallNoteView, "POST", f"{API}/call-notes", expected=202, json=payload
    )


@router.get(
    "/crm/request-files/call-note/{note}",
    response_model=CallNoteView,
    operation_id="getCrmRequestCallNote",
)
async def get_call_note(note: UUID, authed: Writer) -> CallNoteView:
    return await EdsProxy(authed.call).model(CallNoteView, "GET", f"{API}/call-notes/{note}")


@router.get(
    "/crm/request-files/{file_id}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadCrmRequestFile",
)
async def download_request_file(file_id: UUID, authed: Writer) -> Response:
    """«Открыть» файл основания: свой файл сотрудника в EDS, потоком и всегда вложением."""
    upstream = await EdsProxy(authed.call).raw("GET", f"{API}/files/{file_id}", stream=True)
    if upstream.status_code != 200:
        try:
            await upstream.aread()
            raise eds_error(upstream)
        finally:
            await upstream.aclose()
    headers = {
        "Content-Disposition": upstream.headers.get("content-disposition") or "attachment",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(upstream, headers, "application/octet-stream")
