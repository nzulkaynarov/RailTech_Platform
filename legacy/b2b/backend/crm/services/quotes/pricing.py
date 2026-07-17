"""КП financial engine: per-line price calculation, FX resolution, full-quote
recalculation and seller-side unit economics.

Split out of the monolithic ``crm/services/quotes.py`` (ARCH refactor) — behaviour
unchanged. Depends only on the leaf ``_shared`` helpers, so no circular import with
the lifecycle / bulk / access submodules.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import models, transaction

from crm.models import Quote, QuoteItem, QuoteItemHistory

from ._shared import _quote_owner_company_id


def effective_quote_lead_time(quote, items=None) -> int:
    """Effective КП delivery lead time (days): the manual override on the КП if set,
    otherwise max(line lead_time_days) — the КП is fully delivered when the slowest
    line is ready. `items` may be a pre-fetched list to avoid a re-query; otherwise the
    КП's items are read. Returns 0 when there is no override and no line has a lead time.
    """
    if quote.delivery_lead_time_days is not None:
        return quote.delivery_lead_time_days
    rows = items if items is not None else quote.items.all()
    # Only real, included priced lines drive the КП delivery time — SECTION/NOTE rows have no
    # срок, and an optional line is quoted outside the offer, so it must not stretch the term.
    return max(
        (row.lead_time_days for row in rows if row.display_type == QuoteItem.DisplayType.ITEM and not row.is_optional),
        default=0,
    )


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
        # SECTION/NOTE are presentation rows (group header / free-text), not priced lines — they
        # carry no cost inputs and never contribute to any total. Zero their price fields and skip
        # the whole pipeline so a stray frozen_base_price on such a row can never leak into a sum.
        if item.display_type != QuoteItem.DisplayType.ITEM:
            item.logistics_cost = Decimal("0")
            item.landed_cost = Decimal("0")
            item.final_price_excl_vat = Decimal("0")
            if commit:
                item.save(update_fields=["landed_cost", "final_price_excl_vat", "logistics_cost"])
            return item

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
        # ONLY real priced lines feed the subtotal: display_type=ITEM AND NOT optional. SECTION/
        # NOTE are presentation rows; optional ITEMs are shown with a price but quoted OUTSIDE the
        # totals (доп. предложение). Same filter drives economics/margin below — optional never
        # distorts the seller's margin governance.
        totals = quote.items.filter(display_type=QuoteItem.DisplayType.ITEM, is_optional=False).aggregate(
            subtotal=models.Sum(models.F("final_price_excl_vat") * models.F("quantity"))
        )
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
    # Economics mirror the subtotal filter: only the priced, non-optional ITEM lines count toward
    # COGS / margin / the FX-missing guard. SECTION/NOTE carry no cost; an optional line is quoted
    # outside the totals, so its (real) cost must not drag the seller's margin governance.
    items = list(
        quote.items.select_related("frozen_currency").filter(display_type=QuoteItem.DisplayType.ITEM, is_optional=False)
    )
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
