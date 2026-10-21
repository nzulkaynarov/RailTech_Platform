"""AI draft-КП generation (ADR-0006 Move 3 — speed).

A back-office staff member turns the buyer's request into a pre-filled draft КП in ONE click: the request lines
are copied into a new seller Quote, and matched products get cost / currency / lead-time prefilled
from the seller's own SupplierOffers (pricing-assist). The seller reviews-and-sends instead of
re-typing the whole КП — cutting time-to-first-КП (the wedge metric). Rule 8 service.
"""

import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from accounts.models import CustomUser
from crm.constants import QuoteStatusCode

from ..models import Deal, Quote, QuoteItem, QuoteStatus
from .pricing_assist import suggest_pricing_for_products

logger = logging.getLogger(__name__)

# Line-identity fields copied verbatim from a buyer request line → the seller's draft line.
_LINE_FIELDS = (
    "product_id",
    "imported_raw_name",
    "name_canonical",
    "quantity",
    "unit",
    "unit_code",
    "mpn",
    "gost_drawing",
    "hs_code",
    "note",
)


@dataclass(frozen=True)
class RequestLine:
    """Строка заявки клиента в виде, который копирует построитель КП (поля `_LINE_FIELDS` + `pk`).

    Строки заявки из Cabinet и из передачи CRM лежат в `portal.PortalRequestLine`, а не в позициях КП —
    сервисы ниже читают их одинаково через `_request_items`, не зная, откуда строка."""

    pk: int
    imported_raw_name: str
    quantity: int
    unit: str = ""
    note: str = ""
    product_id: Optional[int] = None
    name_canonical: str = ""
    unit_code: str = ""
    mpn: str = ""
    gost_drawing: str = ""
    hs_code: str = ""


def _portal_request_lines(deal: Deal) -> list:
    """Строки заявки клиента из портала / передачи CRM. Ничего не выдумываем: количество не указано — 1
    (в КП оно целое и не меньше единицы), дробное округляется вверх, чтобы не заказать меньше написанного."""
    lines = []
    for line in deal.portal_lines.all():
        text = (line.text or "").strip()
        max_name = QuoteItem._meta.get_field("imported_raw_name").max_length
        quantity = max(1, math.ceil(line.quantity)) if line.quantity else 1
        lines.append(
            RequestLine(
                pk=line.pk,
                imported_raw_name=text[:max_name],
                # Не влезло в наименование — полный текст остаётся в примечании, а не теряется.
                note=text if len(text) > max_name else "",
                quantity=quantity,
                unit=(line.unit or "").strip()[: QuoteItem._meta.get_field("unit").max_length],
            )
        )
    return lines


def _request_items(deal: Deal):
    """Строки заявки клиента: строки портала (`PortalRequestLine`) либо, у прежних сделок, позиции
    «КП заявки» без исполнителя (`prepared_by=None`)."""
    portal_lines = _portal_request_lines(deal)
    if portal_lines:
        return portal_lines
    request_quote = deal.quotes.filter(prepared_by__isnull=True).order_by("version").first()
    return list(request_quote.items.all()) if request_quote else []


def deal_request_lines_count(deal: Deal) -> int:
    """Сколько строк в заявке (для кнопок карточки сделки: «Взять в работу и подготовить» — только со строками)."""
    return len(_request_items(deal))


def deal_request_text(deal: Deal) -> str:
    """Заявка словами: полный текст клиента (`PortalRequestSummary`), иначе комментарий сделки `notes`
    (передача из CRM кладёт суть потребности туда)."""
    summary = getattr(deal, "portal_summary", None)
    if summary is not None and (summary.text or "").strip():
        return summary.text.strip()
    return (deal.notes or "").strip()


