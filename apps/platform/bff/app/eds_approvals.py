"""Сборка экранов «КП на одобрение» и «На согласовании» (контракт BFF 0.22.0, тег `eds-approvals`).

BFF не решает: маршрут, шаги, чек-лист КП и `allowed_decisions` приходят из EDS; здесь — вызовы с
токеном доступа EDS, состав КП и контакт клиента из ERP (частичный ответ `sources`), вырезание
полей `cost_margin` и перевод ошибок решения (`not_your_step`, `route_closed`,
`checklist_not_green`).
"""

import asyncio
import re
from collections.abc import Awaitable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from app.deps import Authed
from app.eds_documents import API, EdsProxy, eds_error
from app.errors import PlatformError
from app.feeds.feed import Feed
from app.feeds.models import StepCode
from app.feeds.numbers import deal_step
from app.rbac import strip_restricted
from app.schemas_eds_approvals import (
    MEMO_KINDS,
    MemoApprovalCard,
    MemoApprovalPage,
    MemoApprovalRow,
    QuoteApprovalCard,
    QuoteApprovalPage,
    QuoteApprovalRow,
    QuoteCalculator,
    QuoteChannels,
    QuoteChecklistLine,
    QuoteInternal,
    QuoteLetterRef,
    QuoteLine,
    QuoteRequestRef,
    QuoteTotals,
    RawApproval,
    RawDocument,
    RawListItem,
    RawPage,
    parse,
    person,
    route_step,
)
from app.schemas_eds_documents import EdsDealRef, EdsDecision, EdsFile, EdsMoney, EdsPerson

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
QUOTE_NUMBER_RE = re.compile(r"^КП-\d{4}/\d+$")
MEMO_NUMBER_RE = re.compile(r"^(СЗ|ЗЯ|ОТ)-\d{4}/\d+$")

# Поля снимка КП и чек-листа с экономикой: без группы `cost_margin` вырезаются до разбора.
MARGIN_RULES = {"cost_margin": ("cost", "margin_amount", "margin_pct", "min_margin_pct")}
ENRICH_PARALLEL = 8
_STAGES: tuple[StepCode, ...] = (
    "REQUEST",
    "RESOLUTION",
    "CALCULATION",
    "QUOTE",
    "CONTRACT",
    "PAYMENT",
    "DONE",
)
_SOFT = (403, 404, 503)  # источник не дал данных — строка остаётся без обогащения


def not_found(what: str) -> PlatformError:
    return PlatformError(
        "NOT_FOUND",
        what,
        status_code=404,
        source="eds",
        details={"backend_status": 404},
    )


def decision_error(response: Any) -> PlatformError:
    """Ошибка решения EDS в формате `Error`; к подкоду добавляются коды красных строк чек-листа."""
    error = eds_error(response)
    try:
        body = response.json()
    except ValueError:
        body = {}
    raw = body.get("details") if isinstance(body, dict) else None
    failed = raw.get("failed") if isinstance(raw, dict) else None
    if isinstance(failed, list):
        details = error.body.details or {}
        details["failed"] = [str(code) for code in failed]
        error.body.details = details
    return error


async def soft[T](call: Awaitable[T]) -> T | None:
    """Вызов, чей отказ не роняет экран (403, 404, недоступность): `None`."""
    try:
        result = await call
    except PlatformError as exc:
        if exc.status_code in _SOFT:
            return None
        raise
    return result


