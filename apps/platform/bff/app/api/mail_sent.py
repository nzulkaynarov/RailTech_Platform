"""«Почта · Отправленные» (план 2.8, MAIL-1): журнал писем ансамбля из CRM `GET /mail/sent`.

Кому какие строки — решает CRM: сотрудник видит письма, отправленные по его запросу, администратор —
все. Текст письма — отдельным запросом, CRM пишет его просмотр в аудит. Письмо EDS ведёт на карточку
документа в «Все документы». «Отправить ещё раз» (MAIL-2) — CRM `POST /mail/sent/{id}/resend`:
новая строка журнала; у писем со входом, паролем или кодом текста нет — 409
`mail_not_resendable`."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ValidationError

from app.clients.crm_proxy import CrmProxy, crm_error
from app.deps import Authed, require_any_section
from app.errors import backend_unavailable
from app.feeds.numbers import outgoing_document_path

router = APIRouter(tags=["mail"])

Member = Annotated[Authed, Depends(require_any_section)]
Status = Literal["queued", "sent", "failed", "skipped_no_smtp"]
Source = Literal["crm", "erp", "eds"]


class _CrmItem(BaseModel):
    id: int
    to_email: str
    subject: str
    status: Status
    error: str | None
    lang: str
    source: Source
    purpose: str | None
    ref_kind: str | None
    ref_id: str | None
    attachments: int
    resendable: bool = False
    requested_by: int | None
    requested_by_name: str | None
    created_at: datetime
    sent_at: datetime | None


class _CrmPage(BaseModel):
    items: list[_CrmItem]
    next_cursor: str | None


class SentMail(BaseModel):
    id: str
    to: str
    subject: str
    status: Status
    error: str | None
    source: Source
    attachments: int
    resendable: bool
    requested_by: str | None
    created_at: datetime
    sent_at: datetime | None
    path: str | None


class SentMailPage(BaseModel):
    items: list[SentMail]
    next_cursor: str | None


class SentMailBody(BaseModel):
    id: str
    text: str | None
    attachments: list[str]


def _path(item: _CrmItem) -> str | None:
    """Письмо документа EDS (ИСХ на бланке) — карточка документа; остальные пока без перехода."""
    if item.source == "eds" and item.ref_kind == "document" and item.ref_id:
        return outgoing_document_path(item.ref_id)
    return None


def _mail(i: _CrmItem) -> SentMail:
    return SentMail(
        id=str(i.id),
        to=i.to_email,
        subject=i.subject,
        status=i.status,
        error=i.error,
        source=i.source,
        attachments=i.attachments,
        resendable=i.resendable,
        requested_by=i.requested_by_name,
        created_at=i.created_at,
        sent_at=i.sent_at,
        path=_path(i),
    )


async def _crm(authed: Authed, path: str, params: dict[str, str | int] | None = None) -> object:
    response = await CrmProxy(authed.call).raw("GET", path, params=params)
    if response.status_code != 200:
        raise crm_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise backend_unavailable("crm", "bad_response") from exc


@router.get("/mail/sent", response_model=SentMailPage, operation_id="listSentMail")
async def list_sent_mail(
    authed: Member,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: Status | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SentMailPage:
    params: dict[str, str | int] = {"limit": limit}
    if q and q.strip():
        params["q"] = q.strip()
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    try:
        page = _CrmPage.model_validate(await _crm(authed, "/api/v1/mail/sent", params))
    except ValidationError as exc:
        raise backend_unavailable("crm", "bad_response") from exc
    return SentMailPage(
        items=[_mail(i) for i in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/mail/sent/{id}", response_model=SentMailBody, operation_id="getSentMailBody")
async def get_sent_mail_body(id: Annotated[int, Path(ge=1)], authed: Member) -> SentMailBody:
    raw = await _crm(authed, f"/api/v1/mail/sent/{id}")
    try:
        body = SentMailBody.model_validate(
            {**raw, "id": str(raw["id"])} if isinstance(raw, dict) else raw
        )
    except (ValidationError, KeyError) as exc:
        raise backend_unavailable("crm", "bad_response") from exc
    return body


@router.post(
    "/mail/sent/{id}/resend",
    response_model=SentMail,
    status_code=201,
    operation_id="resendSentMail",
)
async def resend_sent_mail(id: Annotated[int, Path(ge=1)], authed: Member) -> SentMail:
    """Новое письмо с тем же адресатом, темой, текстом и вложениями; исходное не меняется."""
    response = await CrmProxy(authed.call).raw("POST", f"/api/v1/mail/sent/{id}/resend")
    if response.status_code != 201:
        raise crm_error(response)
    try:
        return _mail(_CrmItem.model_validate(response.json()))
    except (ValidationError, ValueError) as exc:
        raise backend_unavailable("crm", "bad_response") from exc