def _resolve_exact_catalog_matches(request_items) -> dict:
    """Deterministically bind still-unmatched request lines to a catalog Product by EXACT
    identifier (GOST drawing, then MPN) — but ONLY when exactly one PUBLISHED product matches.

    This is the SAFE half of ADR-0006 Move 3 (auto-match to cut time-to-first-КП): an exact
    GOST/MPN hit is unambiguous, so it is auto-bound → pricing-assist can then prefill it, and the
    seller gets a fuller draft in one click. Fuzzy / trigram / AI matches deliberately do NOT
    auto-bind here — they stay human-confirmed (services_ai.match_lines_to_catalog / Smart Match),
    preserving the platform's "AI never binds unattended" principle. A line with an ambiguous
    identifier (2+ published matches) is left unmatched rather than guessed.

    Returns {request_item.pk: product_id} for the lines that were resolved.
    """
    from catalog.models import Product

    resolved: dict[int, int] = {}
    for src in request_items:
        if src.product_id:
            continue
        gost = (src.gost_drawing or "").strip()
        mpn = (src.mpn or "").strip()
        product_ids = []
        if gost:
            product_ids = list(
                Product.objects.filter(status__code="PUBLISHED", gost_drawing__iexact=gost).values_list(
                    "id", flat=True
                )[:2]
            )
        if len(product_ids) != 1 and mpn:
            product_ids = list(
                Product.objects.filter(status__code="PUBLISHED", manufacturer_part_number__iexact=mpn).values_list(
                    "id", flat=True
                )[:2]
            )
        if len(product_ids) == 1:
            resolved[src.pk] = product_ids[0]
    return resolved


def _resolve_ai_catalog_matches(request_items, resolved: dict) -> Tuple[int, list]:
    """Augment `resolved` in place with FUZZY AI matches for lines still unmatched after the exact
    pass. Returns (how many were auto-bound, telemetry rows) — ADR-0006 Move 3, the AI half.

    Auto-binds ONLY the top candidate and ONLY when its confidence ≥ AI_DRAFT_MATCH_CONFIDENCE (a
    high bar) — and only INTO A DRAFT the seller reviews + edits before sending. That review is the
    human-in-the-loop step: unlike a buyer-submitted заявка (which is final), a mis-bound draft line
    is seen and corrected before the КП goes out, so a confident auto-bind here is safe. Lower-
    confidence lines are left unmatched for the manual Smart Match. AI disabled / no key / any API
    error → no-op (the exact-matched draft is already useful; the accelerator must never break it).

    Telemetry rows carry the top candidate for EVERY line the AI answered — including
    below-threshold ones (auto_bound=False): those rows are what lets `ai_match_report` evaluate
    lower thresholds against the seller's eventual manual matches (AI-калибровка)."""
    if not getattr(settings, "AI_IMPORT_ENABLED", False):
        return 0, []
    pending = [src for src in request_items if not src.product_id and src.pk not in resolved]
    if not pending:
        return 0, []
    lines = [
        {
            "name": src.imported_raw_name or "",
            "name_canonical": src.name_canonical or "",
            "gost_drawing": src.gost_drawing or "",
            "mpn": src.mpn or "",
        }
        for src in pending
    ]
    try:
        from ai.services.matching import match_lines_to_catalog

        matches = match_lines_to_catalog(lines)
    except Exception as exc:  # noqa: BLE001 — an AI/API failure must never break the (already useful) draft
        logger.warning("AI draft match failed; keeping exact matches only: %s", exc)
        return 0, []
    threshold = float(getattr(settings, "AI_DRAFT_MATCH_CONFIDENCE", 0.9))
    added = 0
    telemetry = []
    for match in matches:
        idx = match.get("line_index")
        candidates = match.get("candidates") or []
        if not candidates or not isinstance(idx, int) or not (0 <= idx < len(pending)):
            continue
        src = pending[idx]
        top = candidates[0]
        confidence = float(top.get("confidence") or 0)
        auto_bound = confidence >= threshold
        if auto_bound:
            resolved[src.pk] = top["product_id"]
            added += 1
        telemetry.append(
            {
                "src_pk": src.pk,
                "line_raw": src.imported_raw_name or src.name_canonical or "",
                "product_id": top["product_id"],
                "confidence": confidence,
                "threshold": threshold,
                "auto_bound": auto_bound,
            }
        )
    return added, telemetry


def _run_draft_quote_gates(deal_id: int, actor: CustomUser):
    """Read-only gate checks shared by generate_draft_quote, prepare_quote_from_request and the
    pre-enqueue validation (ARCH-01): actor role, deal existence, own-company staff, request lines.
    No writes, no LLM. (The paid ai.draft entitlement / credit gate was removed in M1-ERP-02
    wave 2 — the action is decided by the role permission.)

    Returns (deal, request_items, seller_company_id, error_code) — error_code None when clear.
    """
    from accounts.services.permissions import can_edit_quote_pricing, is_seller, primary_seller_company_id

    if not (getattr(actor, "is_superuser", False) or can_edit_quote_pricing(actor)):
        return None, None, None, "ONLY_SELLER_CAN_BUILD_QUOTE"
    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        return None, None, None, "DEAL_NOT_FOUND"
    if not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, None, None, "MEMBER_REQUIRED_FOR_ACTION"
    request_items = _request_items(deal)
    if not request_items:
        return deal, [], None, "NO_REQUEST_LINES"
    seller_company_id = primary_seller_company_id(actor)
    return deal, request_items, seller_company_id, None