def money(value: Any, currency: Any) -> EdsMoney | None:
    """Сумма EDS (`Amount`) как `EdsMoney`; нулевая или нечисловая — нет суммы."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0 or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    return EdsMoney(amount=f"{amount:.2f}", currency=currency)


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _plain(value: Decimal) -> str:
    return f"{value:.2f}"


# --- списки --------------------------------------------------------------------------------------


async def _page(
    proxy: EdsProxy,
    templates: list[str],
    *,
    mine: bool,
    status: list[str],
    cursor: str | None,
    limit: int,
) -> RawPage:
    params: dict[str, Any] = {
        "mine": "true" if mine else "false",
        "template": templates,
        "limit": limit,
    }
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    return parse(RawPage, await proxy.request("GET", f"{API}/approvals", params=params), "page")


async def _gather[T](items: list[Any], load: Any) -> list[T | None]:
    sem = asyncio.Semaphore(ENRICH_PARALLEL)

    async def one(item: Any) -> T | None:
        async with sem:
            return await soft(load(item))

    return list(await asyncio.gather(*(one(i) for i in items)))


async def quote_page(
    proxy: EdsProxy, *, mine: bool, status: list[str], cursor: str | None, limit: int
) -> QuoteApprovalPage:
    page = await _page(proxy, ["quote"], mine=mine, status=status, cursor=cursor, limit=limit)

    async def detail(item: RawListItem) -> RawApproval:
        return parse(
            RawApproval, await proxy.request("GET", f"{API}/approvals/{item.id}"), "approval"
        )

    details = await _gather(page.items, detail)
    rows: list[QuoteApprovalRow] = []
    for item, full in zip(page.items, details, strict=True):
        snap = full.quote if full else None
        rows.append(
            QuoteApprovalRow(
                id=item.id,
                number=item.object.quote_number or item.title,
                version=item.object.quote_version or 1,
                request_number=item.object.deal_number,
                client_name=snap.client_name if snap else None,
                total=money(snap.total, snap.currency) if snap else None,
                due=snap.due if snap else None,
                status=item.status,
                can_decide=full.can_decide if full else False,
                outgoing_number=full.outgoing_number if full else None,
                created_at=item.created_at,
            )
        )
    return QuoteApprovalPage(items=rows, next_cursor=page.next_cursor)


async def memo_page(
    proxy: EdsProxy, *, mine: bool, status: list[str], cursor: str | None, limit: int
) -> MemoApprovalPage:
    page = await _page(
        proxy, list(MEMO_KINDS), mine=mine, status=status, cursor=cursor, limit=limit
    )
    items = [i for i in page.items if i.object.document_id and i.template in MEMO_KINDS]

    async def document(item: RawListItem) -> RawDocument:
        return parse(
            RawDocument,
            await proxy.request("GET", f"{API}/documents/{item.object.document_id}"),
            "document",
        )

    async def detail(item: RawListItem) -> RawApproval:
        return parse(
            RawApproval, await proxy.request("GET", f"{API}/approvals/{item.id}"), "approval"
        )

    docs = await _gather(items, document)
    # `can_decide` — слово EDS по маршруту (`GET /approvals/{id}`), BFF его не вычисляет.
    routes = await _gather(items, detail)
    rows: list[MemoApprovalRow] = []
    for item, doc, route in zip(items, docs, routes, strict=True):
        kind: Any = item.template
        rows.append(
            MemoApprovalRow(
                id=str(item.object.document_id),
                approval_id=item.id,
                number=item.object.number,
                kind=kind,
                subject=doc.subject if doc else item.title,
                author=person(doc.author) if doc else None,
                amount=money(doc.amount.amount, doc.amount.currency)
                if doc and doc.amount
                else None,
                due_date=doc.due_date if doc else None,
                status=item.status,
                step_label=item.current_step.label if item.current_step else None,
                can_decide=route.can_decide if route else False,
                created_at=item.created_at,
            )
        )
    return MemoApprovalPage(items=rows, next_cursor=page.next_cursor)


# --- адресация -----------------------------------------------------------------------------------


async def registry_ids(proxy: EdsProxy, number: str, kind: str | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"number": number, "limit": 20}
    if kind:
        params["kind"] = kind
    body = await proxy.request("GET", f"{API}/registry", params=params)
    items = body.get("items") if isinstance(body, dict) else None
    return [i for i in items or [] if isinstance(i, dict) and i.get("number") == number]


async def quote_route_id(proxy: EdsProxy, ref: str) -> str:
    if UUID_RE.match(ref):
        return ref.lower()
    if not QUOTE_NUMBER_RE.match(ref):
        raise not_found("КП не найдено.")
    found = [i for i in await registry_ids(proxy, ref, "quote") if i.get("kind") == "quote"]
    if not found:
        raise not_found("КП не найдено.")
    # У номера несколько версий: открытая (ждёт решения), иначе самая свежая.
    found.sort(key=lambda i: str(i.get("registered_at") or ""), reverse=True)
    chosen = next((i for i in found if i.get("status") == "open"), found[0])
    return str(chosen["id"])


async def memo_document_id(proxy: EdsProxy, ref: str) -> str:
    if UUID_RE.match(ref):
        return ref.lower()
    if not MEMO_NUMBER_RE.match(ref):
        raise not_found("Документ не найден.")
    for item in await registry_ids(proxy, ref, None):
        if item.get("kind") in MEMO_KINDS:
            return str(item["id"])
    raise not_found("Документ не найден.")


# --- карточка КП ---------------------------------------------------------------------------------


def _lines(erp_quote: dict[str, Any]) -> list[QuoteLine]:
    lines: list[QuoteLine] = []
    for raw in erp_quote.get("items") or []:
        if not isinstance(raw, dict) or raw.get("display_type", "ITEM") != "ITEM":
            continue
        name = next(
            (
                t
                for k in ("name_canonical", "product_name", "imported_raw_name")
                if (t := _text(raw.get(k)))
            ),
            "—",
        )
        qty_raw = raw.get("quantity")
        qty = qty_raw if isinstance(qty_raw, int) and not isinstance(qty_raw, bool) else 0
        price = _dec(raw.get("final_price_excl_vat")) or Decimal(0)
        lead = raw.get("lead_time_days")
        lines.append(
            QuoteLine(
                position=len(lines) + 1,
                name=name,
                quantity=qty,
                unit=_text(raw.get("unit")) or _text(raw.get("product_uom")),
                unit_price=_plain(price),
                amount=_plain(price * qty),
                lead_time_days=lead
                if isinstance(lead, int) and not isinstance(lead, bool)
                else None,
                optional=raw.get("is_optional") is True,
            )
        )
    return lines


def _totals(erp_quote: dict[str, Any]) -> QuoteTotals | None:
    total = _dec(erp_quote.get("total_incl_vat"))
    currency = erp_quote.get("quote_currency")
    if total is None or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    subtotal = _dec(erp_quote.get("subtotal_excl_vat"))
    vat = _dec(erp_quote.get("vat_amount"))
    rate = _dec(erp_quote.get("vat_rate"))
    return QuoteTotals(
        currency=currency,
        subtotal=_plain(subtotal) if subtotal is not None else None,
        vat_rate=f"{rate.normalize():f}" if rate is not None else None,
        vat_amount=_plain(vat) if vat is not None else None,
        total=_plain(total),
    )


def _channels(contact: dict[str, Any] | None) -> QuoteChannels | None:
    if contact is None:
        return None
    return QuoteChannels(
        contact_name=_text(contact.get("name")),
        telegram=isinstance(contact.get("telegram_user_id"), int),
        cabinet=contact.get("company_is_registered") is True,
        email=_text(contact.get("email")) is not None,
    )


def _stage(deal: dict[str, Any] | None) -> StepCode:
    """«КП» — пока заявка в ERP не ушла дальше (договор, оплата, выполнено) или не закрыта."""
    if deal is None:
        return "QUOTE"
    step = deal_step(deal)
    if step == "LOST":
        return "LOST"
    if step in _STAGES and _STAGES.index(step) > _STAGES.index("QUOTE"):
        return step
    return "QUOTE"


def _request_path(number: str) -> str:
    return f"/crm/requests?request={quote(number, safe='')}&panel=open&tab=card"


async def _letter(proxy: EdsProxy, deal_number: str | None) -> QuoteLetterRef | None:
    if not deal_number:
        return None
    body = await soft(
        proxy.request("GET", f"{API}/letters", params={"q": deal_number, "limit": 10})
    )
    items = body.get("items") if isinstance(body, dict) else None
    best: dict[str, Any] | None = None
    for item in items or []:
        links = item.get("links") if isinstance(item, dict) else None
        if not isinstance(links, dict) or links.get("deal_number") != deal_number:
            continue
        if best is None or str(item.get("received_at")) > str(best.get("received_at")):
            best = item
    number = best.get("number") if best else None
    if not isinstance(number, str):
        return None
    return QuoteLetterRef(number=number, path=f"/eds/inbox/{quote(number, safe='')}")


async def quote_card(authed: Authed, proxy: EdsProxy, body: Any) -> QuoteApprovalCard:
    """Карточка КП: маршрут EDS + состав КП, заявка и контакт клиента из ERP."""
    show = "cost_margin" in authed.fields
    raw = parse(RawApproval, strip_restricted(body, authed.fields, MARGIN_RULES), "approval")
    if raw.template != "quote" or raw.object.erp_quote_id is None:
        raise not_found("КП не найдено.")
    feed = Feed(authed)
    quote_id, deal_id = raw.object.erp_quote_id, raw.object.erp_deal_id
    erp_quote, deal, letter = await asyncio.gather(
        feed.get("erp", f"/api/v1/crm/quotes/{quote_id}/"),
        feed.get("erp", f"/api/v1/crm/deals/{deal_id}/") if deal_id is not None else _none(),
        _letter(proxy, raw.object.deal_number),
    )
    erp_quote = erp_quote if isinstance(erp_quote, dict) else None
    version = raw.object.quote_version
    erp_version = erp_quote.get("version") if erp_quote else None
    if erp_quote and isinstance(erp_version, int) and version and erp_version != version:
        # У ERP уже другая редакция КП: строки закрытого круга не показываем — только снимок EDS.
        erp_quote = None
    deal = deal if isinstance(deal, dict) else None
    contact: dict[str, Any] | None = None
    contact_id = deal.get("client") if deal else None
    if isinstance(contact_id, int):
        found = await feed.get("erp", f"/api/v1/accounts/contacts/{contact_id}/")
        contact = found if isinstance(found, dict) else None

    snap = raw.quote
    number = raw.object.quote_number or raw.title
    title = _text(deal.get("title")) if deal else None
    request = (
        QuoteRequestRef(
            number=raw.object.deal_number,
            title=title,
            path=_request_path(raw.object.deal_number),
        )
        if raw.object.deal_number
        else None
    )
    checklist = [
        QuoteChecklistLine(
            code=c.code,
            ok=c.ok,
            blocking=c.blocking,
            by_name=c.by.full_name if c.by else None,
            at=c.at,
            **({"value": c.value} if c.code != "margin" or show else {}),
        )
        for c in raw.checklist
    ]
    internal: QuoteInternal | None = None
    if show and snap is not None and snap.margin_pct is not None:
        internal = QuoteInternal(
            cost=snap.cost,
            margin_amount=snap.margin_amount,
            margin_pct=snap.margin_pct,
            min_margin_pct=snap.min_margin_pct,
            payment_terms=None,
            valid_until=snap.valid_until,
            supplier_price_until=None,
        )
    extra: dict[str, Any] = {"internal": internal} if internal is not None else {}
    totals = _totals(erp_quote) if erp_quote else None
    snapshot_total = money(snap.total, snap.currency) if snap else None
    mismatch = False
    if totals is not None and snapshot_total is not None:
        erp_total = _dec(totals.total)
        mismatch = totals.currency != snapshot_total.currency or erp_total != _dec(
            snapshot_total.amount
        )
    client_name = (snap.client_name if snap else None) or (
        _text(deal.get("company_name")) if deal else None
    )
    return QuoteApprovalCard(
        id=raw.id,
        number=number,
        version=raw.object.quote_version or 1,
        round=raw.round,
        status=raw.status,
        stage=_stage(deal),
        can_decide=raw.can_decide,
        allowed_decisions=raw.allowed_decisions,
        approved_late=raw.approved_late,
        outgoing_number=raw.outgoing_number,
        created_at=raw.created_at,
        ready_at=snap.ready_at if snap else None,
        due=snap.due if snap else None,
        client_name=client_name,
        request=request,
        letter=letter,
        calculated_by=[
            QuoteCalculator(name=c.by_name, zone="goods" if c.code == "visa_goods" else "services")
            for c in checklist
            if c.code in ("visa_goods", "visa_services") and c.by_name
        ],
        snapshot_total=snapshot_total,
        totals_mismatch=mismatch,
        lines=_lines(erp_quote) if erp_quote else None,
        totals=totals,
        checklist=checklist,
        steps=[route_step(s) for s in raw.steps],
        channels=_channels(contact),
        sources=feed.sources,
        **extra,
    )


async def _none() -> None:
    return None


# --- карточка документа --------------------------------------------------------------------------


async def memo_card(
    proxy: EdsProxy, doc_body: Any, approval_body: Any | None = None
) -> MemoApprovalCard:
    doc = parse(RawDocument, doc_body, "document")
    if doc.kind not in MEMO_KINDS:
        raise not_found("Документ не найден.")
    if approval_body is None:
        if doc.approval_id is None:
            raise not_found("Документ не отправлялся на согласование.")
        approval_body = await proxy.request("GET", f"{API}/approvals/{doc.approval_id}")
    approval = parse(RawApproval, approval_body, "approval")
    kind: Any = doc.kind
    return MemoApprovalCard(
        id=doc.id,
        approval_id=approval.id,
        number=doc.number,
        kind=kind,
        subject=doc.subject,
        text=doc.text,
        document_status=doc.status,
        status=approval.status,
        round=approval.round,
        author=EdsPerson(crm_user_id=doc.author.crm_user_id or 0, full_name=doc.author.full_name),
        addressee=person(doc.addressee),
        amount=money(doc.amount.amount, doc.amount.currency) if doc.amount else None,
        due_date=doc.due_date,
        files=[
            EdsFile(id=f.id, name=f.name, content_type=f.content_type, size=f.size)
            for f in doc.files
        ],
        deal=EdsDealRef(erp_deal_id=doc.erp_deal_id, number=doc.deal_number)
        if doc.erp_deal_id is not None
        else None,
        steps=[route_step(s) for s in approval.steps],
        accountant_step=any(
            s.status == "current"
            and s.assignee is not None
            and s.assignee.permission == "payments.confirm"
            for s in approval.steps
        ),
        decisions=[
            EdsDecision(
                round=d.round,
                step=d.step,
                decision=d.decision,
                comment=d.comment,
                by=EdsPerson(crm_user_id=d.by.crm_user_id or 0, full_name=d.by.full_name),
                at=d.at,
            )
            for d in doc.decisions
        ],
        can_decide=approval.can_decide,
        allowed_decisions=approval.allowed_decisions,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )
