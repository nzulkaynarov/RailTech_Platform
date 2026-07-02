import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Tuple

from django.db import models, transaction
from django.db.models import Count, Sum

from accounts.constants import SystemRoleCode, VerificationStatusCode, WorkspaceRoleCode
from accounts.models import Company, CompanyMember, CustomUser
from accounts.services.permissions import has_workspace_role, routed_seller_company_id
from core.audit import log_admin_action

from ..constants import DealStageCode, QuoteStatusCode
from ..models import ActivityLog, Deal, Quote, QuoteItem, QuoteItemHistory, QuoteStatus
from ._params import has_explicit_company_role_perm
from .availability import resolve_seller_offer, split_line_by_availability
from .deals import transition_deal_stage

logger = logging.getLogger(__name__)


def _quote_owner_company_id(quote) -> Optional[int]:
    """Company that owns the КП — the seller team that runs the approval chain and whose
    requisites brand the document.

    Source of truth is the explicit `Quote.seller_company` FK, set at build/claim time to the
    VERIFIED routed seller (audit F0/H2). Read FIRST so the role checks, ВЭД/director gate,
    auto-split, PDF header and КП-number minting all resolve to ONE coherent company — never
    "validate against routed company B but anchor to the preparer's primary company A".
    Falls back to the preparer's primary membership ONLY for legacy quotes saved before the FK
    existed. None if neither is resolvable (unclaimed buyer request)."""
    if quote.seller_company_id:
        return quote.seller_company_id
    if not quote.prepared_by_id:
        return None
    membership = (
        CompanyMember.objects.filter(user_id=quote.prepared_by_id, is_primary=True, is_active=True)
        .only("company_id")
        .first()
    )
    return membership.company_id if membership else None


def _quote_seller_company(quote):
    """The issuing (seller) Company for the КП document header — the preparer's
    owning company. None when the КП is still an unclaimed buyer request (no preparer),
    in which case the PDF header falls back to the platform name."""
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None
    return Company.objects.filter(pk=company_id).first()


def _seller_document_profile(seller_company):
    """The selling company's branded document requisites for the КП header — or None.

    Only returns a profile when the seller has actually filled it in (at least a legal
    name or a logo); an empty auto-created profile yields None so the template cleanly
    falls back to the seller Company fields / platform name. Read-only — never creates.
    """
    from accounts.models import CompanyDocumentProfile

    if seller_company is None:
        return None
    profile = CompanyDocumentProfile.objects.filter(company=seller_company).first()
    if profile is None:
        return None
    has_content = bool((profile.legal_name or "").strip() or profile.logo or (profile.bank_details or "").strip())
    return profile if has_content else None


def apply_company_quote_defaults(quote: Quote, company: Optional[Company]) -> Quote:
    """Pre-fill a freshly-CREATED КП from the seller company's CompanySettings.

    Only fills fields the company has actually configured (non-None), and ONLY on a
    brand-new quote — never overwrites a value already set on the quote. Applied to:
    delivery_basis, quote cost_currency_default, vat_rate, margin_percent and
    valid_until (= today + default_offer_validity_days). No-op when the company has no
    settings configured. Reads settings via a plain filter (no write on read).
    """
    if company is None:
        return quote
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import CompanySettings

    settings_row = CompanySettings.objects.filter(company=company).first()
    if settings_row is None:
        return quote

    changed = []
    if settings_row.default_delivery_basis_id and quote.delivery_basis_id is None:
        quote.delivery_basis_id = settings_row.default_delivery_basis_id
        changed.append("delivery_basis")
    if settings_row.default_cost_currency_id and quote.cost_currency_default_id is None:
        quote.cost_currency_default_id = settings_row.default_cost_currency_id
        changed.append("cost_currency_default")
    # vat_rate / margin_percent have non-null model defaults; only override when the
    # quote still carries the bare model default AND the company configured a value.
    if settings_row.default_vat_rate is not None and quote.vat_rate == Decimal("12.00"):
        quote.vat_rate = settings_row.default_vat_rate
        changed.append("vat_rate")
    if settings_row.default_margin_percent is not None and quote.margin_percent == Decimal("0"):
        quote.margin_percent = settings_row.default_margin_percent
        changed.append("margin_percent")
    if settings_row.default_offer_validity_days is not None and quote.valid_until is None:
        quote.valid_until = timezone.now().date() + timedelta(days=settings_row.default_offer_validity_days)
        changed.append("valid_until")

    if changed:
        quote.save(update_fields=[*changed, "updated_at"])
    return quote


def _set_quote_status(quote, code: str) -> None:
    # .get (not get_or_create): the status MUST exist from the seed migration.
    quote.status = QuoteStatus.objects.get(code=code)
    quote.save(update_fields=["status", "updated_at"])


def _notify_quote_outcome(quote, *, type_code: str, title: str, message: str) -> None:
    """Tell the seller side a client decided on a КП (approved/rejected).

    Targets the КП author `prepared_by` (reliably set) plus a distinct
    `deal.manager` if one is assigned — in the single-seller model deal.manager
    is usually empty, so the old manager-only notification never reached anyone.
    Pushed over WS via push_notification_ws for realtime delivery.
    """
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    recipient_ids = {quote.prepared_by_id, quote.deal.manager_id} - {None}
    if not recipient_ids:
        return
    ntype = NotificationType.objects.filter(code=type_code).first()
    for uid in recipient_ids:
        notif = Notification.objects.create(
            user_id=uid, type=ntype, title=title, message=message, link="/crm/deals", deal=quote.deal
        )
        push_notification_ws(notif)


def _log_quote(quote, actor, action: str, detail: str = "") -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=quote.id,
    )


# Which КП statuses each WorkspaceRole is responsible for advancing — drives the
# per-role "my approval queue".
_ROLE_QUEUE_STATUSES = {
    WorkspaceRoleCode.SALES_MANAGER: {QuoteStatusCode.DRAFT},
    WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST: {QuoteStatusCode.PENDING_TRADE_REVIEW},
    WorkspaceRoleCode.DIRECTOR: {QuoteStatusCode.PENDING_APPROVAL},
    WorkspaceRoleCode.OWNER: {
        QuoteStatusCode.DRAFT,
        QuoteStatusCode.PENDING_TRADE_REVIEW,
        QuoteStatusCode.PENDING_APPROVAL,
        QuoteStatusCode.READY_TO_SEND,
    },
}


def can_send_quote_to_client(actor, quote) -> bool:
    """Who may push an internally-approved КП out to the client.

    The platform admin / superuser (escalation), or the SALES_MANAGER / OWNER of
    the company that owns the КП (the preparer's company that ran the approval
    chain). Mirrors ADR-0002: the seller team builds AND sends its own quotes;
    sending is no longer platform-admin-only. The READY_TO_SEND status guard
    itself stays in QuoteLifecycleService.send_to_client.

    Permission hardening (additive, defense-in-depth): also accepts a member
    holding the explicit 'quote.send' CompanyRole permission — this satisfies the
    new Role+Permission-set model while keeping the legacy WorkspaceRole path as
    a fallback for members not yet migrated to a CompanyRole.
    """
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_platform_admin", False):
        return True
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return False
    # has_workspace_role already lets OWNER through as the escape hatch.
    # has_explicit_company_role_perm is additive: passes ONLY when an explicit
    # CompanyRole is assigned with the quote.send permission — it does NOT fall back
    # to legacy can_sell (which would incorrectly promote all default members).
    return has_workspace_role(actor, company_id, [WorkspaceRoleCode.SALES_MANAGER]) or has_explicit_company_role_perm(
        actor, company_id, "quote.send"
    )


def approval_queue_for(user):
    """КП waiting on THIS user's pending approval STEP (unified step-based chain).

    A КП is in my queue when it is PENDING_APPROVAL, has a PENDING acting step at the
    CURRENT stage (lowest pending order), that step is in a company I belong to, and I hold
    the step's permission (quote.review for an intermediate, quote.approve_final for the head).
    """
    from accounts.constants import Permission
    from accounts.services.permissions import member_has_permission
    from crm.models import QuoteApprovalStep
    from crm.models.approvals import StepParticipation, StepStatus

    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    if not company_ids:
        return Quote.objects.none()

    steps = (
        QuoteApprovalStep.objects.filter(
            status=StepStatus.PENDING, quote__status__code=QuoteStatusCode.PENDING_APPROVAL
        )
        .exclude(participation=StepParticipation.INFORMED)
        .select_related("quote", "quote__status", "quote__seller_company", "quote__prepared_by")
        .order_by("quote_id", "order")
    )
    active_order_by_quote: dict = {}
    actionable_quote_ids: set = set()
    for step in steps:
        quote = step.quote
        company_id = _quote_owner_company_id(quote)
        if company_id not in company_ids:
            continue
        # steps are ordered by order asc → the first seen for a quote is its active (min) order
        active = active_order_by_quote.setdefault(quote.id, step.order)
        if step.order != active:
            continue
        perm = (
            Permission.QUOTE_APPROVE_FINAL.value
            if step.participation == StepParticipation.HEAD
            else Permission.QUOTE_REVIEW.value
        )
        if member_has_permission(user, company_id, perm):
            actionable_quote_ids.add(quote.id)
    return (
        Quote.objects.filter(id__in=actionable_quote_ids)
        .select_related("deal", "deal__company", "status", "prepared_by")
        .order_by("-updated_at")
    )


def effective_quote_lead_time(quote, items=None) -> int:
    """Effective КП delivery lead time (days): the manual override on the КП if set,
    otherwise max(line lead_time_days) — the КП is fully delivered when the slowest
    line is ready. `items` may be a pre-fetched list to avoid a re-query; otherwise the
    КП's items are read. Returns 0 when there is no override and no line has a lead time.
    """
    if quote.delivery_lead_time_days is not None:
        return quote.delivery_lead_time_days
    rows = items if items is not None else quote.items.all()
    return max((row.lead_time_days for row in rows), default=0)


def _positive_fx_rate(value):
    """Parse a stored FX rate; return Decimal ONLY if strictly positive, else None.
    A stray 0 / negative / non-numeric (e.g. a hand-edited fx_manual) is ignored rather than
    used to zero or flip a line's landed cost (adversarial HOLE 1). The serializer rejects such
    values on write; this is the defensive read for any pre-existing bad data."""
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return rate if rate > 0 else None


