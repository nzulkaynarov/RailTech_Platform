"""EDS · Входящие письма и резолюция директора (контракт: tag `letters`, 0.16.0; D1-3).

BFF не решает: статусы письма, права `letters.*`, срок расчёта и «кого можно назначить» проверяет
EDS (и бизнес-правила шины ERP). Здесь — доступ к разделу каталога `eds.inbox` (чтение — список и
карточка, полный — резолюция, возврат, отказ), вызовы EDS с токеном доступа EDS (обмен токена
сотрудника CRM `aud=eds`, `app.auth`), данные заявки из ERP по ссылке письма с частичным ответом
`sources`, адресация письма и по id, и по номеру `ВХ-104/26`, перевод ошибок EDS в формат `Error`.

Кандидаты в исполнители — по **разделам каталога**, а не по кодам ролей (CONVENTIONS.md §2 п. 6):
зона «товары» — `erp.calc.goods`, «услуги» — `erp.calc.services`, «условия оплаты» —
`eds.payments`. Выбор делает CRM (`GET /team?section=&level=full`, D1-8, B-007): он владеет людьми и
матрицами ролей; BFF матрицы не сводит. Право на операцию — чтение сотрудников (`admin` не ниже
чтения): без него выбор пуст и `directory = forbidden`. Зону исполнителя проверяет и EDS при
резолюции (`assignee_zone_mismatch`).
"""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

import anyio
import httpx
import structlog
from fastapi import APIRouter, Depends, Header, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.types import Send

from app.api.inbound_mail import mail_registration
from app.clients.eds import EdsLetters, eds_error
from app.deps import Authed, require, require_any, require_any_section
from app.errors import PlatformError, backend_unavailable
from app.feeds.feed import Feed
from app.rbac import strip_restricted
from app.rbac_generated import RESOURCE_MODULE
from app.schemas_eds_letters import (
    NUMBER_RE,
    UUID_RE,
    ZONES,
    EdsStaffList,
    EdsStaffMember,
    InstructionCompleteIn,
    InstructionExtensionDecisionIn,
    InstructionExtensionIn,
    LetterCard,
    LetterDuplicate,
    LetterDuplicateList,
    LetterKindList,
    LetterPage,
    LetterRegisterIn,
    LetterRejectIn,
    LetterReturnIn,
    LetterStatus,
    LetterZone,
    OfficeResolutionIn,
    ResolutionAssignees,
    ResolutionCandidate,
    ResolutionDraftIn,
    ResolutionIn,
    ResolutionZone,
    letter_path,
    parse_letter,
    to_card,
    to_page,
)

log = structlog.get_logger()

router = APIRouter(prefix="/eds", tags=["letters"])

