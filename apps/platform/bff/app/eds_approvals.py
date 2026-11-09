"""Сборка экранов «КП на одобрение» и «На согласовании» (контракт BFF 0.24.0, тег `eds-approvals`).

BFF не решает: маршрут, шаги, чек-лист КП и `allowed_decisions` приходят из EDS; здесь — вызовы с
токеном доступа EDS, состав КП, доступность каналов и итог отправки из ERP (частичный ответ
`sources`), вырезание полей `cost_margin` и перевод ошибок решения (`not_your_step`, `route_closed`,
`checklist_not_green`).

D17G-2 (гейт D1-7): каналы отправки — по фактическим контактам клиента, их проверяет ERP
(`channel_availability` КП, те же правила, что у автоотправки), «почта настроена» — CRM. Прежде BFF
искал контакт по `deal.client` (это пользователь ERP, а не контакт) и почти всегда писал «контакт
не получен». Отчёт по каналам после одобрения — из `send_report` КП ERP.
"""

import asyncio
import re
from collections.abc import Awaitable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote

from pydantic import ValidationError

from app.deps import Authed
from app.eds_documents import API, EdsProxy, eds_error
from app.errors import PlatformError, backend_code, from_backend
from app.feeds.feed import Feed
from app.feeds.models import StepCode
from app.feeds.numbers import deal_step, request_path
from app.rbac import allows, strip_restricted
from app.schemas_eds_approvals import (
    MEMO_KINDS,
    Channel,
    DeliveryReason,
    DeliveryStatus,
    MemoApprovalCard,
    MemoApprovalPage,
    MemoApprovalRow,
    OnBehalfRecord,
    QuoteApprovalCard,
    QuoteApprovalPage,
    QuoteApprovalRow,
    QuoteCalculator,
    QuoteChannelReasons,
    QuoteChannels,
    QuoteChecklistLine,
    QuoteClientComment,
    QuoteClientDecision,
    QuoteDelivery,
    QuoteDeliveryLine,
    QuoteInternal,
    QuoteLetterRef,
    QuoteLine,
    QuoteRequestRef,
    QuoteTotals,
    RawApproval,
    RawDocument,
    RawListItem,
    RawPage,
    SigningApprovalPage,
    SigningApprovalRow,
    parse,
    person,
    route_step,
)
from app.schemas_eds_documents import EdsDealRef, EdsDecision, EdsFile, EdsMoney, EdsPerson

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Номер КП: ERP (`КП-2026-00001`, с префиксом продавца — `ACME-КП-2026-00001`) и вид `КП-2026/115`.
QUOTE_NUMBER_RE = re.compile(r"^(?:[\w.]+-)?КП-\d{4}[-/]\d+$")
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
                superseded_by=item.object.superseded_by_version,
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


async def signing_page(proxy: EdsProxy) -> SigningApprovalPage:
    """Открытые шаги «Подписать» текущего сотрудника (SIGN-4, FX-10): подписант назначен в EDS."""
    data = await proxy.request(
        "GET",
        f"{API}/approvals",
        params={"mine": "true", "template": ["signing"], "status": ["open"], "limit": 100},
    )
    rows = []
    for item in data.get("items", []):
        obj = item.get("object") or {}
        tiyins = obj.get("signing_amount_tiyins")
        rows.append(
            SigningApprovalRow(
                id=item["id"],
                kind=obj["signing_kind"],
                number=obj["signing_number"],
                title=item.get("title") or "",
                amount=f"{Decimal(tiyins) / 100:.2f}" if tiyins is not None else None,
                currency=obj.get("signing_currency"),
                created_at=item["created_at"],
            )
        )
    return SigningApprovalPage(items=rows)


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


def _client_comments(erp_quote: dict[str, Any] | None) -> list[QuoteClientComment]:
    """Комментарии клиента к КП из ERP (кабинет, B-CABFIX-1); битые записи пропускаются."""
    found: list[QuoteClientComment] = []
    for raw in (erp_quote or {}).get("client_comments") or []:
        if not isinstance(raw, dict):
            continue
        try:
            found.append(
                QuoteClientComment(
                    author="manager" if raw.get("author") == "manager" else "client",
                    author_name=_text(raw.get("author_name")),
                    text=str(raw.get("text") or ""),
                    created_at=raw.get("created_at"),
                )
            )
        except ValidationError:
            continue
    return found


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


