"""Входящая почта общего ящика (W18A-P2, B-INB-5; контракт: tag `inbound-mail`, 0.34.0).

Очередь, карточка, «Подсказать» и действия — CRM (`/api/v1/inbound-mail*`, права `mail_inbox:*`)
токеном сотрудника; BFF проверяет раздел первой линии `crm.leads.triage` (полный), маппит номера
(лид `L-0042`, путь ВХ) и ошибки. «Зарегистрировать ВХ» — форма P8 (`POST /eds/letters` с
`source_mail_id`: сначала CRM помечает письмо «Регистрируется»); чтобы форма открылась с вложениями,
`POST /inbound-mail/{id}/eds-files` читает файлы письма из CRM и загружает их в EDS (`POST
/files`) от
имени того же сотрудника — как если бы он приложил их сам. Приём — карточка «Почта» «Подключений»
(`/admin/integrations/imap*`).

W18A-P2-2 (контракт 0.35.0): вкладка «Подозрительные» (`status=spam`), «Не спам» и «Убрать»;
`history` — фильтр «из истории»; «Найти папки» и «Загрузить письма за период» в «Подключениях».

W18A-P2-3 (контракт 0.36.0): обращение — представления (`view`), «в работе», цепочки, адресаты.
Список,
карточка, ответ и «Вернуть в Новые» открыты любому сотруднику: CRM показывает ему только письма,
где он
исполнитель или «адресовано лично» (403 на чужое); действия первой линии — `crm.leads.triage`.
"""

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Path, Query, Response