def validate_draft_quote_gates(deal_id: int, actor: CustomUser) -> Optional[str]:
    """Cheap pre-enqueue validation for the async draft-КП endpoint (ARCH-01): the same gates
    as generate_draft_quote, run before queueing so the view can 4xx without a paid LLM call.
    The worker re-runs them inside generate_draft_quote."""
    _deal, _request_items, _seller_company_id, err = _run_draft_quote_gates(deal_id, actor)
    return err


def generate_draft_quote(deal_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str], int]:
    """Build a pre-filled draft КП for `actor`'s seller company from the deal's client request.
    Returns (quote, error_code, prefilled_count). The quote is a fresh DRAFT owned by the actor's
    seller company — never touches the buyer request."""
    deal, request_items, seller_company_id, err = _run_draft_quote_gates(deal_id, actor)
    if err:
        return None, err, 0

    # Move 3: bind still-unmatched lines to catalog products BEFORE pricing (so pricing-assist
    # covers them too) — first deterministically by exact GOST/MPN, then a fuzzy AI pass for
    # high-confidence raw-text matches. ARCH-01: both passes consume the buyer's request LINES
    # (pre-existing rows) — nothing created below — so the LLM call is hoisted OUT of the atomic
    # block and no longer holds a DB transaction open for up to AI_REQUEST_TIMEOUT seconds.
    resolved_matches = _resolve_exact_catalog_matches(request_items)
    ai_matched, ai_telemetry = _resolve_ai_catalog_matches(request_items, resolved_matches)

    with transaction.atomic():
        quote, prefilled = _create_prefilled_quote(
            deal,
            actor,
            seller_company_id,
            request_items,
            resolved_matches,
            ai_telemetry=ai_telemetry,
            ai_matched=ai_matched,
        )
    quote.refresh_from_db()
    return quote, None, prefilled


def _create_prefilled_quote(
    deal, actor, seller_company_id, request_items, resolved_matches, *, ai_telemetry=None, ai_matched=0
):
    """The DETERMINISTIC draft-КП builder shared by the AI path (generate_draft_quote) and the
    no-AI path (prepare_quote_from_request, W2): create the seller's DRAFT quote, copy the buyer
    request lines, bind resolved catalog matches, prefill prices from the seller's own offers,
    recalc totals. Must run inside transaction.atomic. Returns (quote, prefilled_count)."""
    version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1
    quote = Quote.objects.create(
        deal=deal,
        version=version,
        prepared_by=actor,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT),
        seller_company_id=seller_company_id,
    )
    # КП-level defaults (Incoterm / VAT / margin / validity) from the seller's CompanySettings.
    if seller_company_id:
        from accounts.models import Company

        from .quotes import apply_company_quote_defaults

        apply_company_quote_defaults(quote, Company.objects.filter(pk=seller_company_id).first())

    effective_ids = [it.product_id or resolved_matches.get(it.pk) for it in request_items]
    pricing = (
        suggest_pricing_for_products([pid for pid in effective_ids if pid], seller_company_id)
        if seller_company_id
        else {}
    )
    prefilled = 0
    auto_matched = 0
    item_by_src_pk = {}
    for line_index, src in enumerate(request_items):
        data = {field: getattr(src, field) for field in _LINE_FIELDS}
        # Explicit row order on the new КП grid, following the buyer's request order (request
        # lines default position=0 — copying that would pile every line at the top once the
        # seller starts reordering). One deterministic pass = stable grid on first open.
        data["position"] = line_index
        if not data["product_id"]:
            resolved_pid = resolved_matches.get(src.pk)
            if resolved_pid:
                data["product_id"] = resolved_pid
                auto_matched += 1
        product_id = data["product_id"]
        offer = pricing.get(product_id) if product_id else None
        if offer:
            data["frozen_base_price"] = Decimal(offer["base_price"])  # str (JSON-safe) → Decimal field
            data["lead_time_days"] = offer["lead_time_days"]
            if offer["currency"]:
                from master_data.models import Currency

                data["frozen_currency"] = Currency.objects.filter(code=offer["currency"]).first()
            prefilled += 1
        # Bug fix (владелец 27-07): a line WITHOUT its own offer currency inherits the КП
        # cost-currency default — the seller's «валюта себестоимости» setting — exactly like a
        # manually-added line (useQuoteBuilderActions), instead of silently defaulting to UZS.
        # Never overrides an offer's real currency.
        if not data.get("frozen_currency") and quote.cost_currency_default_id:
            data["frozen_currency_id"] = quote.cost_currency_default_id
        item_by_src_pk[src.pk] = QuoteItem.objects.create(quote=quote, **data)

    if ai_telemetry:
        from .ai_telemetry import record_draft_match_outcomes

        record_draft_match_outcomes(quote, ai_telemetry, item_by_src_pk)

    if auto_matched:
        logger.info(
            "draft КП %s: auto-matched %s line(s) to catalog (%s exact GOST/MPN, %s fuzzy AI)",
            quote.id,
            auto_matched,
            auto_matched - ai_matched,
            ai_matched,
        )

    from .quotes import QuoteCalculationService

    QuoteCalculationService.recalculate_quote(quote.id)
    return quote, prefilled