CHANNEL_ORDER: tuple[Channel, ...] = ("telegram", "cabinet", "email")
SMTP_READY_PATH = "/api/v1/integrations/smtp/ready"
# Коды ERP (проверки каналов `quote_auto_send._CHECKS`, гейты отправки) -> причины контракта.
_ERP_REASONS: dict[str, DeliveryReason] = {
    "CONTACT_TELEGRAM_REQUIRED": "no_telegram",
    "CLIENT_NOT_IN_CRM": "client_not_in_crm",
    "CABINET_NOT_INVITED": "no_cabinet",
    "CONTACT_EMAIL_REQUIRED": "no_email",
    "QUOTE_BELOW_COST": "below_cost",
    "FX_RATE_MISSING": "fx_missing",
    "QUOTE_HAS_UNPRICED_LINES": "unpriced_lines",
    "BELOW_FLOOR_JUSTIFICATION_REQUIRED": "below_floor",
    "QUOTE_NOT_CLAIMED": "not_claimed",
    "RECIPIENT_REQUIRED": "no_recipient",
}
_STATES: dict[str, Literal["ready", "sent", "closed"]] = {
    "READY_TO_SEND": "ready",
    "SENT": "sent",
    "APPROVED": "closed",
    "REJECTED": "closed",
}
_RESENDABLE: frozenset[DeliveryStatus] = frozenset({"failed", "skipped", "not_selected", "unknown"})


def erp_reason(code: object, detail: object = None) -> DeliveryReason:
    """Код ERP -> причина контракта; недоставленное письмо — по причине почтового сервиса."""
    if code == "EMAIL_DELIVERY_FAILED":
        return "mail_not_configured" if detail == "smtp_not_configured" else "mail_failed"
    return _ERP_REASONS.get(str(code), "send_failed")


def _channels(erp_quote: dict[str, Any] | None, mail_ready: bool | None) -> QuoteChannels | None:
    """Доступность каналов из ERP (`channel_availability`) и CRM (почта настроена; `None` —
    не узнали)."""
    found = erp_quote.get("channel_availability") if erp_quote else None
    if not isinstance(found, dict):
        return None
    reasons: dict[str, DeliveryReason | None] = dict.fromkeys(CHANNEL_ORDER)
    for row in found.get("channels") or []:
        if not isinstance(row, dict) or row.get("channel") not in reasons:
            continue
        if row.get("available") is not True:
            reasons[row["channel"]] = erp_reason(row.get("reason"))
    if reasons["email"] is None and mail_ready is False:
        reasons["email"] = "mail_not_configured"
    return QuoteChannels(
        contact_name=_text(found.get("contact_name")),
        telegram=reasons["telegram"] is None,
        cabinet=reasons["cabinet"] is None,
        email=reasons["email"] is None,
        reasons=QuoteChannelReasons.model_validate(reasons),
    )


def _line_status(
    channel: Channel,
    state: Literal["ready", "sent", "closed"],
    report: dict[str, Any],
    channels: QuoteChannels | None,
) -> tuple[DeliveryStatus, DeliveryReason | None]:
    skipped = {
        item.get("channel"): item for item in report.get("skipped") or [] if isinstance(item, dict)
    }
    sent_via = report.get("sent_via") or []
    if channel in skipped:
        item = skipped[channel]
        reason = erp_reason(item.get("reason"), item.get("detail"))
        return ("failed" if item.get("reason") == "EMAIL_DELIVERY_FAILED" else "skipped"), reason
    if channel in sent_via:
        if channel == "cabinet":
            return "published", None
        if channel == "email" and not report.get("email_sent_at"):
            return "pending", None
        return "sent", None
    error = report.get("error")
    if error and channel in (report.get("requested") or []):
        return "failed", erp_reason(error)
    if channel == "cabinet" and state != "ready":
        # Отправленное КП клиент видит в кабинете всегда (DECISIONS 2026-10-28 «ERP-11»), если он
        # туда приглашён.
        if channels is not None and not channels.cabinet:
            return "skipped", channels.reasons.cabinet
        return "published", None
    if not report and state != "ready":
        return "unknown", None
    return "not_selected", None


