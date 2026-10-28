"""EDS · Проекты (контракт BFF 0.26.0, тег `eds-projects`; D2-5): вызовы ERP и сборка экранов.

BFF не решает: проект, его шаг, статус для клиента, «проблемы», история и действия, доступные
сотруднику, приходят из ERP (`GET /crm/projects/`), а право на действие (`contract.manage`,
`contract.sign`, `fulfillment.act`), допустимый переход статуса договора и акта, тип и размер скана
проверяет ERP. Здесь — разделы каталога (`eds.projects`: чтение и полный), адресация по номеру ПР
или id сделки, **идентификатор документа берётся из карточки проекта, а не из запроса** (чужой
договор по подставленному id не тронуть), номера ПР и ЗВ (у сделки в ERP их нет — B-010), перевод
ошибок ERP в формат `Error` и потоковая выдача файлов.
"""

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.errors import PlatformError, backend_code, backend_unavailable
from app.feeds.text import parse_dt
from app.schemas_eds_projects import (
    ActActionIn,
    ContractActionIn,
    ProjectCard,
    ProjectPage,
    ProjectRow,
    RawCard,
    RawPage,
    RawRow,
    parse,
)

Call = Callable[..., Awaitable[httpx.Response]]

API = "/api/v1/crm"
# Номер проекта или заявки: `ПР-2026-104`, `ЗВ-2026-104`; латиницей (раскладка) — `PR-`, `ZV-`.
_NUMBER = re.compile(r"^(?:ПР|ЗВ|PR|ZV)-(\d{4})-(\d{1,9})$", re.IGNORECASE)
MAX_ID = 2**31 - 1

# Код отказа ERP -> текст для сотрудника. Остальное переводит `project_error` по статусу.
_ERP_REASONS: dict[str, str] = {
    "CONTRACT_TRANSITION_NOT_ALLOWED": "Договор сейчас в другом статусе. Обновите страницу.",
    "ACT_SIGN_NOT_ALLOWED": "Акт сейчас в другом статусе. Обновите страницу.",
    "ACT_ALREADY_EXISTS": "Акт по этому счёту уже есть.",
    "ACT_AWAITING_REISSUE": "Акт возвращён заказчиком: выпустите его заново.",
    "ACT_INVALID_INVOICE_STATUS": "Акт можно выпустить по выставленному счёту.",
    "CONTRACT_NEEDS_APPROVAL": "Проект договора можно сформировать только из принятого КП.",
}
_FIELD_OF: dict[str, str] = {
    "REASON_REQUIRED": "reason",
    "SCAN_REQUIRED": "file",
    "SCAN_INVALID": "file",
    "NO_FILE_PROVIDED": "file",
}


def _year(created_at: Any) -> int:
    """Год создания сделки по UTC — так же, как у `feeds.numbers.deal_number`."""
    moment = (
        created_at.astimezone(UTC) if isinstance(created_at, datetime) else parse_dt(created_at)
    )
    return moment.year if moment else 0


def project_number(deal_id: int, created_at: Any) -> str:
    """Номер проекта `ПР-2026-104`. **Временно, до ERP-09** (`Deal.number`): год и id сделки."""
    return f"ПР-{_year(created_at):04d}-{deal_id:03d}"


def request_number(deal_id: int, created_at: Any) -> str:
    return f"ЗВ-{_year(created_at):04d}-{deal_id:03d}"


def not_found() -> PlatformError:
    return PlatformError(
        "NOT_FOUND",
        "Проект не найден.",
        status_code=404,
        source="erp",
        details={"backend_status": 404},
    )


def parse_ref(ref: str) -> tuple[int, int | None]:
    """Адрес проекта -> (id сделки, год из номера или None); год сверяется с карточкой ERP."""
    text = ref.strip()
    if text.isdigit() and int(text) <= MAX_ID:
        return int(text), None
    match = _NUMBER.match(text)
    if match is None or int(match.group(2)) > MAX_ID:
        raise not_found()
    return int(match.group(2)), int(match.group(1))


def deal_id_of_number(text: str) -> int | None:
    """Id сделки из номера `ПР-2026-104` / `ЗВ-2026-104` (для поиска); голые цифры — не номер."""
    match = _NUMBER.match(text.strip())
    return int(match.group(2)) if match and int(match.group(2)) <= MAX_ID else None


