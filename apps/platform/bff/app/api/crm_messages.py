"""Клиенты · Ждут ответа (D1-1, контракт: tag `messages`, 0.16.0): передачи от бота, переписка,
ответ.

BFF проксирует к CRM с токеном сотрудника и проверяет раздел каталога `crm.leads`: чтение (очередь,
карточка, лента, вложения) — от `read` (директор смотрит без действий), действия (забрать,
ответить, заметка, подсказка, вернуть боту, шаблоны) — `full`. Право на действие над лидом
(владелец, согласие, открытая передача) решает CRM; её отказы переводятся в `Error` с кодом CRM в
`details.reason`.

Ответ клиенту несёт ключ повтора `client_message_id`: CRM не шлёт второе сообщение с тем же ключом,
поэтому «Повторить» безопасно. Telegram не ответил — 502 CRM (`delivery_failed`) → 502
`INTEGRATION_FAILED`. Вложение идёт потоком из CRM с `Content-Disposition: attachment` и `nosniff`;
ключей и адресов хранилища браузер не видит. Живые обновления — подсказка `messages` потока
`/events/stream` (`app/bus.py`).
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any

import anyio
import httpx
from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import StreamingResponse
from starlette.types import Send

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy, crm_error
from app.crm_messages_view import card, inbox_items, team_note, thread_message
from app.deps import Authed, require
from app.errors import PlatformError
from app.feeds.numbers import lead_id_of, lead_number
from app.schemas_bot import ReplyTemplate, ReplyTemplateList
from app.schemas_crm_messages import (
    AssistIn,
    AssistSuggestion,
    ConversationCard,
    ConversationThread,
    MessageInbox,
    ReplyIn,
    ReturnToBotIn,
    SentMessage,
    TeamNoteIn,
)
from app.schemas_integrations import ActionOk
from app.schemas_kb import CreatedId

router = APIRouter(tags=["messages"])

API = "/api/v1"
Reader = Annotated[Authed, Depends(require("crm.leads", "read"))]
Worker = Annotated[Authed, Depends(require("crm.leads", "full"))]
LeadParam = Annotated[str, Path(pattern=r"^[Ll]-?\d{1,9}$")]


def _lead_id(lead: str) -> int:
    found = lead_id_of(lead)
    if found is None:  # шаблон пути уже проверен; на случай расхождения — 404, а не 500
        raise PlatformError("NOT_FOUND", "Лид не найден.", status_code=404)
    return found


def _error(response: httpx.Response) -> PlatformError:
    """Отказ CRM → `Error`; для «лид уже забран» — ещё и кто его забрал (`assigned_user_name`)."""
    error = crm_error(response)
    try:
        name = response.json()["details"]["assigned_user_name"]
    except (ValueError, KeyError, TypeError):
        name = None
    if isinstance(name, str) and name:
        error.body.details = {**(error.body.details or {}), "assigned_user_name": name}
    return error


class _Crm:
    """Вызовы CRM от имени сотрудника; не 2xx — ошибка контракта."""

    def __init__(self, authed: Authed) -> None:
        self.proxy = CrmProxy(authed.call)

    async def json(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, Any] | None = None,
        probe: bool = False,
    ) -> Any:
        response = await self.proxy.raw(method, path, json=body, params=params, probe=probe)
        if response.status_code != 200:
            raise _error(response)
        return response.json() if response.content else None

    async def names(self) -> dict[int, str]:
        """Имена менеджеров (`GET /team`, `leads:read`); сбой — без имён, экран покажет «#id»."""
        try:
            rows = await self.proxy.get_list(crm.TeamMember, f"{API}/team")
        except PlatformError:
            return {}
        return {row.id: row.full_name for row in rows}

    async def products(self, keys: list[str]) -> dict[str, str]:
        """Названия продуктов (`GET /kb/products`, `kb:read`); без ключей — без запроса."""
        if not keys:
            return {}
        try:
            rows = await self.proxy.get_list(crm.ProductOut, f"{API}/kb/products")
        except PlatformError:
            return {}
        return {row.key: row.name for row in rows}


@router.get("/crm/messages", response_model=MessageInbox, operation_id="listCrmMessages")
async def list_messages(authed: Reader) -> MessageInbox:
    api = _Crm(authed)
    raw, names = await asyncio.gather(api.json("GET", f"{API}/inbox"), api.names())
    inbox = crm.InboxResponse.model_validate(raw)
    return MessageInbox(items=inbox_items(inbox, names))


@router.get(
    "/crm/messages/{lead}", response_model=ConversationCard, operation_id="getCrmConversation"
)
async def get_conversation(lead: LeadParam, authed: Reader) -> ConversationCard:
    api = _Crm(authed)
    raw, names = await asyncio.gather(api.json("GET", f"{API}/leads/{_lead_id(lead)}"), api.names())
    detail = crm.LeadDetail.model_validate(raw)
    products = await api.products(list(detail.product_interest))
    return card(detail, names, products)