def _delivery(
    route_status: str,
    erp_quote: dict[str, Any] | None,
    channels: QuoteChannels | None,
    may_send: bool,
) -> QuoteDelivery | None:
    """Отчёт об отправке одобренного КП по каналам (ERP `send_report`, D17G-2)."""
    if route_status != "approved" or erp_quote is None:
        return None
    state = _STATES.get(str(erp_quote.get("status_code") or ""))
    if state is None:
        return None
    raw_report = erp_quote.get("send_report")
    report: dict[str, Any] = raw_report if isinstance(raw_report, dict) else {}
    lines: list[QuoteDeliveryLine] = []
    for channel in CHANNEL_ORDER:
        status, reason = _line_status(channel, state, report, channels)
        can = (
            may_send
            and state != "closed"
            and channel != "cabinet"
            and status in _RESENDABLE
            and channels is not None
            and bool(getattr(channels, channel))
        )
        lines.append(QuoteDeliveryLine(channel=channel, status=status, reason=reason, can_send=can))
    error = report.get("error")
    return QuoteDelivery(state=state, lines=lines, error=erp_reason(error) if error else None)


_DECISION_STATES: dict[str, Literal["awaiting", "accepted", "rejected", "expired"]] = {
    "SENT": "awaiting",
    "APPROVED": "accepted",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
}


def evidence_url(approval_id: str) -> str:
    return f"/api/v1/eds/quotes/{approval_id}/client-decision/evidence"


def _recorded_by_staff(raw: Any, approval_id: str) -> OnBehalfRecord | None:
    if not isinstance(raw, dict) or not raw.get("channel"):
        return None
    try:
        return OnBehalfRecord.model_validate(
            {
                "staff_name": _text(raw.get("recorded_by_name")),
                "channel": raw.get("channel"),
                "counterparty_person": raw.get("counterparty_person") or "",
                "occurred_on": raw.get("occurred_on") or None,
                "comment": _text(raw.get("comment")),
                "evidence_name": _text(raw.get("evidence_name")),
                "evidence_url": evidence_url(approval_id)
                if raw.get("evidence_attachment_id")
                else None,
            }
        )
    except ValidationError:
        return None


def _client_decision(
    erp_quote: dict[str, Any] | None, approval_id: str, may_record: bool
) -> QuoteClientDecision | None:
    """Решение клиента по отправленному КП (A1): статус ERP, атрибуция записи сотрудником, можно ли
    записать (решает ERP: `can_record_client_decision` — SENT и право `deal.manage`)."""
    if erp_quote is None:
        return None
    state = _DECISION_STATES.get(str(erp_quote.get("status_code") or ""))
    if state is None:
        return None
    staff = _recorded_by_staff(erp_quote.get("client_decision"), approval_id)
    decided_at = None
    if state != "awaiting":
        decided_at = (staff and (erp_quote.get("client_decision") or {}).get("recorded_at")) or (
            erp_quote.get("approved_at") if state == "accepted" else None
        )
    reason = _text(erp_quote.get("client_reject_reason")) if state == "rejected" else None
    return QuoteClientDecision(
        state=state,
        decided_at=decided_at,
        reason=reason,
        recorded_by_staff=staff,
        can_record=bool(
            may_record and state == "awaiting" and erp_quote.get("can_record_client_decision")
        ),
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
    """Заявка КП — рабочий экран заявки (B-UIA-1, `feeds.numbers.request_path`)."""
    return request_path(number)


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
    erp_quote, deal, letter, smtp = await asyncio.gather(
        feed.get("erp", f"/api/v1/crm/quotes/{quote_id}/"),
        feed.get("erp", f"/api/v1/crm/deals/{deal_id}/") if deal_id is not None else _none(),
        _letter(proxy, raw.object.deal_number),
        feed.peek("crm", SMTP_READY_PATH, ttl=30),
    )
    erp_quote = erp_quote if isinstance(erp_quote, dict) else None
    # Комментарии клиента — у объекта КП, а не у редакции: видны и тогда, когда строки ERP скрыты
    # ниже.
    comments = _client_comments(erp_quote)
    version = raw.object.quote_version
    erp_version = erp_quote.get("version") if erp_quote else None
    if erp_quote and isinstance(erp_version, int) and version and erp_version != version:
        # У ERP уже другая версия КП (версия маршрута EDS — `Quote.version` ERP, D26G-2): строки
        # заменённой версии не показываем — только снимок EDS.
        erp_quote = None
    deal = deal if isinstance(deal, dict) else None
    channels = _channels(erp_quote, _mail_ready(smtp))
    may_send = erp_quote is not None and erp_quote.get("can_send") is True
    may_send = may_send and allows(authed.access, "crm.clients", "full")

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
        superseded_by=raw.object.superseded_by_version,
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
        channels=channels,
        delivery=_delivery(raw.status, erp_quote, channels, may_send),
        client_comments=comments,
        client_decision=_client_decision(
            erp_quote, raw.id, allows(authed.access, "crm.clients", "full")
        ),
        sources=feed.sources,
        **extra,
    )