from app.clients import crm_models as crm
from app.deps import Authed, require, require_any_section
from app.eds_documents import EdsProxy
from app.errors import (
    PlatformError,
    backend_reason,
    backend_unavailable,
    from_backend,
    retry_after_seconds,
)
from app.feeds.numbers import lead_number
from app.schemas_eds_documents import EdsFile
from app.schemas_inbound_mail import (
    TYPE_CODE,
    ImapCheck,
    ImapConnector,
    ImapFolders,
    ImapHistory,
    ImapHistoryIn,
    ImapSettingsIn,
    InboundMail,
    InboundMailArchiveIn,
    InboundMailAssist,
    InboundMailBulkArchiveIn,
    InboundMailBulkArchiveResult,
    InboundMailCheck,
    InboundMailLeadResult,
    InboundMailPage,
    InboundMailReply,
    InboundMailReplyIn,
    InboundMailTakeIn,
    MailView,
    check_too_soon,
    to_bulk,
    to_check,
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
Member = Annotated[Authed, Depends(require_any_section)]
AdminRead = Annotated[Authed, Depends(require("admin", "read"))]
AdminWrite = Annotated[Authed, Depends(require("admin", "full"))]
MailId = Annotated[int, Path(ge=1)]

_MESSAGES = {
    "smtp_not_configured": "Почта не настроена — Настройки · Подключения · Почта.",
    "wrong_password": "Пароль указан неверно.",
    "secrets_key_missing": "На сервере не задан ключ шифрования секретов: пароль не сохранить.",
    "assist_disabled": "Помощник канцелярии выключен администратором — разберите письмо вручную.",
    "mail_handled": "Письмо уже обработано: обновите очередь.",
    "mail_registering": "Письмо уже регистрируется — дождитесь результата.",
    "mail_not_returnable": "Это письмо нельзя вернуть в «Новые».",
    "mail_type_inactive": "Этот тип отключён — выберите другой.",
    "mail_rule_exists": "Такое правило уже есть.",
    "mail_no_handover_target": "Передать можно только тому, кто подтверждает оплату.",
}
_CHECK_WAIT_S = 35.0  # CRM ждёт опрос до 30 секунд, потом отвечает «checking»
_HANDLED = "Письмо уже обработано: обновите очередь."
_TZ = ZoneInfo("Asia/Tashkent")
_NOT_CONFIGURED = "Сначала настройте приём почты: сервер, логин и пароль приложения."


def _since(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone(_TZ).strftime("%H:%M")
    except ValueError:
        return ""


def error_of(response: httpx.Response) -> PlatformError:
    """4xx CRM → `Error`; причина CRM — в `details.reason`, текст — словами для сотрудника.

    «Уже в работе у …» (W18A-P2-3): имя и время взятия — в `details.assignee_name` и `assigned_at`,
    чтобы экран предложил «Забрать себе»."""
    reason = backend_reason(response)
    err = from_backend("crm", response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = reason
    if reason == "mail_in_work_by_other":
        try:
            backend = response.json()["details"]
        except (ValueError, KeyError, TypeError):
            backend = {}
        name, since = str(backend.get("assignee_name") or ""), _since(backend.get("assigned_at"))
        if err.body.details is not None:
            err.body.details.update(assignee_name=name, assigned_at=backend.get("assigned_at"))
        who = f"у {name}" if name else "у коллеги"
        err.body.message = f"Письмо уже в работе {who}" + (f" с {since}." if since else ".")
    elif reason in _MESSAGES:
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
    authed: Member,
    view: Annotated[MailView, Query()] = "new",
    history: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    type: Annotated[str | None, Query(pattern=TYPE_CODE)] = None,
) -> InboundMailPage:
    params: dict[str, str] = {"view": view}
    if type:
        params["type"] = type
    if history is not None:
        params["history"] = "true" if history else "false"
    if q and q.strip():
        params["q"] = q.strip()
    raw = await _json(authed, "GET", CRM, params=params)
    return to_page(crm.InboundMailPage.model_validate(raw))


@router.post("/inbound-mail/poll", response_model=InboundMailCheck, operation_id="checkInboundMail")
async def check_inbound_mail(authed: Member) -> InboundMailCheck:
    """«Проверить почту» (MAIL-NOW): CRM читает общий ящик сразу, под блокировкой планового опроса;
    любой сотрудник, как просмотр очереди. Проверяли меньше 20 секунд назад — `too_soon` с
    `retry_after_s` (не ошибка). Ждёт до 30 секунд; идёт или продолжается в фоне — `checking`."""
    response = await authed.call("crm", "POST", f"{CRM}/poll", wait_seconds=_CHECK_WAIT_S)
    if response.status_code == 429:
        return check_too_soon(retry_after_seconds(response))
    if response.status_code >= 300:
        raise error_of(response)
    try:
        return to_check(crm.InboundMailCheckOut.model_validate(response.json()))
    except ValueError as exc:
        raise backend_unavailable("crm", "bad_response") from exc


@router.get("/inbound-mail/{id}", response_model=InboundMail, operation_id="getInboundMail")
async def get_inbound_mail(authed: Member, id: MailId) -> InboundMail:
    return to_mail(await mail_card(authed, id))


@router.post("/inbound-mail/{id}/read", status_code=204, operation_id="markInboundMailRead")
async def mark_read(authed: Member, id: MailId) -> Response:
    """Открыл карточку — прочитано (отметка на человека)."""
    await _json(authed, "POST", f"{CRM}/{id}/read")
    return Response(status_code=204)


@router.post("/inbound-mail/{id}/take", status_code=204, operation_id="takeInboundMail")
async def take(body: InboundMailTakeIn, authed: Clerk, id: MailId) -> Response:
    """«Взять в работу»; `takeover` — «Забрать себе» у того, кто ведёт письмо (запись в журнал)."""
    await _json(authed, "POST", f"{CRM}/{id}/take", json={"takeover": body.takeover})
    return Response(status_code=204)


@router.post("/inbound-mail/{id}/release", status_code=204, operation_id="releaseInboundMail")
async def release(authed: Member, id: MailId) -> Response:
    """«Вернуть в Новые»: своё «в работе» или разобранное архивом/ответом (запись в журнал)."""
    await _json(authed, "POST", f"{CRM}/{id}/release")
    return Response(status_code=204)


@router.post(
    "/inbound-mail/bulk-archive",
    response_model=InboundMailBulkArchiveResult,
    operation_id="bulkArchiveInboundMail",
)
async def bulk_archive(
    body: InboundMailBulkArchiveIn, authed: Clerk
) -> InboundMailBulkArchiveResult:
    """«В архив» нескольких писем с причиной; пропущенные (в работе у другого, разобранные)
    названы."""
    raw = await _json(
        authed, "POST", f"{CRM}/bulk-archive", json={"ids": body.ids, "reason": body.reason.strip()}
    )
    return to_bulk(crm.InboundMailBulkArchiveOut.model_validate(raw))


async def mail_registration(
    authed: Authed, mail_id: int, state: str, *, quiet: bool = False
) -> None:
    """CRM: ВХ из письма создаётся (`start` — 409, если ведёт другой или уже разобрано) или EDS
    отказал (`cancel`, без ошибок)."""
    response = await authed.call(
        "crm", "POST", f"{CRM}/{mail_id}/registration", json={"state": state}
    )
    if response.status_code >= 300 and not quiet:
        raise error_of(response)


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
    authed: Member,
    id: MailId,
    index: Annotated[int, Path(ge=0, le=49)],
) -> Response:
    response = await _file(authed, id, index)
    headers = {
        # Имя уже очищено CRM (`attachment; filename=…; filename*=UTF-8''…`).
        "Content-Disposition": response.headers.get(
            "content-disposition", 'attachment; filename="file"'
        ),
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
        if item.inline:  # картинки внутри письма (логотип, баннер) — не файлы входящего
            continue
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
async def reply(body: InboundMailReplyIn, authed: Member, id: MailId) -> InboundMailReply:
    payload = {
        "text": body.text,
        "to": body.to,
        "reply_all": body.reply_all,
        "awaiting": body.awaiting,
    }
    raw = await _json(authed, "POST", f"{CRM}/{id}/reply", json=payload)
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
        "personal_rule": body.personal_rule,
        "personal_label": body.personal_label,
        "trusted_auth_servers": body.trusted_auth_servers,
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