class QuoteCalculationService:
    """
    Centralized engine for financial calculations.
    Ensures consistency between QuoteItems and Quote totals.
    """

    @staticmethod
    def calculate_item_prices(item: QuoteItem, commit=True, basis=..., margin_percent=None, rate=None):
        """
        Calculates Landed Cost and Final Price for a single item.
        Formula:
          1. landed_cost (UZS) = (base + customs duty) × FX-rate   — F3.8 + multi-currency
          2. final_price = landed_cost * (1 + margin%) * (1 − discount%)

        Multi-currency: the per-line base price (frozen_base_price) is denominated in the
        line's cost currency (item.frozen_currency, e.g. USD/EUR/RUB). `rate` is that
        currency's UZS rate (resolved ONCE in recalculate_quote — no N+1 lookup here). The
        customs_duty is treated as entered in the SAME line currency and converted together
        (design choice — keeps the per-line cost in one currency; UZS lines use rate=1). All
        downstream amounts (margin, subtotal, charges, VAT, totals) are therefore in UZS =
        quote_currency. When `rate` is None, no conversion is applied (rate 1) — preserves
        the legacy in-memory call path (e.g. unit tests, QuoteItem.save without a quote map).

        `basis` is accepted for call-site compatibility but no longer gates per-line columns:
        freight/insurance/etc. are document-level charges (на всю партию), not per-line. The
        Incoterm basis instead drives which document charges auto-apply (the per-basis global
        ChargeTemplate seed → apply_charge_template_to_quote).
        """
        is_service = item.product and item.product.domain_type and item.product.domain_type.code == "SERVICES"

        # F3.8 (owner directive): the per-line cost is ONLY себестоимость (base) + customs
        # duty (inherently per-line — the rate is set by the line's ТНВЭД/HS code). Freight,
        # insurance, packing and every other shipment cost are document-level charges entered
        # ONCE for the whole batch (см. QuoteCharge / per-basis ChargeTemplate), NOT per line.
        # The table is therefore unified across Incoterms; the chosen basis drives which
        # document charges appear, not which per-line columns show. logistics_cost stays 0.
        item.logistics_cost = Decimal("0")
        if is_service:
            item.customs_duty = Decimal("0")
        # Convert (base + customs), both in the line currency, into UZS via the resolved rate.
        fx_rate = Decimal("1") if rate is None else Decimal(str(rate))
        item.landed_cost = ((item.frozen_base_price + item.customs_duty) * fx_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # себестоимость → +наценка (маржа на ВЕСЬ КП) → −скидка позиции. Маржа приходит из
        # quote.margin_percent; прямые вызовы без неё падают на позиционное значение (задел).
        effective_margin = item.margin_percent if margin_percent is None else margin_percent
        margin_mult = Decimal("1") + (effective_margin / Decimal("100"))
        discount_mult = Decimal("1") - (item.discount_percent / Decimal("100"))
        item.final_price_excl_vat = (item.landed_cost * margin_mult * discount_mult).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if commit:
            item.save(update_fields=["landed_cost", "final_price_excl_vat", "logistics_cost", "customs_duty"])

        return item

    @staticmethod
    def _resolve_fx_rate_map(quote, items) -> dict:
        """Resolve {currency_code: Decimal rate_to_uzs} for every DISTINCT line cost
        currency on the КП, ONCE (no per-line lookup). Priority per currency:
          1. quote.fx_manual[code]   — КП-level manual override (договорной курс), wins.
          2. quote.fx_snapshot[code] — already frozen on a prior recalc (no market drift).
          3. master_data.fx.get_rate_to_uzs(code) — current market rate; WRITTEN BACK into
             fx_snapshot so it freezes from now on.
        UZS (and a missing currency) → rate 1. Mutates quote.fx_snapshot in place; the
        caller persists it. Returns {code: Decimal}.
        """
        from master_data.fx import get_rate_to_uzs

        snapshot = quote.fx_snapshot if isinstance(quote.fx_snapshot, dict) else {}
        manual = quote.fx_manual if isinstance(quote.fx_manual, dict) else {}
        rate_map: dict = {}
        codes = {(item.frozen_currency.code if item.frozen_currency_id else "UZS").upper() for item in items}
        for code in codes:
            if code in ("UZS", ""):
                rate_map[code] = Decimal("1")
                continue
            manual_rate = _positive_fx_rate(manual.get(code))
            if manual_rate is not None:
                rate_map[code] = manual_rate
                continue
            snapshot_rate = _positive_fx_rate(snapshot.get(code))
            if snapshot_rate is not None:
                rate_map[code] = snapshot_rate
                continue
            market = get_rate_to_uzs(code)
            if market is None:
                # KP-01: NO rate available. Use 1 as an in-memory placeholder so recalc doesn't
                # crash — but DO NOT freeze it into the snapshot. Freezing a fabricated 1 would
                # understate cost ~12000× AND permanently shadow the real rate once it lands in
                # the DB. compute_quote_economics().fx_missing flags it; submit/send is blocked.
                rate_map[code] = Decimal("1")
                continue
            resolved = Decimal(str(market))
            rate_map[code] = resolved
            # Freeze the REAL market rate onto the КП so the total can't drift on the next recalc.
            snapshot[code] = str(resolved)
        quote.fx_snapshot = snapshot
        return rate_map

    @classmethod
    @transaction.atomic
    def recalculate_quote(cls, quote_id: int):
        """
        Full recalculation of a Quote and all its items.
        Prevents N+1 updates by using aggregation.
        """
        # of=("self",): lock only the quote row — select_related pulls the NULLABLE
        # delivery_basis via an outer join, and Postgres can't FOR UPDATE that side.
        quote = Quote.objects.select_for_update(of=("self",)).select_related("delivery_basis").get(pk=quote_id)
        items = list(quote.items.select_related("product__domain_type", "frozen_currency").all())

        # 0. Resolve the FX rate map ONCE for all distinct line cost currencies and freeze
        #    newly-resolved rates into quote.fx_snapshot (persisted in step 4 below).
        rate_map = cls._resolve_fx_rate_map(quote, items)

        # 1. Recalculate each item price (without saving each time to DB yet). Pass the basis
        #    and per-currency rate once so the Incoterm flag-gating + FX conversion run
        #    without an N+1 on item.quote / rate lookup (M1/M2).
        for item in items:
            line_code = (item.frozen_currency.code if item.frozen_currency_id else "UZS").upper()
            cls.calculate_item_prices(
                item,
                commit=False,
                basis=quote.delivery_basis,
                margin_percent=quote.margin_percent,
                rate=rate_map.get(line_code, Decimal("1")),
            )

        # 1b. Effective КП lead time = override or max(line lead times). Computed here off
        #     the already-fetched items (no extra query); the override on the КП is NEVER
        #     overwritten — the derived value is presentation, exposed via the serializer /
        #     Quote.effective_delivery_lead_time_days. (Helper centralises the rule — Rule 8.)
        quote.effective_lead_time_cached = effective_quote_lead_time(quote, items)

        # 2. Bulk update items to minimize DB hits
        QuoteItem.objects.bulk_update(items, ["landed_cost", "final_price_excl_vat", "logistics_cost", "customs_duty"])

        # 2b. Record audit trail snapshots for changed items
        history_records = [
            QuoteItemHistory(
                quote_item=item,
                frozen_base_price=item.frozen_base_price,
                logistics_cost=item.logistics_cost,
                customs_duty=item.customs_duty,
                margin_percent=item.margin_percent,
                discount_percent=item.discount_percent,
                landed_cost=item.landed_cost,
                final_price_excl_vat=item.final_price_excl_vat,
                quantity=item.quantity,
                change_reason="recalculation",
            )
            for item in items
        ]
        if history_records:
            QuoteItemHistory.objects.bulk_create(history_records)

        # 3. Aggregation for Quote totals (use QuerySet, not list).
        # UBL 2.1: LineExtensionAmount (Σ позиций) + document-level AllowanceCharge
        # (Σ статей расхода со знаком) = TaxExclusiveAmount → +НДС → TaxInclusiveAmount.
        totals = quote.items.aggregate(subtotal=models.Sum(models.F("final_price_excl_vat") * models.F("quantity")))
        subtotal = totals["subtotal"] or Decimal("0")

        # Ставка НДС берётся из КП (заморожена из БД), не хардкодится в коде.
        vat_rate = quote.vat_rate / Decimal("100")

        penny = Decimal("0.01")
        quote.subtotal_excl_vat = subtotal.quantize(penny, rounding=ROUND_HALF_UP)

        # CASCADE (sequential pricing, SAP-style): statьи расхода применяются СВЕРХУ ВНИЗ по
        # sort_order. Каждая % статья считается от РАСТУЩЕГО итога (позиции + подписанные статьи
        # выше неё) — так «комиссия 10%» берётся от всего итога над ней, «скидка выше комиссии»
        # уменьшает базу комиссии и т.д. Порядок несущий; менеджер двигает строки. % уже считаем
        # от квантованной базы (no sub-копеечный дрейф). KP-03: пошаговый max(running, 0) держит
        # tax_exclusive ≥ 0 И не даёт нижестоящему % считаться от отрицательной базы.
        running = quote.subtotal_excl_vat
        for charge in quote.charges.all():  # Meta.ordering = [sort_order, id]
            base_before = running
            signed = charge.resolve_signed(base_before).quantize(penny, rounding=ROUND_HALF_UP)
            running = max(running + signed, Decimal("0"))
            # Transparency snapshot for the UI / UBL (BaseAmount / Amount).
            charge.resolved_base = base_before
            charge.resolved_amount = signed
            # skip_recalculate: we ARE inside recalc — saving a charge must not re-trigger it.
            charge.save(update_fields=["resolved_base", "resolved_amount"], skip_recalculate=True)
        quote.charges_total = (running - quote.subtotal_excl_vat).quantize(penny, rounding=ROUND_HALF_UP)
        tax_exclusive = running.quantize(penny, rounding=ROUND_HALF_UP)
        quote.vat_amount = (tax_exclusive * vat_rate).quantize(penny, rounding=ROUND_HALF_UP)
        quote.total_incl_vat = tax_exclusive + quote.vat_amount

        quote.save(
            update_fields=[
                "subtotal_excl_vat",
                "charges_total",
                "vat_amount",
                "total_incl_vat",
                # FX snapshot freezes any newly-resolved market rate so the total can't drift.
                "fx_snapshot",
                "updated_at",
            ]
        )
        return quote


def compute_quote_economics(quote) -> dict:
    """Seller-side unit economics for the КП (панель «Экономика сделки»).

    Uses the SAME stored values the engine produced (no re-derivation of price): per-line
    landed_cost × qty for COGS; the КП's subtotal/charges/totals as-is. Margin is reported as
    GROSS MARGIN ON PRICE (profit/price) — the governance metric — plus markup-on-cost for
    reference. operating_profit subtracts the seller's REAL cost of charges (QuoteCharge.
    cost_amount, default = billed), so a КП billed below its true cost shows the loss.
    `below_cost` is the hard-stop flag; `below_floor` drives the warn+approval path.
    Returns Decimals (the serializer/JSON layer stringifies)."""
    items = list(quote.items.select_related("frozen_currency").all())
    total_landed_cost = sum((it.landed_cost * it.quantity for it in items), Decimal("0")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    subtotal = quote.subtotal_excl_vat or Decimal("0")
    charges_total = quote.charges_total or Decimal("0")
    tax_exclusive = subtotal + charges_total

    # FX guard (KP-01): distinct non-UZS line currencies with NO resolvable rate (neither a
    # manual override, a frozen snapshot, nor a current market rate). Such a line was priced at
    # the in-memory placeholder rate 1 → landed cost silently understated. This list blocks
    # submit/send and warns the manager — we never let a fabricated rate 1 freeze into the КП.
    from master_data.fx import get_rate_to_uzs

    manual = quote.fx_manual if isinstance(quote.fx_manual, dict) else {}
    snapshot = quote.fx_snapshot if isinstance(quote.fx_snapshot, dict) else {}
    fx_missing: list = []
    _seen_ccy: set = set()
    for line in items:
        ccy = (line.frozen_currency.code if line.frozen_currency_id else "UZS").upper()
        if ccy in ("UZS", "") or ccy in _seen_ccy:
            continue
        _seen_ccy.add(ccy)
        # A POSITIVE manual override or frozen snapshot satisfies the rate (a stray 0/negative
        # is ignored — HOLE 1). Otherwise fall back to the market; None there → genuinely missing.
        if _positive_fx_rate(manual.get(ccy)) is not None or _positive_fx_rate(snapshot.get(ccy)) is not None:
            continue
        if get_rate_to_uzs(ccy) is None:
            fx_missing.append(ccy)

    gross_profit = subtotal - total_landed_cost
    gross_margin_pct = (gross_profit / subtotal * Decimal("100")) if subtotal > 0 else Decimal("0")
    markup_pct = (gross_profit / total_landed_cost * Decimal("100")) if total_landed_cost > 0 else Decimal("0")

    # Seller's REAL cost of the charges: explicit cost_amount when set, else the cascade-billed
    # amount (resolved_amount) as pass-through (billed = cost → nets to zero in operating profit).
    # Deductions (discounts) are a revenue reduction, not a cost → skipped.
    charge_cost_total = Decimal("0")
    for charge in quote.charges.all():
        if charge.is_deduction:
            continue
        if charge.cost_amount is not None:
            charge_cost_total += charge.cost_amount
        elif charge.resolved_amount is not None:
            charge_cost_total += charge.resolved_amount
    charge_cost_total = charge_cost_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    operating_profit = tax_exclusive - total_landed_cost - charge_cost_total

    # Seller company's margin governance thresholds (gross-margin-on-price). Fall back to the
    # model defaults when the КП has no resolvable owner / settings yet.
    from accounts.models import CompanySettings

    company_id = _quote_owner_company_id(quote)
    settings_row = CompanySettings.objects.filter(company_id=company_id).first() if company_id else None
    min_margin = settings_row.min_margin_percent if settings_row else Decimal("15")
    target_margin = settings_row.target_margin_percent if settings_row else Decimal("25")

    return {
        "total_landed_cost": total_landed_cost,
        "gross_profit": gross_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "gross_margin_percent": gross_margin_pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "markup_percent": markup_pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
        "charge_cost_total": charge_cost_total,
        "operating_profit": operating_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        # KP-02: a real loss is operating_profit < 0 — i.e. the buyer's tax-exclusive price does
        # not cover landed cost PLUS the seller's real cost of the charges. The old lines-only
        # test (tax_exclusive < total_landed_cost) was masked by any buyer-billed +charge (the
        # charge revenue inflated tax_exclusive) → a loss-making КП slipped past the G1 gate.
        "below_cost": tax_exclusive < (total_landed_cost + charge_cost_total),
        "below_floor": subtotal > 0 and gross_margin_pct < min_margin,
        "min_margin_percent": min_margin,
        "target_margin_percent": target_margin,
        "fx_missing": fx_missing,
    }


def get_crm_analytics_data():
    """LOW-4: Extracted analytics logic from views to service."""
    deals = Deal.objects.all()
    items = QuoteItem.objects.all()

    pipeline_by_status = list(deals.values("stage__name").annotate(count=Count("id")))
    sourcing_backlog = items.filter(product__isnull=True).count()

    total_items = items.count()
    mapped_items = items.filter(product__isnull=False).count()
    mapped_items_percentage = (mapped_items / total_items * 100) if total_items > 0 else 0

    kyc_backlog = Company.objects.filter(
        verification_status__code__in=[VerificationStatusCode.L1_UNVERIFIED, VerificationStatusCode.PROFILE_SUBMITTED]
    ).count()

    total_pipeline_value = (
        Quote.objects.filter(status__code__in=[QuoteStatusCode.SENT, QuoteStatusCode.APPROVED]).aggregate(
            total=Sum("total_incl_vat")
        )["total"]
        or 0
    )

    return {
        "pipeline_by_status": pipeline_by_status,
        "sourcing_backlog": sourcing_backlog,
        "kyc_backlog": kyc_backlog,
        "total_pipeline_value": float(total_pipeline_value),
        "mapped_items_percentage": round(mapped_items_percentage, 1),
    }


class QuoteLifecycleService:
    """Manages Quote state transitions: generate PDF, send, approve, reject."""

    @staticmethod
    @transaction.atomic
    def generate_pdf(quote_id: int) -> Quote:
        """Generate PDF for a quote using WeasyPrint."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from django.template.loader import render_to_string
        from weasyprint import HTML

        quote = (
            Quote.objects.select_related(
                "deal__company", "status", "tax_country", "prepared_by", "quote_currency", "delivery_basis"
            )
            .prefetch_related("items__product__domain_type")
            .get(pk=quote_id)
        )

        # Issuer (seller) block for a branded offer header — the company that owns the КП
        # (the preparer's seller company). An unclaimed buyer-request КП (prepared_by NULL)
        # has NO issuing seller, so rendering it would brand a "коммерческое предложение"
        # with the platform identity ("RailTech B2B") — misrepresenting the supplier on a
        # commercial document. Refuse to render until a seller has claimed it (audit F1).
        seller_company = _quote_seller_company(quote)
        if seller_company is None:
            raise ValueError("QUOTE_NOT_CLAIMED")
        # HOLE 2 (loss-prevention): the render/export surface was the gate bypass — a seller could
        # generate a КП PDF on a DRAFT at the placeholder rate 1 (or below cost) and hand it to the
        # client out-of-band, never touching submit/send. Refuse to render a client КП document
        # whose numbers are wrong (no FX rate) or loss-making — the same gate as send_to_client.
        _econ = compute_quote_economics(quote)
        if _econ["fx_missing"]:
            raise ValueError("FX_RATE_MISSING")
        if _econ["below_cost"]:
            raise ValueError("QUOTE_BELOW_COST")
        # The seller's filled-in document profile (legal name, requisites, logo, footer).
        # When present, the «Поставщик» block + header logo + footer render from it; when
        # absent the template falls back to the seller Company fields → platform name.
        seller_profile = _seller_document_profile(seller_company)
        seller_logo_url = None
        if seller_profile and seller_profile.logo:
            try:
                seller_logo_url = seller_profile.logo.url
            except (ValueError, OSError):  # storage backend unavailable / missing key
                seller_logo_url = None

        # Move 4 monetization: a seller in DEMO for quote.send may BUILD + preview the КП, but the
        # rendered document is watermarked «ДЕМО — не для коммерческого использования» (send/export
        # stay gated by quote_send_entitled). The template overlays it when is_demo is truthy.
        from accounts.constants import FeatureKey
        from accounts.services.entitlements import is_demo

        html_string = render_to_string(
            "crm/quote_pdf.html",
            {
                "quote": quote,
                "items": quote.items.select_related("product", "frozen_currency").all(),
                "company": quote.deal.company,
                "seller": seller_company,
                "seller_profile": seller_profile,
                "seller_logo_url": seller_logo_url,
                "is_demo": is_demo(seller_company.id, FeatureKey.QUOTE_SEND),
            },
        )

        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)

        filename = f"KP_{quote.deal.company.inn}_{quote.deal_id}_v{quote.version}.pdf"
        quote.pdf_file.save(filename, ContentFile(pdf_file.getvalue()), save=True)

        return quote

    @staticmethod
    @transaction.atomic
    def send_to_client(quote_id: int, sent_by_user) -> Quote:
        """
        Send quote to client:
        1. Guard: only READY_TO_SEND (internally approved) quotes can be sent
        2. Generate PDF if not exists
        3. Set frozen_at timestamp
        4. Change status to SENT
        5. Change deal stage to QUOTE_SENT via FSM
        6. Create notification for client
        """
        from django.utils import timezone

        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related("deal__company", "deal__client", "deal__stage", "status").get(pk=quote_id)

        # Status guard: only an internally-approved КП (READY_TO_SEND — it passed
        # the sales → ВЭД → director chain) may go out to the client.
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.READY_TO_SEND:
            raise ValueError(
                f"Cannot send quote in status '{current}'. "
                "Only READY_TO_SEND quotes (internally approved) can be sent to the client."
            )

        # An unclaimed КП has no issuing seller (e.g. the preparer's membership was deactivated
        # after the КП was claimed) — refuse to send rather than freeze it under the PLATFORM
        # identity, mint a platform-branded number, and then have the async PDF render fail
        # (audit M2). Mirrors the generate_pdf QUOTE_NOT_CLAIMED guard so the failure surfaces
        # synchronously to the sender. A superuser send is the platform-escalation/orchestrator
        # path (no company membership by design) and is allowed through with platform branding.
        seller_company = _quote_seller_company(quote)
        if seller_company is None and not getattr(sent_by_user, "is_superuser", False):
            raise ValueError("QUOTE_NOT_CLAIMED")

        # MONETIZATION GATE (ADR-0006 Move 4): sending a КП to the client is a PAID action. The
        # seller's company must hold the quote.send entitlement — an operational subscription grants it
        # by default, so paying sellers are unaffected; a demo/unsubscribed seller can build the КП
        # but not send it. Superuser = platform escalation, allowed through.
        if seller_company is not None and not getattr(sent_by_user, "is_superuser", False):
            from accounts.services import quote_send_entitled

            if not quote_send_entitled(seller_company.id):
                raise ValueError("QUOTE_SEND_NOT_ENTITLED")

        # LOSS PREVENTION (authoritative server gate): never send a КП priced below its landed
        # cost — even if items/charges were edited after the internal approval. Mirrors the
        # live G1 guardrail in the builder; can't be bypassed via the API.
        # A value-less КП (no priced lines) must not go to the client even if it carries charges
        # (HOLE 4 — submit had this guard, send did not; items can change after READY_TO_SEND).
        if (quote.subtotal_excl_vat or 0) <= 0:
            raise ValueError("QUOTE_HAS_UNPRICED_LINES")
        _econ = compute_quote_economics(quote)
        if _econ["fx_missing"]:
            raise ValueError("FX_RATE_MISSING")
        if _econ["below_cost"]:
            raise ValueError("QUOTE_BELOW_COST")

        # Mint the public no-login access token once (idempotent across re-sends of the
        # same КП version). Lets an offline/registered client open the client projection
        # without an account; rotate only by issuing a new version.
        import secrets

        if not quote.public_access_token:
            quote.public_access_token = secrets.token_urlsafe(32)

        # Mint a human, sequential, quotable КП number on first send (idempotent across
        # re-sends of the same version) — world-standard B2B: every offer the buyer receives
        # carries a citable document number, per-company-prefixed (ACME-КП-2026-00001) or the
        # shared platform counter (КП-2026-00001). Re-using next_document_number keeps the КП
        # consistent with Contract/Invoice/Act numbering.
        if not quote.number:
            from .numbering import next_document_number

            quote.number = next_document_number("KP", "КП", seller_company)

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code=QuoteStatusCode.SENT).first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=["status", "number", "frozen_at", "public_access_token", "updated_at"])

        # Email the КП off the request thread, after commit (F1.6 — no render inside the
        # atomic block, no orphan on rollback). The task renders the PDF if needed, then
        # emails it (with the public link) to the recipient — registered client OR offline
        # contact. Unified send: one action, channel adapts to who the recipient is.
        from ..tasks import send_quote_email

        transaction.on_commit(lambda: send_quote_email.delay(quote_id))

        # Change deal stage via FSM. P0-1: the real buyer path lands the deal in RFQ_OPEN, and
        # QUOTE_SENT is only legal from CALCULATING — so advance through CALCULATING first, and
        # CAPTURE the error instead of swallowing it. Previously the error was discarded: the КП
        # was marked SENT + emailed while the deal silently stayed in RFQ_OPEN forever (dead-end).
        deal = quote.deal
        current_stage = deal.stage.code if deal.stage else None
        if current_stage in (DealStageCode.RFQ_OPEN, DealStageCode.SOURCING):
            _, stage_err = transition_deal_stage(
                deal, DealStageCode.CALCULATING, actor=sent_by_user, reason="Сборка КП к отправке"
            )
            if stage_err:
                raise ValueError(stage_err)
        _, stage_err = transition_deal_stage(
            deal,
            DealStageCode.QUOTE_SENT,
            actor=sent_by_user,
            reason=f"КП v{quote.version} отправлено клиенту",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Create notification for client contact
        if quote.deal.client:
            info_type = NotificationType.objects.filter(code="INFO").first()
            Notification.objects.create(
                user=quote.deal.client,
                type=info_type,
                title="Новое коммерческое предложение",
                message=f"Вам отправлено КП v{quote.version} по сделке #{quote.deal_id}",
                link="/cabinet/deals",
                deal=quote.deal,
            )

        return quote

    @staticmethod
    @transaction.atomic
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Client approves the quote. Only SENT quotes can be approved."""
        from django.utils import timezone

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot approve quote in status '{current}'. " "Only SENT quotes can be approved.")

        approved_status = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

        # Change deal stage via FSM (P0-1: capture the error — don't swallow it).
        _, stage_err = transition_deal_stage(
            quote.deal,
            DealStageCode.CONTRACT_SIGNED,
            actor=approved_by_user,
            reason=f"КП v{quote.version} одобрено клиентом",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Materialize the Contract the instant the buyer accepts — otherwise the deal sits in
        # CONTRACT_SIGNED with NO actual Contract (audit B1: approve → green badge → dead-end,
        # generate_contract_from_quote was only ever called from tests). actor=None = system
        # path: the buyer's approval triggers it, and the buyer is not a seller so it must NOT
        # go through the seller-actor guard. Best-effort — a render hiccup must not unwind the
        # approval (the seller can re-issue from the contract surface).
        from .contracts import generate_contract_from_quote

        try:
            generate_contract_from_quote(quote.id, actor=None)
        except (ValueError, OSError) as exc:  # noqa: BLE001 — narrow: lookup/PDF render
            logger.warning("Contract auto-generation after approval failed for quote %s: %s", quote.id, exc)

        # Notify the seller who built the КП (and a distinct manager, if assigned)
        # that the client approved. deal.manager is usually unset in the single-
        # seller model, so prepared_by is the reliable recipient — without it the
        # seller never learned the outcome. Pushed over WS for realtime delivery.
        _notify_quote_outcome(
            quote,
            type_code="SUCCESS",
            title="КП одобрено клиентом",
            message=f"{quote.deal.company.name} одобрил КП v{quote.version}",
        )

        return quote

    # ── Internal approval chain (документооборот) ──────────────────────────
    # DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND → (send).
    # Each step is gated by the actor's WorkspaceRole in the company that owns the
    # КП (the preparer's company); OWNER may act on any step. Returns
    # (quote, None) on success or (None, error_code) for views to map to HTTP.

    @staticmethod
    @transaction.atomic
    def submit_for_review(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """Sales submits a built КП into the chain. DRAFT → PENDING_TRADE_REVIEW,
        or straight to PENDING_APPROVAL if the company has no ВЭД member."""
        quote = Quote.objects.select_related("status", "prepared_by", "deal").get(pk=quote_id)
        # Resolve the КП-owning company WITHOUT mutating anything first (audit F0):
        #   • already-claimed КП → the preparer's company;
        #   • unclaimed buyer-request КП → the submitter MAY claim it, but ONLY if they are
        #     a can_sell seller routed to THIS deal. Anchoring prepared_by before this check
        #     let any authenticated user (even a buyer) hijack the КП + drive its approval
        #     chain cross-tenant, and the write committed even on a rejected call.
        if quote.prepared_by_id:
            company_id = _quote_owner_company_id(quote)
            if not company_id:
                return None, "NO_QUOTE_COMPANY"
        else:
            company_id = routed_seller_company_id(actor, quote.deal_id)
            if not company_id:
                return None, "ROLE_NOT_PERMITTED"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.SALES_MANAGER]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.DRAFT:
            return None, "INVALID_STATUS"
        # A commercial offer cannot enter the approval chain with NO value: reject a КП whose
        # total is zero/negative (the "half-priced / unpriced КП" gap — it could otherwise be
        # approved and sent to the client at 0,00). Keyed on the КП TOTAL (not per-line) so a
        # deliberately-free line (included item, sample, 100% promo discount) among priced lines
        # is still allowed — only a genuinely value-less offer is blocked (audit M6).
        if (quote.subtotal_excl_vat or 0) <= 0:
            return None, "QUOTE_HAS_UNPRICED_LINES"
        # LOSS PREVENTION (hard stop): a КП whose client total is below its landed cost would be
        # sold at a loss — never allow it into the approval chain. Below the margin FLOOR is a
        # softer signal (warn + approval on the client side), NOT a hard block here.
        _econ = compute_quote_economics(quote)
        if _econ["fx_missing"]:
            return None, "FX_RATE_MISSING"
        if _econ["below_cost"]:
            return None, "QUOTE_BELOW_COST"
        # All gates passed — NOW it is safe to claim the КП: anchor BOTH the preparer and the
        # owning seller company to the VERIFIED company resolved above (audit F0/H2), so the
        # rest of the chain, the document header and the КП number all resolve to ONE coherent
        # company — never "validated against routed B but anchored to primary A".
        claim_fields = []
        if not quote.prepared_by_id:
            quote.prepared_by = actor
            claim_fields.append("prepared_by")
        if not quote.seller_company_id:
            quote.seller_company_id = company_id
            claim_fields.append("seller_company")
        if claim_fields:
            quote.save(update_fields=[*claim_fields, "updated_at"])
        # ATP auto-split (Track B): the КП is built and leaving DRAFT — split every
        # product line whose seller stock can't cover the requested qty into наличие +
        # под заказ tranches, in one pass (no per-line clicks). Idempotent: an already-
        # split set is left alone, so re-submitting after a send-back never re-splits.
        from .availability import auto_split_quote_by_availability

        auto_split_quote_by_availability(quote, company_id)
        # Unified approval workflow: build the permission-driven step list (mandatory head +
        # optional reviewer(s) + risk-aware reason), then route. Source of truth = the steps,
        # not a granular status — the КП goes to a single «На согласовании» (PENDING_APPROVAL).
        from .approvals import _active_order, _notify_order, build_approval_chain

        build_approval_chain(quote, company_id, economics=_econ)
        _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
        first_order = _active_order(quote)
        if first_order is not None:
            _notify_order(quote, first_order)
        _log_quote(quote, actor, "quote.submit_for_review", f"КП v{quote.version} на согласование (цепочка построена)")
        return quote, None

    @staticmethod
    @transaction.atomic
    def confirm_trade_review(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """ВЭД confirms. PENDING_TRADE_REVIEW → PENDING_APPROVAL."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.PENDING_TRADE_REVIEW:
            return None, "INVALID_STATUS"
        _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
        _log_quote(
            quote, actor, "quote.confirm_trade_review", f"КП v{quote.version} подтверждено ВЭД → PENDING_APPROVAL"
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def director_approve(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """Director approves internally. PENDING_APPROVAL → READY_TO_SEND."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.DIRECTOR]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
            return None, "INVALID_STATUS"
        _set_quote_status(quote, QuoteStatusCode.READY_TO_SEND)
        _log_quote(quote, actor, "quote.director_approve", f"КП v{quote.version} утверждено директором → READY_TO_SEND")
        return quote, None

    @staticmethod
    @transaction.atomic
    def send_back(quote_id: int, actor: CustomUser, reason: str = "") -> Tuple[Optional[Quote], Optional[str]]:
        """Return a КП under review to sales for rework. Any review status → DRAFT.
        Allowed for ВЭД, DIRECTOR (and OWNER)."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(
            actor, company_id, [WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST, WorkspaceRoleCode.DIRECTOR]
        ):
            return None, "ROLE_NOT_PERMITTED"
        review_states = {
            QuoteStatusCode.PENDING_TRADE_REVIEW,
            QuoteStatusCode.PENDING_APPROVAL,
            QuoteStatusCode.READY_TO_SEND,
        }
        if not quote.status or quote.status.code not in review_states:
            return None, "INVALID_STATUS"
        # LEAK FIX: the rework reason is INTERNAL — it goes to the audit log only, NEVER into
        # quote.notes (which is rendered verbatim in the CLIENT-facing КП PDF «Примечания»).
        _set_quote_status(quote, QuoteStatusCode.DRAFT)
        _log_quote(quote, actor, "quote.send_back", f"КП v{quote.version} возвращено на доработку. {reason}".strip())
        return quote, None

    @staticmethod
    @transaction.atomic
    def force_approve_quote(
        quote_id: int,
        admin_user: CustomUser,
        reason: str = "",
    ) -> Tuple[Optional[Quote], Optional[str]]:
        """Platform-admin force override: approve a quote regardless of its current status.

        Used for escalations (e.g. client unreachable but verbally approved offline).
        Logged with [FORCE_ADMIN] marker so audit can distinguish from normal flow.
        Caller must have SystemRole.ADMIN or be is_superuser. Viewer-mode admins
        (ADMIN without a CompanyMember) are explicitly permitted — force-actions
        are platform-admin moderation, not bound to membership.
        """
        from django.utils import timezone

        if not (
            getattr(admin_user, "is_superuser", False)
            or (admin_user.role and admin_user.role.code == SystemRoleCode.ADMIN)
        ):
            return None, "PLATFORM_ADMIN_REQUIRED"
        if not reason.strip():
            return None, "FORCE_REASON_REQUIRED"
        # of=("self",): Quote.status is a nullable FK, so select_related("status")
        # emits a LEFT OUTER JOIN, and Postgres rejects "FOR UPDATE" on the nullable
        # side of an outer join. Lock only the crm_quote row, not the joined tables.
        quote = Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=quote_id)
        approved = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        if not approved:
            return None, "QUOTE_STATUS_NOT_FOUND"
        old_code = quote.status.code if quote.status else "None"
        quote.status = approved
        quote.approved_at = timezone.now()
        quote.approved_by = admin_user
        # LEAK FIX: the force-override reason + the platform-admin EMAIL must NOT land in
        # quote.notes — that field is rendered verbatim in the CLIENT КП PDF «Примечания». The
        # override is fully captured below in the entity-scoped audit log (log_admin_action).
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        # Structured, entity-scoped audit (G2 Gap A) — route through log_admin_action like
        # transition_deal_stage, so the override carries reason + entity_type/id + before/after
        # and shows on the quote timeline and the «Журнал доступа» page (not a bare ActivityLog).
        log_admin_action(
            entity_type="quote",
            entity_id=quote_id,
            action="[FORCE_ADMIN] КП одобрено платформенным админом",
            detail=f"КП #{quote_id} ({old_code} → APPROVED).",
            actor=admin_user,
            reason=reason,
            before={"status": old_code},
            after={"status": QuoteStatusCode.APPROVED},
            level="WARNING",
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def reject_quote(quote_id: int, rejected_by_user, reason: str = "") -> Quote:
        """Client rejects the quote. Only SENT quotes can be rejected."""

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot reject quote in status '{current}'. " "Only SENT quotes can be rejected.")

        rejected_status = QuoteStatus.objects.filter(code=QuoteStatusCode.REJECTED).first()
        quote.status = rejected_status
        # LEAK FIX: the rejection reason is NOT written to quote.notes (rendered in the client КП
        # PDF). It's preserved on the deal-stage transition audit below + the seller notification.
        quote.save(update_fields=["status", "updated_at"])

        # Move deal back to CALCULATING via FSM (P0-1: capture the error — don't swallow it).
        _, stage_err = transition_deal_stage(
            quote.deal,
            DealStageCode.CALCULATING,
            actor=rejected_by_user,
            reason=f"КП v{quote.version} отклонено. {reason}",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Notify the КП author (+ distinct manager) that the client rejected —
        # same single-seller reasoning as approve_quote. Pushed over WS.
        _notify_quote_outcome(
            quote,
            type_code="WARNING",
            title="КП отклонено клиентом",
            message=f"{quote.deal.company.name} отклонил КП v{quote.version}. {reason}".strip(),
        )

        return quote


# ──────────────────────────────────────────────────────────────────────────
# Re-match (manual reassign QuoteItem.product)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def reassign_quote_item_product(
    quote_item_id: int,
    actor: CustomUser,
    product_id: Optional[int],
) -> Tuple[Optional[QuoteItem], Optional[str]]:
    """Allow manager to override Smart Match result by picking a different product."""
    from accounts.services import is_platform_admin_viewer
    from catalog.models import Product

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    item = QuoteItem.objects.select_for_update().select_related("quote").get(pk=quote_item_id)
    if item.quote.frozen_at:
        return None, "QUOTE_FROZEN_CANNOT_REASSIGN"
    if product_id:
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return None, "PRODUCT_NOT_FOUND"
        item.product = product
        # Inherit ТНВЭД from the product card unless ВЭД already set it manually
        # (the per-line override wins; we only fill an empty code).
        if not (item.hs_code or "").strip() and (product.hs_code or "").strip():
            item.hs_code = product.hs_code
        # Lead-time INHERITANCE (Track B): pull the срок from the seller's OWN offer for
        # this product, but ONLY when the seller hasn't manually set one (0/unset). The
        # per-line override always wins — mirrors the hs_code inheritance above.
        offer = resolve_seller_offer(product, _quote_owner_company_id(item.quote))
        if not item.lead_time_days and offer is not None:
            tranches = split_line_by_availability(product, item.quantity, offer)
            item.lead_time_days = max((tranche.lead_time_days for tranche in tranches), default=0)
    else:
        item.product = None
    item.save(update_fields=["product", "assigned_at", "hs_code", "lead_time_days"])
    ActivityLog.objects.create(
        action="Переназначен продукт в позиции КП",
        detail=f"QuoteItem #{item.id} → Product #{product_id}",
        user=actor,
        level="INFO",
    )
    return item, None
