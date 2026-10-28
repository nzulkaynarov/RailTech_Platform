"""Расчёт · Заявки в расчёте и расчёт по заявке (контракт: tag `calc`, 0.26.0; D2-1, SPEC-v3 §7.4).

BFF не решает (CONVENTIONS.md §2 п. 2): зону строки, визы, «Расчёт готов» (только со всеми визами),
правку закупки и цены решает ERP (`/api/v1/calc/*`, права `quote.visa_goods`, `quote.visa_services`,
`quote.build`). Здесь — доступ к разделам каталога (чтение — `erp.calc`; начать, «Расчёт готов»,
ИИ-разбор — `erp.calc` полный; строки — `erp.calc.goods` или `erp.calc.services` полный), адресация
заявки по номеру ЗВ/ПР (номер выдаёт ERP, `Deal.number`; заявка ищется отбором `?number=` среди
заявок с заданием расчёта, `id` из номера не разбирается), вырезание полей с ограничением и перевод
ошибок ERP.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query, status

from app.clients.erp_company import ErpCompany, erp_error
from app.deps import Authed, require, require_any
from app.errors import PlatformError
from app.feeds.numbers import deal_number, number_query
from app.schemas_erp_calc import (
    CalcCatalogItem,
    CalcCatalogPage,
    CalcLinePatch,
    CalcLinesIn,
    CalcParseIn,
    CalcParseJob,
    CalcParseResult,
    CalcProposalLine,
    CalcRequestList,
    CalcSheet,
    to_row,
    to_sheet,
    zones_of,
)

router = APIRouter(prefix="/erp", tags=["calc"])

Reader = Annotated[Authed, Depends(require("erp.calc", "read"))]
Builder = Annotated[Authed, Depends(require("erp.calc", "full"))]
ZoneHolder = Annotated[
    Authed, Depends(require_any(("erp.calc.goods", "full"), ("erp.calc.services", "full")))
]
Number = Annotated[str, Path(min_length=1, max_length=40)]
LineId = Annotated[str, Path(pattern=r"^[0-9]+$", max_length=12)]

ZONE_SECTION = {"goods": "erp.calc.goods", "service": "erp.calc.services"}
# Отказ правила строки ERP (400) -> поле контракта (`details.fields`).
_FIELD_OF = {
    "CLIENT_PRICE_BELOW_COST": "client_price",
    "MARKUP_OUT_OF_RANGE": "client_price",
    "SERVICE_COST_FROM_CREW": "purchase_price",
    "GOODS_HAVE_NO_CREW": "crew_rate",
    "NAME_REQUIRED": "name",
    "PRODUCT_NOT_FOUND": "product_id",
    "BAD_CURRENCY": "purchase_currency",
    "KIND_FROM_CATALOG": "kind",
}
_MESSAGES = {
    "VISAS_MISSING": (
        "Не все строки подтверждены: «Расчёт готов» станет доступна после виз всех строк."
    ),
    "QUOTE_NOT_DRAFT": (
        "Расчёт уже у директора: строки не правятся, пока он не вернёт КП на доработку."
    ),
    "QUOTE_FROZEN": "КП уже отправлено клиенту: строки не правятся.",
    "LINE_INCOMPLETE": "Сначала заполните закупку и цену клиенту.",
    "PURCHASE_REQUIRED": "Сначала укажите закупку: от неё считается наценка.",
    "CALC_NOT_STARTED": "Расчёт ещё не начат.",
    "DEAL_NOT_IN_CALCULATION": (
        "Заявка закрыта или ушла дальше расчёта: КП директору отсюда не отправить."
    ),
    "AI_DISABLED": "ИИ-разбор выключен в настройках моделей. Добавьте строки вручную.",
    "REQUEST_TEXT_EMPTY": "В заявке нет текста для разбора. Вставьте текст в поле.",
}


def _other_prefix(number: str) -> tuple[str, ...]:
    """`ЗВ-2026-104` ↔ `ПР-2026-104`: заявка и проект с одним NNN (SPEC-v3 §2.2)."""
    for one, other in (("ЗВ-", "ПР-"), ("ПР-", "ЗВ-")):
        if number.startswith(one):
            return (other + number[len(one) :],)
    return ()


class ErpCalc(ErpCompany):
    """Вызовы `/api/v1/calc/*` от имени сотрудника и поиск заявки по номеру ЗВ."""

    async def deal_id(self, number: str) -> int:
        """Заявка по номеру ЗВ/ПР: лёгкий справочник ERP `GET /calc/deals/?number=` (id, номер,
        создана, стадия — без строк и виз). Номер выдаёт ERP (`Deal.number`, ERP-09); `id` из
        номера не разбирается. После принятия КП заявка — проект с тем же NNN: `ЗВ-…` находит и
        `ПР-…`."""
        canonical = number_query(number) or number
        wanted = {number, canonical, *_other_prefix(canonical)}
        data = await self.data("GET", "calc/deals/", params={"number": canonical})
        for deal in data.get("results", []) if isinstance(data, dict) else []:
            if isinstance(deal, dict) and deal_number(deal) in wanted:
                return int(deal["id"])
        raise PlatformError(
            "NOT_FOUND",
            "Заявки нет среди заявок с заданием расчёта.",
            status_code=404,
            source="erp",
            details={"reason": "calc_task_not_found"},
        )

    async def call_calc(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        response = await self._call("erp", method, f"/api/v1/calc/{path}", json=json, params=params)
        if response.status_code >= 400:
            raise calc_error(response)
        return response.json()


def calc_error(response: Any) -> PlatformError:
    """Ответ ERP -> ошибка контракта: 400 — 422 с полем, 409 — `CONFLICT`, 403 и 404 — с
    `details.reason` (код ERP в нижнем регистре)."""
    try:
        body = response.json()
    except ValueError:
        body = None
    code = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(code, str):
        return erp_error(response)
    details: dict[str, Any] = {
        "backend_status": response.status_code,
        "backend_code": code,
        "reason": code.lower(),
    }
    if isinstance(body, dict) and isinstance(body.get("missing"), int):
        details["missing"] = body["missing"]
    if response.status_code == 400:
        fields = (
            [_FIELD_OF[code]] if code in _FIELD_OF else sorted(k for k in body if k != "detail")
        )
        if fields:
            details["fields"] = fields
        return PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            source="erp",
            details=details,
        )
    if response.status_code == 409:
        message = _MESSAGES.get(code, "Действие сейчас недоступно: обновите экран.")
        return PlatformError("CONFLICT", message, status_code=409, source="erp", details=details)
    if response.status_code in (403, 404):
        error = erp_error(response)
        error.body.details = {**(error.body.details or {}), "reason": code.lower()}
        return error
    return erp_error(response)


def _erp(authed: Authed) -> ErpCalc:
    return ErpCalc(authed.call)


async def _sheet(
    authed: Authed, number: str, method: str, suffix: str, json: Any = None
) -> CalcSheet:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    raw = await erp.call_calc(method, f"{deal_id}/{suffix}", json=json)
    return to_sheet(raw, authed.fields, authed.access)


@router.get(
    "/calc/requests",
    response_model=CalcRequestList,
    response_model_exclude_unset=True,
    operation_id="listCalcRequests",
)
async def list_requests(authed: Reader, mine: Annotated[bool, Query()] = False) -> CalcRequestList:
    data = await _erp(authed).call_calc("GET", "tasks/", params={"mine": 1} if mine else None)
    return CalcRequestList(items=[to_row(row) for row in data.get("results", [])])


@router.get(
    "/calc/catalog",
    response_model=CalcCatalogPage,
    operation_id="searchCalcCatalog",
)
async def search_catalog(
    authed: Reader, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> CalcCatalogPage:
    rows = (await _erp(authed).call_calc("GET", "catalog/", params={"q": q})).get("results", [])
    return CalcCatalogPage(
        items=[
            CalcCatalogItem(
                id=str(row["id"]),
                name=row["name"],
                article=row.get("article") or "",
                kind=row["kind"],
                on_hand=row.get("on_hand") or 0,
                supplier_name=row.get("supplier_name"),
                lead_days=row.get("lead_days"),
            )
            for row in rows
        ]
    )


@router.get(
    "/calc-jobs/{job_id}",
    response_model=CalcParseResult,
    response_model_exclude_unset=True,
    operation_id="getCalcParse",
)
async def get_parse(
    authed: Builder, job_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9-]+$", max_length=64)]
) -> CalcParseResult:
    response = await authed.call("erp", "GET", f"/api/v1/sourcing/ai-status/{job_id}/")
    if response.status_code == 403:
        raise PlatformError("NOT_FOUND", "Разбор не найден.", status_code=404, source="erp")
    if response.status_code >= 400:
        raise calc_error(response)
    data = response.json()
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return CalcParseResult(status="pending", lines=[])
    if "proposal" in result:
        return CalcParseResult(
            status="done",
            lines=[CalcProposalLine(**row) for row in result["proposal"]],
            recognized=int(result.get("recognized") or 0),
            truncated=bool(result.get("truncated")),
        )
    reason = result.get("error") or result.get("message") or "ai_job_failed"
    return CalcParseResult(status="failed", lines=[], reason=str(reason).lower())


@router.get(
    "/calc/{number}",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="getCalcSheet",
)
async def get_sheet(authed: Reader, number: Number) -> CalcSheet:
    return await _sheet(authed, number, "GET", "")


@router.post(
    "/calc/{number}/start",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="startCalc",
)
async def start(authed: Builder, number: Number) -> CalcSheet:
    return await _sheet(authed, number, "POST", "start/")


@router.post(
    "/calc/{number}/lines",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="addCalcLines",
)
async def add_lines(authed: Builder, number: Number, body: CalcLinesIn) -> CalcSheet:
    # Зона строки по каталогу Платформы: строка без карточки — по `kind`, с карточкой — любая
    # зона (тип задаёт каталог ERP). Окончательно решает ERP.
    for line in body.lines:
        if line.product_id is None:
            section = ZONE_SECTION[line.kind or "goods"]
            if section not in authed.access or authed.access[section] != "full":
                raise PlatformError(
                    "FORBIDDEN",
                    "Раздел или действие не положены вашей роли.",
                    status_code=403,
                    details={"resource": section, "need": "full"},
                )
    if not any(authed.access.get(s) == "full" for s in ZONE_SECTION.values()):
        raise PlatformError(
            "FORBIDDEN",
            "Раздел или действие не положены вашей роли.",
            status_code=403,
            details={"resource": "erp.calc.goods", "need": "full"},
        )
    rows: list[dict[str, Any]] = []
    for item in body.lines:
        row = item.model_dump(exclude_none=True)
        if "product_id" in row:
            row["product_id"] = int(row["product_id"])
        rows.append(row)
    return await _sheet(authed, number, "POST", "lines/", {"lines": rows})


@router.patch(
    "/calc/{number}/lines/{line_id}",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="updateCalcLine",
)
async def update_line(
    authed: ZoneHolder, number: Number, line_id: LineId, body: Annotated[CalcLinePatch, Body()]
) -> CalcSheet:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            details={"reason": "nothing_to_change"},
        )
    cost_fields = sorted({"purchase_price", "purchase_currency"} & set(patch))
    # Закупку товара правит тот, кто её видит: `cost_margin` или держатель зоны товаров (Q-D2-1-2).
    if (
        cost_fields
        and "cost_margin" not in authed.fields
        and "goods" not in zones_of(authed.access)
    ):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Закупку правит сотрудник с доступом к себестоимости.",
            status_code=422,
            details={"reason": "cost_forbidden", "fields": cost_fields},
        )
    if patch.get("product_id") is not None:
        patch["product_id"] = int(patch["product_id"])
    return await _sheet(authed, number, "PATCH", f"lines/{line_id}/", patch)


@router.delete(
    "/calc/{number}/lines/{line_id}",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="deleteCalcLine",
)
async def delete_line(authed: ZoneHolder, number: Number, line_id: LineId) -> CalcSheet:
    return await _sheet(authed, number, "DELETE", f"lines/{line_id}/")


@router.post(
    "/calc/{number}/lines/{line_id}/visa",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="signCalcLine",
)
async def sign_line(authed: ZoneHolder, number: Number, line_id: LineId) -> CalcSheet:
    return await _sheet(authed, number, "POST", f"lines/{line_id}/visa/")


@router.post(
    "/calc/{number}/ready",
    response_model=CalcSheet,
    response_model_exclude_unset=True,
    operation_id="markCalcReady",
)
async def mark_ready(authed: Builder, number: Number) -> CalcSheet:
    return await _sheet(authed, number, "POST", "ready/")


@router.post(
    "/calc/{number}/parse",
    response_model=CalcParseJob,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="parseCalcText",
)
async def parse_text(
    authed: Builder, number: Number, body: Annotated[CalcParseIn | None, Body()] = None
) -> CalcParseJob:
    erp = _erp(authed)
    deal_id = await erp.deal_id(number)
    text = body.text if body is not None and body.text else ""
    data = await erp.call_calc("POST", f"{deal_id}/parse/", json={"text": text})
    return CalcParseJob(job_id=str(data["task_id"]))