# P8: регистрация (`eds.inbox.register`) отдельно от резолюции (`eds.inbox: full`); читать письма
# может и тот, у кого только регистрация (как пункт меню `inbox` каталога).
Reader = Annotated[
    Authed, Depends(require_any(("eds.inbox", "read"), ("eds.inbox.register", "full")))
]
Registrar = Annotated[Authed, Depends(require("eds.inbox.register", "full"))]
Resolver = Annotated[Authed, Depends(require("eds.inbox", "full"))]
# P8b: проект резолюции и выбор сотрудников — делопроизводителю и директору.
Drafter = Annotated[
    Authed, Depends(require_any(("eds.inbox.register", "full"), ("eds.inbox", "full")))
]
# P8b (SPEC-v3 §3.2a «Права»): карточку письма, его файлы и действия по поручению получает и
# исполнитель без `eds.inbox` — решает EDS (участник поручения, «ознакомить», автор резолюции).
Participant = Annotated[Authed, Depends(require_any_section)]
LetterId = Annotated[uuid.UUID, Path()]
InstructionId = Annotated[uuid.UUID, Path()]

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
    on_control: Annotated[bool | None, Query()] = None,
    overdue: Annotated[bool | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LetterPage:
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = list(dict.fromkeys(status))
    if q and q.strip():
        params["q"] = q.strip()
    # P8b: фильтры журнала «На контроле» и «Просрочено»
    if on_control is not None:
        params["on_control"] = "true" if on_control else "false"
    if overdue is not None:
        params["overdue"] = "true" if overdue else "false"
    if cursor:
        params["cursor"] = cursor
    return to_page(await _letters(authed).page(params))


@router.post(
    "/letters",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    status_code=201,
    operation_id="registerLetter",
)
async def register_letter(
    body: LetterRegisterIn,
    authed: Registrar,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> LetterCard:
    """«Зарегистрировать входящее» (P8, SPEC-v3 §3.2a): ВХ, «Ждёт резолюции», строка директору.

    Из очереди «Входящая почта» (W18A-P2, `source_mail_id`): сначала CRM помечает письмо
    «Регистрируется» и берёт его для этого сотрудника — письмо уже разобрано или в работе у другого,
    409 до EDS, второго ВХ нет (W18A-P2-3); отказ EDS возвращает письмо «в работе». «Разобрано: ВХ»
    ставит событие `letter.registered`."""
    mail_id = body.source_mail_id
    if mail_id is not None:
        await mail_registration(authed, mail_id, "start")
    try:
        raw = await _letters(authed).register(body.for_eds(), idempotency_key)
    except BaseException:
        if mail_id is not None:
            await mail_registration(authed, mail_id, "cancel", quiet=True)
        raise
    return await _card(authed, raw)


@router.get("/letter-kinds", response_model=LetterKindList, operation_id="listLetterKinds")
async def list_letter_kinds(authed: Reader) -> LetterKindList:
    raw = await _letters(authed).kinds()
    try:
        return LetterKindList.model_validate(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_kinds") from exc


@router.get(
    "/letter-duplicates", response_model=LetterDuplicateList, operation_id="findLetterDuplicates"
)
async def find_letter_duplicates(
    authed: Reader,
    ref_number: Annotated[str, Query(min_length=1, max_length=64)],
    sender_name: Annotated[str | None, Query(max_length=255)] = None,
    crm_client_id: Annotated[int | None, Query(ge=1)] = None,
) -> LetterDuplicateList:
    params: dict[str, Any] = {"ref_number": ref_number.strip() or ref_number}
    if sender_name and sender_name.strip():
        params["sender_name"] = sender_name.strip()
    if crm_client_id is not None:
        params["crm_client_id"] = crm_client_id
    raw = await _letters(authed).duplicates(params)
    items = raw.get("items") if isinstance(raw, dict) else None
    found: list[LetterDuplicate] = []
    for item in items if isinstance(items, list) else []:
        try:
            found.append(
                LetterDuplicate.model_validate(
                    {**item, "path": letter_path(str(item.get("number", "")))}
                )
            )
        except (ValidationError, AttributeError) as exc:
            raise backend_unavailable("eds", "bad_duplicates") from exc
    return LetterDuplicateList(items=found)


@router.get(
    "/letters/{ref:path}",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="getLetter",
)
async def get_letter(ref: str, authed: Participant) -> LetterCard:
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


# --- P8b: резолюция делопроизводства, поручения, ознакомление ------------------------------------


@router.put(
    "/letters/{id}/resolution-draft",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="saveResolutionDraft",
)
async def save_resolution_draft(
    id: LetterId, body: ResolutionDraftIn, authed: Drafter
) -> LetterCard:
    return await _card(authed, await _letters(authed).save_draft(str(id), body.for_eds()))


@router.post(
    "/letters/{id}/office-resolution",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="resolveOfficeLetter",
)
async def resolve_office_letter(
    id: LetterId, body: OfficeResolutionIn, authed: Resolver
) -> LetterCard:
    return await _card(authed, await _letters(authed).resolve_office(str(id), body.for_eds()))


@router.post(
    "/letters/{id}/acquaint",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="acknowledgeLetter",
)
async def acknowledge_letter(id: LetterId, authed: Participant) -> LetterCard:
    return await _card(authed, await _letters(authed).acknowledge(str(id)))


@router.post(
    "/instructions/{id}/complete",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="completeInstruction",
)
async def complete_instruction(
    id: InstructionId, body: InstructionCompleteIn, authed: Participant
) -> LetterCard:
    return await _card(authed, await _letters(authed).complete(str(id), body.for_eds()))


@router.post(
    "/instructions/{id}/extension",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="requestInstructionExtension",
)
async def request_instruction_extension(
    id: InstructionId, body: InstructionExtensionIn, authed: Participant
) -> LetterCard:
    raw = await _letters(authed).request_extension(str(id), body.for_eds())
    return await _card(authed, raw)


@router.post(
    "/instructions/{id}/extension/decision",
    response_model=LetterCard,
    response_model_exclude_unset=True,
    operation_id="decideInstructionExtension",
)
async def decide_instruction_extension(
    id: InstructionId, body: InstructionExtensionDecisionIn, authed: Resolver
) -> LetterCard:
    raw = await _letters(authed).decide_extension(str(id), body.for_eds())
    return await _card(authed, raw)


@router.get("/staff", response_model=EdsStaffList, operation_id="listEdsStaff")
async def list_eds_staff(authed: Drafter) -> EdsStaffList:
    """Активные сотрудники EDS: адресат, исполнитель, «ознакомить» (P8b)."""
    raw = await _letters(authed).employees()
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise backend_unavailable("eds", "bad_employees")
    found: list[EdsStaffMember] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("crm_user_id"), int):
            continue
        name = item.get("full_name")
        position = item.get("position")
        found.append(
            EdsStaffMember(
                id=str(item["crm_user_id"]),
                name=name if isinstance(name, str) and name else f"№{item['crm_user_id']}",
                position=position if isinstance(position, str) and position else None,
            )
        )
    found.sort(key=lambda m: (m.name.casefold(), m.id))
    return EdsStaffList(items=found)


# --- кандидаты в исполнители ---------------------------------------------------------------------


async def _zone_team(
    authed: Authed, zone: LetterZone
) -> list[dict[str, Any]] | Literal["forbidden", "unavailable"]:
    """Сотрудники зоны из CRM (`GET /team?section=&level=full`): список или причина отказа."""
    try:
        response = await authed.call(
            "crm", "GET", "/api/v1/team", params={"section": ZONE_SECTION[zone], "level": "full"}
        )
    except PlatformError as exc:
        if exc.status_code == 503:
            return "unavailable"
        raise
    if response.status_code == 403:
        return "forbidden"
    if response.status_code != 200:
        log.warning("resolution_team_failed", zone=zone, status=response.status_code)
        return "unavailable"
    try:
        body = response.json()
    except ValueError:
        return "unavailable"
    return (
        [row for row in body if isinstance(row, dict)] if isinstance(body, list) else "unavailable"
    )


def _candidates(team: list[dict[str, Any]], author_id: str) -> list[ResolutionCandidate]:
    found: list[ResolutionCandidate] = []
    for member in team:
        if not isinstance(member.get("id"), int) or str(member["id"]) == author_id:
            continue  # автор резолюции не исполнитель собственного задания (по id, не по роли)
        name = str(member.get("full_name") or "")
        position = member.get("position")
        initials = member.get("initials")  # считает CRM (`GET /team`), BFF своих не выдумывает
        found.append(
            ResolutionCandidate(
                id=str(member["id"]),
                name=name,
                initials=initials if isinstance(initials, str) else "",
                position=position if isinstance(position, str) and position else None,
            )
        )
    found.sort(key=lambda c: (c.name.casefold(), c.id))
    return found


@router.get(
    "/resolution/assignees",
    response_model=ResolutionAssignees,
    operation_id="listResolutionAssignees",
)
async def list_resolution_assignees(authed: Resolver) -> ResolutionAssignees:
    teams = await asyncio.gather(*(_zone_team(authed, zone) for zone in ZONES))
    for failure in teams:
        if isinstance(failure, str):
            return ResolutionAssignees(
                zones=[ResolutionZone(zone=z, candidates=[]) for z in ZONES], directory=failure
            )
    author = str(authed.data.user_id)
    zones = [
        ResolutionZone(zone=zone, candidates=_candidates(team, author))
        for zone, team in zip(ZONES, teams, strict=True)
        if not isinstance(team, str)
    ]
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
async def download_letter_file(file_id: uuid.UUID, authed: Participant) -> StreamingResponse:
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
