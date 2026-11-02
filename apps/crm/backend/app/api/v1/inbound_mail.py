"""Входящая почта (W18A-P2, B-INB-5): очередь, карточка, действия; приём в «Подключениях».

Очередь и действия — `mail_inbox:read|work` (раздел каталога `crm.leads.triage`); настройки
приёма — `integrations:read|write`, как SMTP карточки «Почта».
"""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.api.deps import ContainerDep, require
from app.schemas.inbound_mail import (
    ImapCheckOut,
    ImapConnectorIn,
    ImapStatusOut,
    InboundMailArchiveIn,
    InboundMailLeadOut,
    InboundMailOut,
    InboundMailPage,
    InboundMailReply,
    InboundMailReplyIn,
)
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["inbound-mail"])

Reader = Annotated[Principal, Depends(require("mail_inbox", "read"))]
Worker = Annotated[Principal, Depends(require("mail_inbox", "work"))]
AdminReader = Annotated[Principal, Depends(require("integrations", "read"))]
AdminWriter = Annotated[Principal, Depends(require("integrations", "write"))]
MailId = Annotated[int, Path(ge=1)]


def _disposition(name: str) -> str:
    safe = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    return f"attachment; filename=\"{safe or 'file'}\"; filename*=UTF-8''{quote(name)}"


@router.get("/inbound-mail", response_model=InboundMailPage)
async def list_inbound_mail(
    _: Reader,
    container: ContainerDep,
    status: Literal["new", "registered", "lead", "archived"] = Query("new"),
) -> InboundMailPage:
    """Очередь «Входящая почта» (по умолчанию — необработанные, новые сверху, до 200) и состояние
    приёма: `mailbox.configured = false` — приём не настроен (подсказка «Настройки · Подключения ·
    Почта»)."""
    return await container.inbound_mail.page(status)


@router.get("/inbound-mail/{mail_id}", response_model=InboundMailOut)
async def get_inbound_mail(mail_id: MailId, _: Reader, container: ContainerDep) -> InboundMailOut:
    """Карточка письма: отправитель, тема, текст, вложения, связка, подсказка помощника, итог."""
    return await container.inbound_mail.get(mail_id)


@router.get(
    "/inbound-mail/{mail_id}/attachments/{index}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_inbound_mail_attachment(
    mail_id: MailId,
    index: Annotated[int, Path(ge=0, lt=50)],
    _: Reader,
    container: ContainerDep,
) -> Response:
    """Файл вложения из хранилища CRM (ключ и адрес хранилища наружу не уходят)."""
    data, name, mime = await container.inbound_mail.attachment(mail_id, index)
    headers = {"Content-Disposition": _disposition(name), "Cache-Control": "private, no-store"}
    return Response(data, media_type=mime, headers=headers)


@router.post("/inbound-mail/{mail_id}/lead", response_model=InboundMailLeadOut)
async def create_lead_from_mail(
    mail_id: MailId, who: Worker, container: ContainerDep
) -> InboundMailLeadOut:
    """«Создать лид»: лид без ответственного во «Входящих» или заметка в открытом лиде с этим
    адресом. Письмо уже обработано — 409."""
    return await container.inbound_mail.create_lead(who, mail_id)


@router.post("/inbound-mail/{mail_id}/archive", status_code=204)
async def archive_inbound_mail(
    mail_id: MailId, body: InboundMailArchiveIn, who: Worker, container: ContainerDep
) -> Response:
    """«Архив» с причиной. Письмо уже обработано — 409."""
    await container.inbound_mail.archive(who, mail_id, body.reason)
    return Response(status_code=204)


@router.post("/inbound-mail/{mail_id}/reply", response_model=InboundMailReply)
async def reply_inbound_mail(
    mail_id: MailId, body: InboundMailReplyIn, who: Worker, container: ContainerDep
) -> InboundMailReply:
    """Ответ отправителю в ту же цепочку (In-Reply-To, References) почтовым сервисом. Почта не
    настроена — 409 `smtp_not_configured`."""
    return await container.inbound_mail.reply(who, mail_id, body.text)


@router.get("/integrations/imap", response_model=ImapStatusOut)
async def get_imap_status(_: AdminReader, container: ContainerDep) -> ImapStatusOut:
    """Приём почты общего ящика: хост, порт, папка, логин; пароль — только «задан» и `last4`;
    итог последнего опроса."""
    return await container.imap_connector.status()


@router.put("/integrations/imap", response_model=ImapStatusOut)
async def put_imap_connector(
    body: ImapConnectorIn, who: AdminWriter, container: ContainerDep
) -> ImapStatusOut:
    """Сохранить приём (после пароля админа); логин/пароль `null` — оставить прежние, пустой хост
    — выключить. Ошибки: `smtp_invalid_host` (422, `host`), `wrong_password` (422),
    `secrets_key_missing` (409)."""
    secret = body.imap_password.get_secret_value() if body.imap_password is not None else None
    return await container.imap_connector.save(
        who,
        host=body.host,
        port=body.port,
        security=body.security,
        mailbox=body.mailbox,
        assist_enabled=body.assist_enabled,
        username=body.username,
        password=secret,
        admin_password=body.password.get_secret_value(),
    )


@router.post("/integrations/imap/check", response_model=ImapCheckOut)
async def check_imap_connector(_: AdminWriter, container: ContainerDep) -> ImapCheckOut:
    """«Проверить приём»: вход и папка только на чтение, без чтения писем. Итог — в ответе:
    `error_kind` — `not_configured`, `invalid_host`, `unavailable`, `tls_failed`, `auth_failed`,
    `mailbox_missing`."""
    return await container.imap_connector.check()
