"""Входящая почта общего ящика (W18A-P2, B-INB-5; контракт: tag `inbound-mail`, 0.34.0).

Очередь, карточка, «Подсказать» и действия — CRM (`/api/v1/inbound-mail*`, права `mail_inbox:*`)
токеном сотрудника; BFF проверяет раздел первой линии `crm.leads.triage` (полный), маппит номера
(лид `L-0042`, путь ВХ) и ошибки. «Зарегистрировать ВХ» — форма P8 (`POST /eds/letters` с
`source_mail_id`); чтобы форма открылась с вложениями, `POST /inbound-mail/{id}/eds-files` читает
файлы письма из CRM и загружает их в EDS (`POST /files`) от имени того же сотрудника — как если бы
он приложил их сам. Приём — карточка «Почта» «Подключений» (`/admin/integrations/imap*`).

W18A-P2-2 (контракт 0.35.0): вкладка «Подозрительные» (`status=spam`), «Не спам» и «Убрать»;
`history` — фильтр «из истории»; «Найти папки» и «Загрузить письма за период» в «Подключениях».
"""

from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Path, Query, Response

from app.clients import crm_models as crm
from app.deps import Authed, require
from app.eds_documents import EdsProxy
from app.errors import PlatformError, backend_reason, backend_unavailable, from_backend
from app.feeds.numbers import lead_number
from app.schemas_eds_documents import EdsFile
from app.schemas_inbound_mail import (
    ImapCheck,
    ImapConnector,
    ImapFolders,
    ImapHistory,
    ImapHistoryIn,
    ImapSettingsIn,
    InboundMail,
    InboundMailArchiveIn,
    InboundMailAssist,
    InboundMailLeadResult,
    InboundMailPage,
    InboundMailReply,
    InboundMailReplyIn,
    MailStatus,
    to_connector,
    to_folders,
    to_history,
    to_mail,
    to_page,
)

router = APIRouter(tags=["inbound-mail"])
admin_router = APIRouter(prefix="/admin/integrations", tags=["integrations"])

CRM = "/api/v1/inbound-mail"
Clerk = Annotated[Authed, Depends(require("crm.leads.triage", "full"))]
AdminRead = Annotated[Authed, Depends(require("admin", "read"))]
AdminWrite = Annotated[Authed, Depends(require("admin", "full"))]
MailId = Annotated[int, Path(ge=1)]

_MESSAGES = {
    "smtp_not_configured": "Почта не настроена — Настройки · Подключения · Почта.",
    "wrong_password": "Пароль указан неверно.",
    "secrets_key_missing": "На сервере не задан ключ шифрования секретов: пароль не сохранить.",
    "assist_disabled": "Помощник канцелярии выключен администратором — разберите письмо вручную.",
}
_HANDLED = "Письмо уже обработано: обновите очередь."
_NOT_CONFIGURED = "Сначала настройте приём почты: сервер, логин и пароль приложения."


