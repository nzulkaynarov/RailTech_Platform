"""Входящая почта (W18A-P2, B-INB-5; обращение — W18A-P2-3): очередь, карточка, действия; приём.

Первая линия — `mail_inbox:read|work` (раздел каталога `crm.leads.triage`); остальной сотрудник
видит
и ведёт только свои письма (исполнитель или «адресовано лично»): очередь и карточка по тем же
адресам,
действия первой линии ему недоступны (403). Настройки приёма — `integrations:read|write`, как SMTP
карточки «Почта». Папки «Спам» и загрузка писем за период — W18A-P2-2.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.api.deps import ContainerDep, PrincipalDep, get_rbac, require
from app.domain.errors import PasswordChangeRequiredError
from app.domain.mail_types import CODE_PATTERN
from app.repositories.inbound_mail_views import View
from app.schemas.inbound_mail import (
    ImapCheckOut,
    ImapConnectorIn,
    ImapFoldersOut,
    ImapHistoryIn,
    ImapHistoryOut,
    ImapStatusOut,
    InboundMailArchiveIn,
    InboundMailAssist,
    InboundMailBulkArchiveIn,
    InboundMailBulkArchiveOut,
    InboundMailLeadOut,
    InboundMailOut,
    InboundMailPage,
    InboundMailRegistrationIn,
    InboundMailReply,
    InboundMailReplyIn,
    InboundMailTakeIn,
)
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services.inbound_mail import MailAccess

router = APIRouter(prefix="/api/v1", tags=["inbound-mail"])

Worker = Annotated[Principal, Depends(require("mail_inbox", "work"))]
AdminReader = Annotated[Principal, Depends(require("integrations", "read"))]
AdminWriter = Annotated[Principal, Depends(require("integrations", "write"))]
MailId = Annotated[int, Path(ge=1)]


async def mail_access(
    principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
) -> MailAccess:
    """Любой сотрудник: первая линия (`mail_inbox:read`) видит всю очередь, остальные — свои
    письма."""
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    full = rbac.allowed(principal.rbac_roles, "mail_inbox", "read", principal.platform_role_ids)
    return MailAccess(principal, full)


Access = Annotated[MailAccess, Depends(mail_access)]


def _disposition(name: str) -> str:
    safe = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    return f"attachment; filename=\"{safe or 'file'}\"; filename*=UTF-8''{quote(name)}"


@router.get("/inbound-mail", response_model=InboundMailPage)
async def list_inbound_mail(
    access: Access,
    container: ContainerDep,
    view: Annotated[View, Query()] = "new",
    history: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    type: Annotated[str | None, Query(pattern=CODE_PATTERN)] = None,
) -> InboundMailPage:
    """Очередь «Входящая почта» по представлению (до 200, новые сверху) и состояние приёма:
    `new` — Новые, `mine` — мои в работе, `in_work` — все в работе, `done` — Разобранные (с итогом),
    `spam` — Подозрительные, `all` — все (кроме подозрительных), `tasks` — для «Моих задач»: новые
    не
    «из истории» и мои в работе. `mailbox.configured = false` — приём не настроен. `history=false` —
    без писем «из истории» (за последние 3 дня), `true` — только они; `q` — поиск по отправителю и
    теме;
    `type` — только письма этого типа (код справочника «Типы входящих писем»);
    `counts` — числа вкладок в рамках прав сотрудника."""
    return await container.inbound_mail.page(access, view, history, q, type)


@router.get("/inbound-mail/{mail_id}", response_model=InboundMailOut)
async def get_inbound_mail(
    mail_id: MailId, access: Access, container: ContainerDep
) -> InboundMailOut:
    """Карточка письма: отправитель, адресаты (сотрудники по адресу), все письма записи, наши
    ответы, вложения, связка, подсказка помощника, итог и журнал действий."""
    return await container.inbound_mail.get(access, mail_id)


@router.post("/inbound-mail/{mail_id}/read", status_code=204)
async def read_inbound_mail(mail_id: MailId, access: Access, container: ContainerDep) -> Response:
    """Отметить прочитанным этим сотрудником (открыл карточку)."""
    await container.inbound_mail.mark_read(access, mail_id)
    return Response(status_code=204)


@router.get(
    "/inbound-mail/{mail_id}/attachments/{index}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_inbound_mail_attachment(
    mail_id: MailId,
    index: Annotated[int, Path(ge=0, lt=50)],
    access: Access,
    container: ContainerDep,
) -> Response:
    """Файл вложения письма записи (корня или ответа в цепочке); ключ и адрес хранилища наружу не
    уходят."""
    data, name, mime = await container.inbound_mail.attachment(access, mail_id, index)
    headers = {"Content-Disposition": _disposition(name), "Cache-Control": "private, no-store"}
    return Response(data, media_type=mime, headers=headers)


@router.post("/inbound-mail/{mail_id}/assist", response_model=InboundMailAssist)
async def assist_inbound_mail(
    mail_id: MailId, who: Worker, container: ContainerDep
) -> InboundMailAssist:
    """«Подсказать» (решение юриста 2026-11-02 — только по кнопке): тип, суть и предложенное
    действие; в модель — текст без персональных данных, вложения — никогда. Уже есть — она же, без
    второго вызова. Модель недоступна — `status = unavailable` (разберите вручную). Помощник
    выключен админом — 409 `assist_disabled`."""
    return await container.inbound_mail_assist.suggest(who, mail_id)


@router.post("/inbound-mail/{mail_id}/take", status_code=204)
async def take_inbound_mail(
    mail_id: MailId, body: InboundMailTakeIn, who: Worker, container: ContainerDep
) -> Response:
    """«Взять в работу» (повтор своего — без изменений). Ведёт другой — 409
    `mail_in_work_by_other` (`details.assignee_name`, `assigned_at`); `takeover=true` — «Забрать
    себе» у того, кто ведёт (в журнал). Разобрано или подозрительное — 409 `mail_handled`."""
    await container.inbound_mail.take(who, mail_id, body.takeover)
    return Response(status_code=204)


@router.post("/inbound-mail/{mail_id}/release", status_code=204)
async def release_inbound_mail(
    mail_id: MailId, access: Access, container: ContainerDep
) -> Response:
    """«Вернуть в Новые»: своё «в работе» или разобранное архивом/ответом (первая линия; запись в
    журнал). Нельзя — 409 `mail_not_returnable`; ведёт другой — 409 `mail_in_work_by_other`."""
    await container.inbound_mail.release(access, mail_id)
    return Response(status_code=204)


@router.post("/inbound-mail/{mail_id}/registration", status_code=204)
async def registration_inbound_mail(
    mail_id: MailId, body: InboundMailRegistrationIn, who: Worker, container: ContainerDep
) -> Response:
    """Регистрация ВХ из письма начата (`start`: письмо «Регистрируется», берётся автоматически;
    ведёт
    другой — 409 `mail_in_work_by_other`) или EDS отказал (`cancel`: снова «в работе»). Итог
    «Разобрано: ВХ» ставит событие EDS."""
    await container.inbound_mail.registration(who, mail_id, body.state)
    return Response(status_code=204)


@router.post("/inbound-mail/bulk-archive", response_model=InboundMailBulkArchiveOut)
async def bulk_archive_inbound_mail(
    body: InboundMailBulkArchiveIn, who: Worker, container: ContainerDep
) -> InboundMailBulkArchiveOut:
    """«В архив» нескольких писем с одной причиной; чужие «в работе», регистрируемые и уже
    разобранные пропускаются и перечислены в `skipped`."""
    return await container.inbound_mail.bulk_archive(who, body.ids, body.reason)


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


@router.post("/inbound-mail/{mail_id}/not-spam", status_code=204)
async def not_spam_inbound_mail(mail_id: MailId, who: Worker, container: ContainerDep) -> Response:
    """«Не спам → в очередь»: подозрительное письмо становится «Ждёт разбора». Не `spam` — 409."""
    await container.inbound_mail.not_spam(who, mail_id)
    return Response(status_code=204)


@router.post("/inbound-mail/{mail_id}/discard", status_code=204)
async def discard_inbound_mail(mail_id: MailId, who: Worker, container: ContainerDep) -> Response:
    """«Убрать» подозрительное письмо: в архив с причиной «Спам». Не `spam` — 409."""
    await container.inbound_mail.discard(who, mail_id)
    return Response(status_code=204)


@router.post("/inbound-mail/{mail_id}/reply", response_model=InboundMailReply)
async def reply_inbound_mail(
    mail_id: MailId, body: InboundMailReplyIn, access: Access, container: ContainerDep
) -> InboundMailReply:
    """Ответ на последнее письмо записи в ту же цепочку (In-Reply-To, References) почтовым
    сервисом; `reply_all` — копия остальным адресам письма. Письмо берётся в работу и после
    отправки «Разобрано: ответ отправлен», при `awaiting` («Ждём ответа») остаётся «в работе».
    Почта не настроена — 409 `smtp_not_configured`."""
    return await container.inbound_mail.reply(
        access, mail_id, body.text, reply_all=body.reply_all, awaiting=body.awaiting, to=body.to
    )


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
        personal_rule=body.personal_rule,
        personal_label=body.personal_label,
        trusted_auth_servers=body.trusted_auth_servers,
        username=body.username,
        password=secret,
        admin_password=body.password.get_secret_value(),
        folders=body.folders,
    )


@router.post("/integrations/imap/check", response_model=ImapCheckOut)
async def check_imap_connector(_: AdminWriter, container: ContainerDep) -> ImapCheckOut:
    """«Проверить приём»: вход и папка только на чтение, без чтения писем. Итог — в ответе:
    `error_kind` — `not_configured`, `invalid_host`, `unavailable`, `tls_failed`, `auth_failed`,
    `mailbox_missing`."""
    return await container.imap_connector.check()


@router.post("/integrations/imap/folders", response_model=ImapFoldersOut)
async def imap_folders(_: AdminWriter, container: ContainerDep) -> ImapFoldersOut:
    """«Найти папки»: папки ящика (IMAP `LIST`) и подсказка спам-папки по флагу `\\Junk`. Итог —
    в ответе, `error_kind` — как у «Проверить приём»."""
    return await container.imap_connector.folders()


@router.post("/integrations/imap/history", response_model=ImapHistoryOut)
async def start_imap_history(
    body: ImapHistoryIn, who: AdminWriter, container: ContainerDep
) -> ImapHistoryOut:
    """«Загрузить письма за период» (7, 14, 30 или 90 дней) — фоном; ход и итог — в ответе и в
    `GET /integrations/imap` (`history`). Уже идёт — та же загрузка. Дубли по Message-ID не
    создаются. Приём не настроен — 409."""
    return await container.inbound_mail_history.start(who, body.days)
