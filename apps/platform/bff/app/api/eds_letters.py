"""EDS · Входящие письма и резолюция директора (контракт: tag `letters`, 0.16.0; D1-3).

BFF не решает: статусы письма, права `letters.*`, срок расчёта и «кого можно назначить» проверяет
EDS (и бизнес-правила шины ERP). Здесь — доступ к разделу каталога `eds.inbox` (чтение — список и
карточка, полный — резолюция, возврат, отказ), вызовы EDS с токеном доступа EDS (обмен токена
сотрудника CRM `aud=eds`, `app.auth`), данные заявки из ERP по ссылке письма с частичным ответом
`sources`, адресация письма и по id, и по номеру `ВХ-104/26`, перевод ошибок EDS в формат `Error`.

Кандидаты в исполнители — по **разделам каталога**, а не по кодам ролей (CONVENTIONS.md §2 п. 6):
зона «товары» — `erp.calc.goods`, «услуги» — `erp.calc.services`, «условия оплаты» —
`eds.payments`; сотрудников и матрицы ролей BFF читает в CRM (`admin` не ниже чтения). Роли без
доступа к справочнику получают пустой выбор и `directory = forbidden` — разрыв бэкенда записан в
`docs/QUESTIONS.md`.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

import anyio
import httpx
import structlog
from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse
from starlette.types import Send

from app.clients.eds import EdsLetters, eds_error
from app.deps import Authed, require
from app.errors import PlatformError
from app.feeds.feed import Feed
from app.rbac import strip_restricted
from app.rbac_generated import RESOURCE_MODULE
from app.schemas import initials_of
from app.schemas_eds_letters import (
    NUMBER_RE,
    UUID_RE,
    ZONES,
    LetterCard,
    LetterPage,
    LetterRejectIn,
    LetterReturnIn,
    LetterStatus,
    LetterZone,
    ResolutionAssignees,
    ResolutionCandidate,
    ResolutionIn,
    ResolutionZone,
    parse_letter,
    to_card,
    to_page,
)

log = structlog.get_logger()

router = APIRouter(prefix="/eds", tags=["letters"])

Reader = Annotated[Authed, Depends(require("eds.inbox", "read"))]
Resolver = Annotated[Authed, Depends(require("eds.inbox", "full"))]
LetterId = Annotated[uuid.UUID, Path()]

# «Маржа не ниже, %» — группа `cost_margin` (platform-rbac.yaml `restricted_fields`): без неё BFF
# вырезает поле из ответа EDS до разбора.
MARGIN_RULES = {"cost_margin": ("min_margin_pct",)}

# Зона резолюции -> раздел каталога, который делает сотрудника исполнителем зоны (уровень «полный»):
# снабженец — склад и цены поставщиков, гл. инженер — услуги, бухгалтер — условия оплаты.
ZONE_SECTION: dict[LetterZone, str] = {
    "goods": "erp.calc.goods",
    "services": "erp.calc.services",
    "payment_terms": "eds.payments",
}
for _section in ZONE_SECTION.values():
    if _section not in RESOURCE_MODULE:  # раздел убрали из каталога — заметить при запуске
        raise KeyError(f"нет раздела каталога: {_section}")


def _letters(authed: Authed) -> EdsLetters:
    return EdsLetters(authed.call)


async def _card(authed: Authed, raw: Any) -> LetterCard:
    """Карточка из письма EDS + заявка ERP по ссылке письма (ERP не ответил — без заявки)."""
    letter = parse_letter(strip_restricted(raw, authed.fields, MARGIN_RULES))
    feed = Feed(authed)
    deal: dict[str, Any] | None = None
    deal_id = letter.links.erp_deal_id
    if deal_id is not None and feed.usable("erp"):
        try:
            payload = await feed.get("erp", f"/api/v1/crm/deals/{deal_id}/")
        except PlatformError as exc:
            if exc.status_code != 403:  # 401 — конец сессии, остальное — не наш разбор
                raise
            payload = None
        deal = payload if isinstance(payload, dict) else None
    return to_card(
        letter, deal=deal, sources=feed.sources, show_margin="cost_margin" in authed.fields
    )


def _not_found() -> PlatformError:
    return PlatformError(
        "NOT_FOUND",
        "Письмо не найдено.",
        status_code=404,
        source="eds",
        details={"backend_status": 404},
    )


@router.get(
    "/letters",
    response_model=LetterPage,
    response_model_exclude_unset=True,
    operation_id="listLetters",
)
async def list_letters(
    authed: Reader,
    status: Annotated[list[LetterStatus] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LetterPage:
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = list(dict.fromkeys(status))
    if q and q.strip():
        params["q"] = q.strip()
    if cursor:
        params["cursor"] = cursor
    return to_page(await _letters(authed).page(params))


@router.get(
    "/letters/{ref:path}",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="getLetter",
)
async def get_letter(ref: str, authed: Reader) -> LetterCard:
    eds = _letters(authed)
    if UUID_RE.match(ref):
        letter_id: str | None = ref.lower()
    elif NUMBER_RE.match(ref):
        letter_id = await eds.id_by_number(ref)
    else:
        letter_id = None
    if letter_id is None:
        raise _not_found()
    return await _card(authed, await eds.get(letter_id))


@router.post(
    "/letters/{id}/resolution",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="resolveLetter",
)
async def resolve_letter(id: LetterId, body: ResolutionIn, authed: Resolver) -> LetterCard:
    if body.min_margin_pct is not None and "cost_margin" not in authed.fields:
        # Порог маржи — внутренняя экономика: без группы `cost_margin` его не читают и не задают.
        raise PlatformError(
            "VALIDATION_FAILED",
            "Порог маржи задаёт роль с доступом к марже.",
            status_code=422,
            details={"fields": ["min_margin_pct"], "reason": "margin_forbidden"},
        )
    return await _card(authed, await _letters(authed).resolve(str(id), body.for_eds()))


@router.post(
    "/letters/{id}/return",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="returnLetter",
)
async def return_letter(id: LetterId, body: LetterReturnIn, authed: Resolver) -> LetterCard:
    return await _card(authed, await _letters(authed).send_back(str(id), body.comment))


@router.post(
    "/letters/{id}/reject",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="rejectLetter",
)
async def reject_letter(id: LetterId, body: LetterRejectIn, authed: Resolver) -> LetterCard:
    return await _card(authed, await _letters(authed).reject(str(id), body.reason))


# --- кандидаты в исполнители ---------------------------------------------------------------------


async def _directory(
    authed: Authed, path: str
) -> list[dict[str, Any]] | Literal["forbidden", "unavailable"]:
    """Справочник CRM (`/users`, `/platform-roles`): список, либо причина, почему его нет."""
    try:
        response = await authed.call("crm", "GET", path)
    except PlatformError as exc:
        if exc.status_code == 503:
            return "unavailable"
        raise
    if response.status_code == 403:
        return "forbidden"
    if response.status_code != 200:
        log.warning("resolution_directory_failed", path=path, status=response.status_code)
        return "unavailable"
    try:
        body = response.json()
    except ValueError:
        return "unavailable"
    return (
        [row for row in body if isinstance(row, dict)] if isinstance(body, list) else "unavailable"
    )


def _has_full(role_access: dict[str, Any] | None, section: str) -> bool:
    return isinstance(role_access, dict) and role_access.get(section) == "full"


def _candidates(
    users: list[dict[str, Any]], roles: list[dict[str, Any]], author_id: str
) -> list[ResolutionZone]:
    access_by_role = {int(r["id"]): r.get("access") for r in roles if isinstance(r.get("id"), int)}
    zones: list[ResolutionZone] = []
    for zone in ZONES:
        section = ZONE_SECTION[zone]
        found: list[ResolutionCandidate] = []
        for user in users:
            if user.get("is_active") is False or not isinstance(user.get("id"), int):
                continue
            if str(user["id"]) == author_id:
                continue  # автор резолюции не исполнитель собственного задания (по id, не по роли)
            role_ids = user.get("platform_role_ids") or []
            if not any(_has_full(access_by_role.get(rid), section) for rid in role_ids):
                continue
            name = str(user.get("full_name") or "")
            position = user.get("position")
            found.append(
                ResolutionCandidate(
                    id=str(user["id"]),
                    name=name,
                    initials=initials_of(name, str(user.get("email") or "")),
                    position=position if isinstance(position, str) and position else None,
                )
            )
        found.sort(key=lambda c: (c.name.casefold(), c.id))
        zones.append(ResolutionZone(zone=zone, candidates=found))
    return zones


@router.get(
    "/resolution/assignees",
    response_model=ResolutionAssignees,
    operation_id="listResolutionAssignees",
)
async def list_resolution_assignees(authed: Resolver) -> ResolutionAssignees:
    users, roles = await asyncio.gather(
        _directory(authed, "/api/v1/users"), _directory(authed, "/api/v1/platform-roles")
    )
    for failure in (users, roles):
        if isinstance(failure, str):
            return ResolutionAssignees(
                zones=[ResolutionZone(zone=z, candidates=[]) for z in ZONES], directory=failure
            )
    assert not isinstance(users, str)  # noqa: S101 — отказы разобраны выше
    assert not isinstance(roles, str)  # noqa: S101
    zones = _candidates(users, roles, str(authed.data.user_id))
    return ResolutionAssignees(zones=zones, directory="ok")


# --- вложения ------------------------------------------------------------------------------------


async def _relay(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk


class _FileStream(StreamingResponse):
    """Вложение потоком; ответ EDS закрывается всегда (клиент или EDS оборвали загрузку)."""

    def __init__(self, upstream: httpx.Response, headers: dict[str, str]) -> None:
        super().__init__(_relay(upstream), media_type="application/octet-stream", headers=headers)
        self._upstream = upstream

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._upstream.aclose()


_ATTACHMENT = re.compile(r"^attachment(;|$)", re.IGNORECASE)


@router.get(
    "/letter-files/{file_id}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadLetterFile",
)
async def download_letter_file(file_id: uuid.UUID, authed: Reader) -> StreamingResponse:
    response = await _letters(authed).file(str(file_id))
    if response.status_code != 200:
        try:
            await response.aread()
            raise eds_error(response)
        finally:
            await response.aclose()
    disposition = response.headers.get("content-disposition", "")
    return _FileStream(
        response,
        headers={
            # Только вложение: имя и тип не дают браузеру открыть файл как страницу.
            "Content-Disposition": disposition if _ATTACHMENT.match(disposition) else "attachment",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, no-store",
        },
    )