@router.get(
    "/crm/messages/{lead}/thread", response_model=ConversationThread, operation_id="getCrmThread"
)
async def get_thread(
    lead: LeadParam,
    authed: Reader,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConversationThread:
    lead_id = _lead_id(lead)
    number = lead_number(lead_id)
    api = _Crm(authed)
    params: dict[str, Any] = {"limit": limit}
    if before is not None:
        params["before_id"] = before
    messages_raw, names = await asyncio.gather(
        api.json("GET", f"{API}/leads/{lead_id}/messages", params=params), api.names()
    )
    rows = [crm.MessageOut.model_validate(m) for m in messages_raw or []]
    notes: list[crm.NoteOut] = []
    if before is None:
        notes = [
            crm.NoteOut.model_validate(n)
            for n in await api.json("GET", f"{API}/leads/{lead_id}/notes") or []
        ]
    return ConversationThread(
        items=[thread_message(number, m, names) for m in rows],
        notes=[team_note(n, names) for n in notes],
        has_more=len(rows) >= limit,
    )


class FileStream(StreamingResponse):
    """Файл вложения потоком; ответ CRM закрывается всегда (как выгрузка CSV, W13-A5)."""

    def __init__(self, upstream: httpx.Response, headers: dict[str, str]) -> None:
        media = upstream.headers.get("content-type", "application/octet-stream")
        super().__init__(self._relay(upstream), media_type=media, headers=headers)
        self._upstream = upstream

    @staticmethod
    async def _relay(response: httpx.Response) -> AsyncIterator[bytes]:
        async for chunk in response.aiter_bytes():
            yield chunk

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._upstream.aclose()


@router.get(
    "/crm/messages/{lead}/attachments/{message}/{index}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadCrmAttachment",
)
async def download_attachment(
    lead: LeadParam,
    message: Annotated[int, Path(ge=1)],
    index: Annotated[int, Path(ge=0, le=19)],
    authed: Reader,
) -> StreamingResponse:
    path = f"{API}/leads/{_lead_id(lead)}/messages/{message}/attachments/{index}"
    response = await CrmProxy(authed.call).raw("GET", path, stream=True)
    if response.status_code != 200:
        try:
            await response.aread()
            raise _error(response)
        finally:
            await response.aclose()
    headers = {
        "Content-Disposition": response.headers.get("content-disposition", "attachment"),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers)


@router.post("/crm/messages/{lead}/take", response_model=ActionOk, operation_id="takeCrmLead")
async def take(lead: LeadParam, authed: Worker) -> ActionOk:
    await _Crm(authed).json("POST", f"{API}/leads/{_lead_id(lead)}/actions/take")
    return ActionOk(id=None, ok=True)


@router.post("/crm/messages/{lead}/reply", response_model=SentMessage, operation_id="replyCrmLead")
async def reply(lead: LeadParam, body: ReplyIn, authed: Worker) -> SentMessage:
    # Отправка ждёт Telegram: таймаут пробы, 502 CRM (`delivery_failed`) — итог, а не сбой CRM.
    out = await _Crm(authed).json(
        "POST", f"{API}/leads/{_lead_id(lead)}/messages", body=body.model_dump(), probe=True
    )
    return SentMessage(id=crm.ActionResult.model_validate(out).id or 0)


@router.post(
    "/crm/messages/{lead}/note",
    response_model=CreatedId,
    status_code=status.HTTP_201_CREATED,
    operation_id="noteCrmLead",
)
async def note(lead: LeadParam, body: TeamNoteIn, authed: Worker) -> CreatedId:
    out = await _Crm(authed).json(
        "POST",
        f"{API}/leads/{_lead_id(lead)}/actions/note",
        body={"text": body.text, "visible_to_bot": False},
    )
    return CreatedId(id=crm.ActionResult.model_validate(out).id or 0)


@router.post(
    "/crm/messages/{lead}/assist", response_model=AssistSuggestion, operation_id="assistCrmReply"
)
async def assist(lead: LeadParam, body: AssistIn, authed: Worker) -> AssistSuggestion:
    out = await _Crm(authed).json(
        "POST", f"{API}/leads/{_lead_id(lead)}/assist", body=body.model_dump(), probe=True
    )
    suggestion = crm.AssistOut.model_validate(out)
    notice = suggestion.notice.value if suggestion.notice is not None else None
    return AssistSuggestion(text=suggestion.text, notice=notice)


@router.post(
    "/crm/messages/{lead}/return-to-bot",
    response_model=ActionOk,
    operation_id="returnCrmLeadToBot",
)
async def return_to_bot(
    lead: LeadParam, authed: Worker, body: ReturnToBotIn | None = None
) -> ActionOk:
    await _Crm(authed).json(
        "POST",
        f"{API}/leads/{_lead_id(lead)}/actions/return_to_bot",
        body={"note": body.note if body else None},
    )
    return ActionOk(id=None, ok=True)


@router.get(
    "/crm/reply-templates", response_model=ReplyTemplateList, operation_id="listCrmReplyTemplates"
)
async def list_templates(authed: Worker) -> ReplyTemplateList:
    rows = await CrmProxy(authed.call).get_list(crm.ReplyTemplateOut, f"{API}/reply-templates")
    return ReplyTemplateList(
        items=[ReplyTemplate.model_validate(r.model_dump(mode="json")) for r in rows]
    )