def prefill_created_quote(quote: Quote) -> int:
    """W2 fix (разрыв №4): a freshly-created MANUAL КП copies the buyer's request lines instead of
    starting empty (lines + exact GOST/MPN binds + own-offer prices — deterministic, no AI). Only fills a quote that has NO items yet (never clobbers duplication flows); a deal
    without request lines is a no-op. Returns the number of copied lines."""
    if not quote.deal_id or quote.items.exists():
        return 0
    request_items = _request_items(quote.deal)
    if not request_items:
        return 0
    resolved_matches = _resolve_exact_catalog_matches(request_items)
    effective_ids = [it.product_id or resolved_matches.get(it.pk) for it in request_items]
    pricing = (
        suggest_pricing_for_products([pid for pid in effective_ids if pid], quote.seller_company_id)
        if quote.seller_company_id
        else {}
    )
    for line_index, src in enumerate(request_items):
        data = {field: getattr(src, field) for field in _LINE_FIELDS}
        data["position"] = line_index
        if not data["product_id"]:
            data["product_id"] = resolved_matches.get(src.pk)
        offer = pricing.get(data["product_id"]) if data["product_id"] else None
        if offer:
            data["frozen_base_price"] = Decimal(offer["base_price"])
            data["lead_time_days"] = offer["lead_time_days"]
            if offer["currency"]:
                from master_data.models import Currency

                data["frozen_currency"] = Currency.objects.filter(code=offer["currency"]).first()
        # Same «валюта себестоимости» inheritance as _create_prefilled_quote (владелец 27-07).
        if not data.get("frozen_currency") and quote.cost_currency_default_id:
            data["frozen_currency_id"] = quote.cost_currency_default_id
        QuoteItem.objects.create(quote=quote, **data)

    from .quotes import QuoteCalculationService

    QuoteCalculationService.recalculate_quote(quote.id)
    return len(request_items)


def prepare_quote_from_request(deal_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str], int]:
    """W2 no-AI path: the same prefilled draft КП (lines copied, EXACT GOST/MPN matches bound,
    prices from the seller's own offers) WITHOUT the AI fuzzy pass — used when AI is switched off
    (``settings.AI_IMPORT_ENABLED``). Deterministic logic only: no LLM call."""
    deal, request_items, seller_company_id, err = _run_draft_quote_gates(deal_id, actor)
    if err:
        return None, err, 0
    resolved_matches = _resolve_exact_catalog_matches(request_items)
    with transaction.atomic():
        quote, prefilled = _create_prefilled_quote(deal, actor, seller_company_id, request_items, resolved_matches)
    quote.refresh_from_db()
    return quote, None, prefilled


# Deal stages the one-click button operates in: the pre-КП working set. QUOTE_SENT and later
# stages already have a КП in flight — the short path must not fork a parallel draft there.
_TAKEABLE_STAGES = ("RFQ_OPEN", "SOURCING", "CALCULATING")