def project_error(response: httpx.Response) -> PlatformError:
    """Ответ ERP 4xx -> ошибка контракта (`source = erp`): 400 -> 422 с полем, 409 -> `CONFLICT`."""
    code = backend_code(response)
    status = response.status_code
    details: dict[str, Any] = {"backend_status": status}
    if code:
        details["backend_code"] = code
    reason = code.split(":", 1)[0] if code else None
    if reason:
        details["reason"] = reason.lower()
    if status in (400, 422):
        if reason in _FIELD_OF:
            details["fields"] = [_FIELD_OF[reason]]
        return PlatformError(
            "VALIDATION_FAILED",
            _ERP_REASONS.get(reason or "", "Проверьте заполнение полей."),
            status_code=422,
            source="erp",
            details=details,
        )
    if status == 403:
        return PlatformError(
            "FORBIDDEN",
            "Действие не положено вашей роли.",
            status_code=403,
            source="erp",
            details=details,
        )
    if status == 404:
        return PlatformError(
            "NOT_FOUND", "Не найдено.", status_code=404, source="erp", details=details
        )
    if status == 409:
        return PlatformError(
            "CONFLICT",
            _ERP_REASONS.get(reason or "", "Объект изменился. Обновите страницу."),
            status_code=409,
            source="erp",
            details=details,
        )
    return backend_unavailable("erp", f"HTTP {status}")