def error_of(response: httpx.Response) -> PlatformError:
    """4xx CRM → `Error`; причина CRM — в `details.reason`, текст — словами для сотрудника."""
    reason = backend_reason(response)
    err = from_backend("crm", response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = reason
    if reason in _MESSAGES:
        err.body.message = _MESSAGES[reason]
    elif response.status_code == 409:
        err.body.message = _HANDLED
    return err


async def _json(authed: Authed, method: str, path: str, **kw: Any) -> Any:
    response = await authed.call("crm", method, path, **kw)
    if response.status_code >= 300:
        raise error_of(response)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise backend_unavailable("crm", "bad_response") from exc


async def mail_card(authed: Authed, mail_id: int) -> crm.InboundMailOut:
    return crm.InboundMailOut.model_validate(await _json(authed, "GET", f"{CRM}/{mail_id}"))


@router.get("/inbound-mail", response_model=InboundMailPage, operation_id="listInboundMail")
async def list_inbound_mail(
    authed: Clerk,
    status: Annotated[MailStatus, Query()] = "new",
    history: Annotated[bool | None, Query()] = None,
) -> InboundMailPage:
    params: dict[str, str] = {"status": status}
    if history is not None:
        params["history"] = "true" if history else "false"
    raw = await _json(authed, "GET", CRM, params=params)
    return to_page(crm.InboundMailPage.model_validate(raw))


@router.get("/inbound-mail/{id}", response_model=InboundMail, operation_id="getInboundMail")
async def get_inbound_mail(authed: Clerk, id: MailId) -> InboundMail:
    return to_mail(await mail_card(authed, id))


def _disposition(name: str) -> str:
    safe = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    return f"attachment; filename=\"{safe or 'file'}\"; filename*=UTF-8''{quote(name)}"


async def _file(authed: Authed, mail_id: int, index: int) -> httpx.Response:
    response = await authed.call("crm", "GET", f"{CRM}/{mail_id}/attachments/{index}")
    if response.status_code != 200:
        raise error_of(response)
    return response


@router.get(
    "/inbound-mail/{id}/attachments/{index}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadInboundMailAttachment",
)
async def download_attachment(
    authed: Clerk,
    id: MailId,
    index: Annotated[int, Path(ge=0, le=49)],
) -> Response:
    card = await mail_card(authed, id)
    item = next((a for a in card.attachments if a.index == index), None)
    response = await _file(authed, id, index)
    headers = {
        "Content-Disposition": _disposition(item.name if item else "file"),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    # Файл всегда скачивается (attachment), тип содержимого не доверяется.
    return Response(response.content, media_type="application/octet-stream", headers=headers)


def _multipart(name: str, content_type: str, data: bytes) -> tuple[bytes, str]:
    request = httpx.Request(
        "POST", "http://eds.invalid/", files={"file": (name, data, content_type)}
    )
    return request.read(), request.headers["content-type"]


@router.post(
    "/inbound-mail/{id}/eds-files",
    response_model=list[EdsFile],
    operation_id="copyInboundMailFilesToEds",
)
async def copy_files_to_eds(authed: Clerk, id: MailId) -> list[EdsFile]:
    """Вложения письма — файлами EDS текущего сотрудника (для `file_ids` формы «Зарегистрировать
    входящее»). Белый список CRM совпадает со списком EDS, поэтому файлы принимаются как есть."""
    card = await mail_card(authed, id)
    eds = EdsProxy(authed.call)
    out: list[EdsFile] = []
    for item in card.attachments:
        data = (await _file(authed, id, item.index)).content
        body, content_type = _multipart(item.name, item.content_type, data)
        out.append(
            await eds.model(
                EdsFile,
                "POST",
                "/api/v1/files",
                expected=201,
                content=body,
                content_type=content_type,
            )
        )
    return out


@router.post(
    "/inbound-mail/{id}/assist",
    response_model=InboundMailAssist,
    operation_id="assistInboundMail",
)
async def assist(authed: Clerk, id: MailId) -> InboundMailAssist:
    """«Подсказать» — только по кнопке (решение юриста 2026-11-02); маскирование и журнал — CRM."""
    raw = await _json(authed, "POST", f"{CRM}/{id}/assist")
    return InboundMailAssist.model_validate(crm.InboundMailAssist.model_validate(raw).model_dump())


@router.post(
    "/inbound-mail/{id}/lead",
    response_model=InboundMailLeadResult,
    operation_id="createLeadFromInboundMail",
)
async def create_lead(authed: Clerk, id: MailId) -> InboundMailLeadResult:
    raw = crm.InboundMailLeadOut.model_validate(await _json(authed, "POST", f"{CRM}/{id}/lead"))
    return InboundMailLeadResult(
        lead_id=raw.lead_id, lead_number=lead_number(raw.lead_id), created=raw.created
    )


@router.post("/inbound-mail/{id}/archive", status_code=204, operation_id="archiveInboundMail")
async def archive(body: InboundMailArchiveIn, authed: Clerk, id: MailId) -> Response:
    await _json(authed, "POST", f"{CRM}/{id}/archive", json={"reason": body.reason.strip()})
    return Response(status_code=204)


@router.post("/inbound-mail/{id}/not-spam", status_code=204, operation_id="markInboundMailNotSpam")
async def not_spam(authed: Clerk, id: MailId) -> Response:
    """«Не спам → в очередь» (W18A-P2-2): ящик на сервере не меняется."""
    await _json(authed, "POST", f"{CRM}/{id}/not-spam")
    return Response(status_code=204)


@router.post("/inbound-mail/{id}/discard", status_code=204, operation_id="discardInboundMail")
async def discard(authed: Clerk, id: MailId) -> Response:
    """«Убрать» подозрительное письмо — в архив с причиной «Спам»."""
    await _json(authed, "POST", f"{CRM}/{id}/discard")
    return Response(status_code=204)


@router.post(
    "/inbound-mail/{id}/reply", response_model=InboundMailReply, operation_id="replyInboundMail"
)
async def reply(body: InboundMailReplyIn, authed: Clerk, id: MailId) -> InboundMailReply:
    raw = await _json(authed, "POST", f"{CRM}/{id}/reply", json={"text": body.text})
    return InboundMailReply.model_validate(crm.InboundMailReply.model_validate(raw).model_dump())


# --- приём почты в «Подключениях» -----------------------------------------------------------------


def _connector(raw: Any) -> ImapConnector:
    return to_connector(crm.ImapStatusOut.model_validate(raw))


@admin_router.get("/imap", response_model=ImapConnector, operation_id="getImapConnector")
async def get_imap(authed: AdminRead) -> ImapConnector:
    return _connector(await _json(authed, "GET", "/api/v1/integrations/imap"))


@admin_router.put("/imap", response_model=ImapConnector, operation_id="saveImapConnector")
async def save_imap(body: ImapSettingsIn, authed: AdminWrite) -> ImapConnector:
    payload = {
        "host": body.host,
        "port": body.port,
        "security": body.security,
        "mailbox": body.mailbox,
        "folders": [f.model_dump() for f in body.folders] if body.folders is not None else None,
        "assist_enabled": body.assist_enabled,
        "username": body.username,
        "imap_password": body.imap_password.get_secret_value() if body.imap_password else None,
        "password": body.password.get_secret_value(),
    }
    return _connector(await _json(authed, "PUT", "/api/v1/integrations/imap", json=payload))


@admin_router.post("/imap/check", response_model=ImapCheck, operation_id="checkImap")
async def check_imap(authed: AdminWrite) -> ImapCheck:
    raw = await _json(authed, "POST", "/api/v1/integrations/imap/check", probe=True)
    return ImapCheck.model_validate(crm.ImapCheckOut.model_validate(raw).model_dump())


@admin_router.post("/imap/folders", response_model=ImapFolders, operation_id="findImapFolders")
async def find_folders(authed: AdminWrite) -> ImapFolders:
    raw = await _json(authed, "POST", "/api/v1/integrations/imap/folders", probe=True)
    return to_folders(crm.ImapFoldersOut.model_validate(raw))


@admin_router.post("/imap/history", response_model=ImapHistory, operation_id="startImapHistory")
async def start_history(body: ImapHistoryIn, authed: AdminWrite) -> ImapHistory:
    response = await authed.call(
        "crm", "POST", "/api/v1/integrations/imap/history", json={"days": body.days}
    )
    if response.status_code >= 300:
        err = error_of(response)
        if response.status_code == 409:
            err.body.message = _NOT_CONFIGURED
        raise err
    try:
        return to_history(crm.ImapHistoryOut.model_validate(response.json()))
    except ValueError as exc:
        raise backend_unavailable("crm", "bad_response") from exc