def take_and_prepare_quote(deal_id: int, actor: CustomUser) -> Tuple[Optional[dict], Optional[str]]:
    """W2 «одна кнопка» (one-click-quotation, Odoo pattern): claim + stage advance + a prefilled
    draft КП in ONE action, collapsing the 4–6 manual steps across two screens.

    Orchestration of EXISTING services (no FSM bypass, no duplicated gates):
      1. claim_deal — the actor takes the заявка (no-op when already self-owned;
         refuses when a teammate owns it).
      2. transition_deal_stage → CALCULATING (RFQ_OPEN→CALCULATING is a legal single FSM hop —
         one buyer notification, not two).
      3. Idempotency: the actor company's existing КП short-circuits — pressing the button
         twice never forks a second КП.
      4. Mode: with AI switched on (``settings.AI_IMPORT_ENABLED``) → {"mode": "ai"} — the VIEW
         enqueues the existing draft_quote job (202+poll); with AI off → the deterministic
         prefilled КП synchronously ({"mode": "quote", "quote": ...}). The paid ai.draft
         entitlement that used to pick the mode was removed in M1-ERP-02 wave 2.

    АТОМАРНО (FIX-67): сначала — только проверки (права, строки заявки, стадия, чужой исполнитель),
    ничего не пишущие; затем claim + стадия + КП в одной транзакции, и отказ на любом шаге откатывает
    предыдущие. Раньше при ``NO_REQUEST_LINES`` заявка уже была назначена и переведена в CALCULATING.

    Returns ({"deal", "mode", "quote"|None}, None) or (None, error_code).
    """
    error = _take_and_prepare_preflight(deal_id, actor)
    if error:
        return None, error
    with transaction.atomic():
        result, error = _take_and_prepare_steps(deal_id, actor)
        if error:
            transaction.set_rollback(True)  # claim и стадия — вместе с отказом, не по отдельности
            return None, error
    return result, None


def _take_and_prepare_preflight(deal_id: int, actor: CustomUser) -> Optional[str]:
    """Все отказы, которые можно знать ДО изменений (без записи): права, строки заявки, стадия, исполнитель."""
    from accounts.services import is_seller

    if not is_seller(actor):
        return "MEMBER_REQUIRED_FOR_ACTION"
    deal, _items, _seller_company_id, error = _run_draft_quote_gates(deal_id, actor)
    if error:
        return error
    if deal.assigned_to_id and deal.assigned_to_id != actor.id:
        return "DEAL_ALREADY_CLAIMED"
    if (deal.stage.code if deal.stage_id else None) not in _TAKEABLE_STAGES:
        return "DEAL_STAGE_NOT_TAKEABLE"
    return None


def _take_and_prepare_steps(deal_id: int, actor: CustomUser) -> Tuple[Optional[dict], Optional[str]]:
    """Шаги с записью; вызывается внутри `transaction.atomic()` — вызывающий откатывает при ошибке."""
    from accounts.services.permissions import primary_seller_company_id
    from crm.constants import DealStageCode

    from .assignment import claim_deal
    from .deals import transition_deal_stage

    deal, err = claim_deal(deal_id, actor)
    if err:
        return None, err

    stage_code = deal.stage.code if deal.stage_id else None
    if stage_code not in _TAKEABLE_STAGES:
        return None, "DEAL_STAGE_NOT_TAKEABLE"
    if stage_code != DealStageCode.CALCULATING:
        deal, err = transition_deal_stage(deal, DealStageCode.CALCULATING, actor)
        if err:
            return None, err

    # Idempotency: the own company's КП already exists → reuse it, never fork a duplicate.
    seller_company_id = primary_seller_company_id(actor)
    existing = (
        deal.quotes.exclude(prepared_by__isnull=True)
        .filter(seller_company_id=seller_company_id)
        .order_by("-version")
        .first()
        if seller_company_id
        else None
    )
    if existing is not None:
        return {"deal": deal, "mode": "quote", "quote": existing}, None

    if getattr(settings, "AI_IMPORT_ENABLED", False):
        return {"deal": deal, "mode": "ai", "quote": None}, None

    quote, err, _prefilled = prepare_quote_from_request(deal_id, actor)
    if err:
        return None, err
    return {"deal": deal, "mode": "quote", "quote": quote}, None