class ErpProjects:
    """Проекты ERP от имени сотрудника (токен ERP из сессии)."""

    def __init__(self, call: Call) -> None:
        self._call = call

    async def _json(self, method: str, path: str, ok: tuple[int, ...] = (200,), **kw: Any) -> Any:
        response = await self._call("erp", method, path, **kw)
        if response.status_code not in ok:
            raise project_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise backend_unavailable("erp", "bad_response") from exc

    async def page(self, params: dict[str, Any]) -> ProjectPage:
        raw = parse(RawPage, await self._json("GET", f"{API}/projects/", params=params), "projects")
        limit = int(params.get("limit", 25))
        offset = int(params.get("offset", 0))
        return ProjectPage(
            items=[row(r) for r in raw.results], total=raw.count, offset=offset, limit=limit
        )

    async def raw_card(self, ref: str) -> RawCard:
        deal_id, year = parse_ref(ref)
        response = await self._call("erp", "GET", f"{API}/projects/{deal_id}/")
        if response.status_code == 404:
            raise not_found()
        if response.status_code != 200:
            raise project_error(response)
        try:
            card = parse(RawCard, response.json(), "project")
        except ValueError as exc:
            raise backend_unavailable("erp", "bad_response") from exc
        if year is not None and _year(card.created_at) != year:
            raise not_found()  # номер называет год, которого у этой сделки нет
        return card

    async def card(self, ref: str) -> ProjectCard:
        return present(await self.raw_card(ref))

    # --- действия: id документа — только из карточки проекта -------------------------------

    async def create_contract(self, ref: str) -> ProjectCard:
        card = await self.raw_card(ref)
        if card.contract is not None:
            raise PlatformError(
                "CONFLICT",
                "Проект договора уже сформирован.",
                status_code=409,
                source="erp",
                details={"reason": "contract_exists"},
            )
        quote = card.quote
        if quote is None or not card.can_create_contract:
            raise PlatformError(
                "FORBIDDEN",
                "Сформировать проект договора может бухгалтер или директор по принятому КП.",
                status_code=403,
                source="erp",
                details={"reason": "contract_create_not_allowed"},
            )
        await self._json(
            "POST",
            f"{API}/contracts/generate-from-quote/",
            ok=(201,),
            json={"quote_id": quote.id, "send_to_client": False},
        )
        return await self.card(ref)

    async def contract_action(self, ref: str, body: ContractActionIn) -> ProjectCard:
        card = await self.raw_card(ref)
        if card.contract is None:
            raise not_found()
        slug = body.action.replace("_", "-")
        payload = {
            k: v.strip()
            for k, v in (("reason", body.reason), ("note", body.note))
            if v and v.strip()
        }
        await self._json("POST", f"{API}/contracts/{card.contract.id}/{slug}/", json=payload)
        return await self.card(ref)

    async def contract_scan(self, ref: str, content: bytes, content_type: str) -> ProjectCard:
        card = await self.raw_card(ref)
        if card.contract is None:
            raise not_found()
        await self._json(
            "POST",
            f"{API}/contracts/{card.contract.id}/attach-scan/",
            content=content,
            content_type=content_type,
        )
        return await self.card(ref)

    async def act_action(self, ref: str, body: ActActionIn) -> ProjectCard:
        card = await self.raw_card(ref)
        if body.action == "issue":
            await self._issue_act(card)
        else:
            if card.act is None:
                raise not_found()
            if body.action == "return":
                payload = {"reason": (body.reason or "").strip()}
                await self._json("POST", f"{API}/acts/{card.act.id}/record-return/", json=payload)
            else:
                await self._json("POST", f"{API}/acts/{card.act.id}/reissue/")
        return await self.card(ref)

    async def _issue_act(self, card: RawCard) -> None:
        """Акт выпускается по самому свежему выставленному счёту проекта (статус и право — ERP)."""
        if card.act_blocker == "forbidden":
            raise PlatformError(
                "FORBIDDEN",
                "Выпустить акт может бухгалтер или директор.",
                status_code=403,
                source="erp",
                details={"reason": "act_issue_not_allowed"},
            )
        if card.act_blocker == "act_exists":
            raise PlatformError(
                "CONFLICT",
                "Акт по этому проекту уже есть.",
                status_code=409,
                source="erp",
                details={"reason": "act_already_exists"},
            )
        issuable = [
            i for i in card.invoices if i.status in ("issued", "partial", "paid", "overdue")
        ]
        if not issuable:
            raise PlatformError(
                "CONFLICT",
                "Акт можно выпустить по выставленному счёту: счёта пока нет.",
                status_code=409,
                source="erp",
                details={"reason": "no_invoice"},
            )
        invoice = max(issuable, key=lambda i: i.id)
        await self._json("POST", f"{API}/invoices/{invoice.id}/generate-act/", ok=(201,))

    async def act_scan(self, ref: str, content: bytes, content_type: str) -> ProjectCard:
        card = await self.raw_card(ref)
        if card.act is None:
            raise not_found()
        await self._json(
            "POST",
            f"{API}/acts/{card.act.id}/attach-scan/",
            content=content,
            content_type=content_type,
        )
        return await self.card(ref)

    async def file_path(self, ref: str, kind: str, doc_id: int, variant: str) -> str:
        """Путь файла в ERP: документ обязан быть в карточке этого проекта."""
        card = await self.raw_card(ref)
        if kind == "contract" and card.contract is not None and card.contract.id == doc_id:
            ok = variant == "pdf" or card.contract.has_scan
            tail = "download-pdf" if variant == "pdf" else "download-signed"
            base = "contracts"
        elif kind == "act" and card.act is not None and card.act.id == doc_id:
            ok = variant == "pdf" or card.act.has_scan
            tail = "download-pdf" if variant == "pdf" else "download-signed"
            base = "acts"
        elif kind == "invoice" and variant == "pdf" and any(i.id == doc_id for i in card.invoices):
            ok, tail, base = True, "download-pdf", "invoices"
        else:
            raise not_found()
        if not ok:
            raise not_found()
        return f"{API}/{base}/{doc_id}/{tail}/"


# --- сборка ответов -------------------------------------------------------------------------------


def row(raw: RawRow) -> ProjectRow:
    return ProjectRow(
        number=project_number(raw.deal_id, raw.created_at),
        request_number=request_number(raw.deal_id, raw.created_at),
        title=raw.title or raw.company_name or project_number(raw.deal_id, raw.created_at),
        client_name=raw.company_name,
        step=raw.step,
        client_status=raw.client_status,
        total=raw.total,
        due_date=raw.due_date,
        manager=raw.manager,
        responsible=raw.responsible,
        documents=raw.documents,
        problems=raw.problems,
        created_at=raw.created_at,
    )


def present(raw: RawCard) -> ProjectCard:
    base = row(raw).model_dump()
    return ProjectCard(
        **base,
        quote=raw.quote,
        contract=raw.contract,
        can_create_contract=raw.can_create_contract,
        invoices=raw.invoices,
        act=raw.act,
        act_blocker=raw.act_blocker,
        fulfillment=raw.fulfillment,
        delivery_lines=raw.delivery_lines,
        journal=raw.journal,
    )