async def _none() -> None:
    return None


SEND_FAILED_MESSAGE = "КП не отправлено: канал недоступен или отправку остановила ERP."


async def send_quote(authed: Authed, proxy: EdsProxy, approval_id: str, channel: str) -> Any:
    """«Отправить» КП по каналу (D17G-2): ERP `deliver` по КП маршрута; ответ — маршрут EDS.

    Право и объектную проверку (своя заявка или `quote.review`) решает ERP; недоступный канал и гейт
    отправки — 409 с причиной контракта, `INVALID_STATUS` — `invalid_status`.
    """
    body = await proxy.request("GET", f"{API}/approvals/{approval_id}")
    raw = parse(RawApproval, strip_restricted(body, authed.fields, MARGIN_RULES), "approval")
    if raw.template != "quote" or raw.object.erp_quote_id is None:
        raise not_found("КП не найдено.")
    response = await authed.call(
        "erp",
        "POST",
        f"/api/v1/crm/quotes/{raw.object.erp_quote_id}/deliver/",
        json={"channel": channel},
    )
    if response.status_code == 400:
        code = backend_code(response) or ""
        invalid = code in ("INVALID_STATUS", "UNKNOWN_CHANNEL")
        reason = "invalid_status" if invalid else erp_reason(code)
        raise PlatformError(
            "CONFLICT",
            SEND_FAILED_MESSAGE,
            status_code=409,
            source="erp",
            details={"reason": reason, "backend_code": code},
        )
    if response.status_code >= 400:
        raise from_backend("erp", response)
    return body


async def _route_quote_id(authed: Authed, proxy: EdsProxy, approval_id: str) -> tuple[Any, int]:
    body = await proxy.request("GET", f"{API}/approvals/{approval_id}")
    raw = parse(RawApproval, strip_restricted(body, authed.fields, MARGIN_RULES), "approval")
    if raw.template != "quote" or raw.object.erp_quote_id is None:
        raise not_found("КП не найдено.")
    return body, raw.object.erp_quote_id


async def record_client_decision(
    authed: Authed, proxy: EdsProxy, approval_id: str, content: bytes, content_type: str
) -> Any:
    """«Клиент принял / отклонил» по подтверждению клиента (A1): ERP `record-client-decision` по КП
    маршрута, форма multipart как есть (поля, файл и право проверяет ERP); ответ — маршрут EDS."""
    from app.eds_projects import project_error

    body, quote_id = await _route_quote_id(authed, proxy, approval_id)
    response = await authed.call(
        "erp",
        "POST",
        f"/api/v1/crm/quotes/{quote_id}/record-client-decision/",
        content=content,
        content_type=content_type,
    )
    if response.status_code != 200:
        raise project_error(response)
    return body


async def evidence_path(authed: Authed, proxy: EdsProxy, approval_id: str) -> str:
    """Путь файла подтверждения в ERP: id вложения — из решения клиента КП этого маршрута."""
    _, quote_id = await _route_quote_id(authed, proxy, approval_id)
    response = await authed.call("erp", "GET", f"/api/v1/crm/quotes/{quote_id}/")
    if response.status_code != 200:
        from app.eds_projects import project_error

        raise project_error(response)
    meta = response.json().get("client_decision") if response.content else None
    attachment_id = meta.get("evidence_attachment_id") if isinstance(meta, dict) else None
    if not isinstance(attachment_id, int):
        raise not_found("Файла подтверждения нет.")
    return f"/api/v1/sourcing/attachments/{attachment_id}/download/"


def _mail_ready(body: Any) -> bool | None:
    """CRM `smtp/ready`: почта настроена; не ответила или отказала — неизвестно (`None`)."""
    configured = body.get("configured") if isinstance(body, dict) else None
    return configured if isinstance(configured, bool) else None


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
