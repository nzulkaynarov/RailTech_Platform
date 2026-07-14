import { useMemo } from 'react';
import Decimal from 'decimal.js';
import type { QuoteCharge, QuoteItem } from '@/api/crmApi';
import { toDecimal } from '@/utils/decimal';

/**
 * usePricingMirror (WP-F / spec §2 P0-2 «правка цены не двигает сумму»).
 *
 * The grid used to render each line's «Сумма» and margin from the SERVER-computed
 * `final_price_excl_vat`, which only updates after a save + refetch — so editing a
 * base price, discount or quantity locally left the line total (and the КП totals)
 * frozen until the seller saved. This hook re-derives those numbers LIVE for the
 * dirty rows, on decimal.js, EXACTLY mirroring the backend engine so the preview and
 * the eventual server value agree to the kopeck.
 *
 * Server formulas mirrored (backend/crm/services/quotes.py + models/charges.py):
 *   • landed_cost (UZS)   = (frozen_base_price + customs_duty) × fx_rate        → q2
 *     fx_rate: quote.fx_manual[ccy] || quote.fx_snapshot[ccy] (positive only); UZS = 1.
 *     A non-UZS line whose rate is on NEITHER map is unknown on the client (the server
 *     also consults live market rates) → that row is flagged needsServerRecalc, never faked.
 *   • final_price_excl_vat = landed_cost × (1 + margin%/100) × (1 − discount%/100) → q2
 *     margin% is the QUOTE-level markup (quote.margin_percent), applied to every line.
 *   • Сумма (line total)  = final_price_excl_vat × quantity
 *   • subtotal_excl_vat   = Σ (final_price_excl_vat × quantity)                  → q2
 *   • charges cascade      = SAP-style running total; each charge signed & q2'd, clamped ≥ 0
 *   • vat_amount          = tax_exclusive × vat_rate/100                        → q2
 *   • total_incl_vat      = tax_exclusive + vat_amount
 *
 * Clean (non-dirty) rows always report their SERVER values, so the preview only moves
 * where the seller actually edited. When any dirty row is needsServerRecalc the KP
 * totals fall back to the server figures (computable = false) rather than guess.
 */

// Backend quantizes money to 2 dp with ROUND_HALF_UP at every step — mirror it exactly.
const q2 = (value: Decimal): Decimal => value.toDecimalPlaces(2, Decimal.ROUND_HALF_UP);

/** Positive FX rate for a line cost currency, or null when unknown on the client.
 *  Mirrors `_positive_fx_rate` (a stray 0/negative is ignored, not used). UZS → 1. */
export function resolveClientFxRate(
	code: string | null | undefined,
	fxManual: Record<string, string>,
	fxSnapshot: Record<string, string>,
): Decimal | null {
	const ccy = (code || 'UZS').toUpperCase();
	if (ccy === 'UZS' || ccy === '') return new Decimal(1);
	const manual = Number(fxManual[ccy]);
	if (fxManual[ccy] != null && manual > 0) return new Decimal(fxManual[ccy]);
	const snapshot = Number(fxSnapshot[ccy]);
	if (fxSnapshot[ccy] != null && snapshot > 0) return new Decimal(fxSnapshot[ccy]);
	return null;
}

export interface LineMirror {
	/** This row carries unsaved local edits → the values below are a live preview. */
	isDraft: boolean;
	/** A non-UZS line currency has no client-known FX rate → preview cost/margin withheld. */
	needsServerRecalc: boolean;
	/** Себестоимость preview (UZS); null when not cost-viewable or FX unknown. */
	landedCost: string | null;
	/** Client-facing price per unit excl VAT (always resolvable — falls back to server). */
	finalPriceExclVat: string;
	/** «Сумма» = final × quantity (always resolvable). */
	lineTotal: string;
	/** Gross margin % on price for the per-line chip; null when cost is hidden/unknown. */
	marginPct: number | null;
	/** Line profit (price − cost) over the quantity; null when cost is hidden/unknown. */
	profit: string | null;
	belowCost: boolean;
	belowFloor: boolean;
}

export interface TotalsMirror {
	/** false → a dirty row's FX is unknown; the figures below are the SERVER fallback. */
	computable: boolean;
	/** Any dirty row present (drives the «черновик» marker on the totals). */
	isDraft: boolean;
	subtotalExclVat: string;
	chargesTotal: string;
	vatAmount: string;
	totalInclVat: string;
	/** Gross margin % on price; null when the viewer can't see costs. */
	grossMarginPercent: number | null;
}

export interface PricingMirrorResult {
	/** Live-or-server derived numbers for one row (dirty → preview, clean → server). */
	lineFor: (item: QuoteItem) => LineMirror;
	/** КП totals with the dirty rows' previews folded in (or the server fallback). */
	totals: TotalsMirror;
}

export interface PricingMirrorInput {
	draftItems: QuoteItem[];
	dirtyIds: Set<number>;
	/** Quote-level markup applied to every line (quote.margin_percent). */
	marginPercent: string | number | null | undefined;
	vatRate: string | number | null | undefined;
	fxSnapshot: Record<string, string>;
	fxManual: Record<string, string>;
	charges: QuoteCharge[];
	/** Cost-viewer gate — false hides cost inputs, so only qty edits move «Сумма». */
	canViewCost: boolean;
	/** Company margin floor for the below-floor per-line signal (null hides it). */
	minMarginPercent: number | null;
	/** Server figures — the honest fallback when a preview input is unavailable. */
	serverTotals: {
		subtotalExclVat: string | number | null | undefined;
		chargesTotal: string | number | null | undefined;
		vatAmount: string | number | null | undefined;
		totalInclVat: string | number | null | undefined;
		grossMarginPercent: number | null;
	};
}

/** Per-line preview for a DIRTY row; `null` when the FX rate is unknown on the client. */
function previewDirtyLine(
	item: QuoteItem,
	input: PricingMirrorInput,
): LineMirror {
	const quantity = Number(item.quantity) || 0;
	const serverFinal = toDecimal(item.final_price_excl_vat);

	// Without cost visibility only quantity can have changed — the price is unchanged,
	// so «Сумма» = server final × the (possibly edited) quantity. No cost/margin preview.
	if (!input.canViewCost) {
		return {
			isDraft: true,
			needsServerRecalc: false,
			landedCost: null,
			finalPriceExclVat: serverFinal.toString(),
			lineTotal: serverFinal.mul(quantity).toString(),
			marginPct: null,
			profit: null,
			belowCost: false,
			belowFloor: false,
		};
	}

	const fxRate = resolveClientFxRate(item.frozen_currency, input.fxManual, input.fxSnapshot);
	if (fxRate === null) {
		// Honest marker: we don't know this currency's rate (the server may hit a live market
		// rate) — show the server line total so the column isn't blank, but withhold cost/margin.
		return {
			isDraft: true,
			needsServerRecalc: true,
			landedCost: null,
			finalPriceExclVat: serverFinal.toString(),
			lineTotal: serverFinal.mul(quantity).toString(),
			marginPct: null,
			profit: null,
			belowCost: false,
			belowFloor: false,
		};
	}

	const landed = q2(toDecimal(item.frozen_base_price).plus(toDecimal(item.customs_duty)).mul(fxRate));
	const marginMult = new Decimal(1).plus(toDecimal(input.marginPercent).div(100));
	const discountMult = new Decimal(1).minus(toDecimal(item.discount_percent).div(100));
	const final = q2(landed.mul(marginMult).mul(discountMult));
	const priceTotal = final.mul(quantity);
	const costTotal = landed.mul(quantity);
	const marginPct = priceTotal.gt(0)
		? priceTotal.minus(costTotal).div(priceTotal).mul(100).toNumber()
		: null;
	return {
		isDraft: true,
		needsServerRecalc: false,
		landedCost: landed.toString(),
		finalPriceExclVat: final.toString(),
		lineTotal: priceTotal.toString(),
		marginPct,
		profit: priceTotal.minus(costTotal).toString(),
		belowCost: priceTotal.lt(costTotal),
		belowFloor:
			input.minMarginPercent != null && marginPct != null && marginPct < input.minMarginPercent,
	};
}

/** Per-line numbers straight from the server (used for CLEAN rows). */
function serverLine(item: QuoteItem, input: PricingMirrorInput): LineMirror {
	const quantity = Number(item.quantity) || 0;
	const final = toDecimal(item.final_price_excl_vat);
	const landed = toDecimal(item.landed_cost);
	const priceTotal = final.mul(quantity);
	const costTotal = landed.mul(quantity);
	const canSignal = input.canViewCost && item.landed_cost != null;
	const marginPct = canSignal && priceTotal.gt(0)
		? priceTotal.minus(costTotal).div(priceTotal).mul(100).toNumber()
		: null;
	return {
		isDraft: false,
		needsServerRecalc: false,
		landedCost: canSignal ? landed.toString() : null,
		finalPriceExclVat: final.toString(),
		lineTotal: priceTotal.toString(),
		marginPct,
		profit: marginPct != null ? priceTotal.minus(costTotal).toString() : null,
		belowCost: marginPct != null ? priceTotal.lt(costTotal) : false,
		belowFloor:
			input.minMarginPercent != null && marginPct != null && marginPct < input.minMarginPercent,
	};
}

export function usePricingMirror(input: PricingMirrorInput): PricingMirrorResult {
	const {
		draftItems, dirtyIds, charges, vatRate, canViewCost, serverTotals,
	} = input;

	return useMemo(() => {
		// Per-row map: dirty → preview, clean → server.
		const lineMap = new Map<number, LineMirror>();
		for (const item of draftItems) {
			lineMap.set(item.id, dirtyIds.has(item.id) ? previewDirtyLine(item, input) : serverLine(item, input));
		}

		const lineFor = (item: QuoteItem): LineMirror =>
			lineMap.get(item.id) ?? serverLine(item, input);

		// Totals: recompute only when there IS a dirty edit and every dirty row is computable;
		// otherwise report the server figures (honest fallback — never a fabricated number).
		const anyUnknown = draftItems.some(
			(item) => dirtyIds.has(item.id) && (lineMap.get(item.id)?.needsServerRecalc ?? false),
		);
		const isDraft = dirtyIds.size > 0;

		const serverFallback: TotalsMirror = {
			computable: false,
			isDraft,
			subtotalExclVat: toDecimal(serverTotals.subtotalExclVat).toString(),
			chargesTotal: toDecimal(serverTotals.chargesTotal).toString(),
			vatAmount: toDecimal(serverTotals.vatAmount).toString(),
			totalInclVat: toDecimal(serverTotals.totalInclVat).toString(),
			grossMarginPercent: serverTotals.grossMarginPercent,
		};

		if (!isDraft || anyUnknown) {
			return { lineFor, totals: { ...serverFallback, computable: !isDraft } };
		}

		// subtotal = Σ final × qty across ALL rows (clean=server final, dirty=preview final).
		let subtotal = new Decimal(0);
		let totalLandedCost = new Decimal(0);
		for (const item of draftItems) {
			const line = lineMap.get(item.id)!;
			const quantity = Number(item.quantity) || 0;
			subtotal = subtotal.plus(toDecimal(line.finalPriceExclVat).mul(quantity));
			if (line.landedCost != null) {
				totalLandedCost = totalLandedCost.plus(toDecimal(line.landedCost).mul(quantity));
			} else if (item.landed_cost != null) {
				totalLandedCost = totalLandedCost.plus(toDecimal(item.landed_cost).mul(quantity));
			}
		}
		subtotal = q2(subtotal);

		// SAP-style cascade over the charges (ordered by sort_order, then id) — mirrors
		// recalculate_quote: each charge signed & q2'd off the RUNNING total, clamped ≥ 0.
		const ordered = [...charges].sort(
			(a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id,
		);
		let running = subtotal;
		for (const charge of ordered) {
			const base = charge.rate_percent != null
				? running.mul(toDecimal(charge.rate_percent).div(100))
				: toDecimal(charge.amount);
			const signed = q2(charge.is_deduction ? base.neg() : base);
			running = Decimal.max(running.plus(signed), new Decimal(0));
		}
		const chargesTotal = q2(running.minus(subtotal));
		const taxExclusive = q2(running);
		const vatAmount = q2(taxExclusive.mul(toDecimal(vatRate).div(100)));
		const totalInclVat = taxExclusive.plus(vatAmount);

		// Gross margin on price (governance metric), 1 dp like compute_quote_economics.
		const grossMarginPercent = canViewCost && subtotal.gt(0)
			? subtotal.minus(totalLandedCost).div(subtotal).mul(100).toDecimalPlaces(1, Decimal.ROUND_HALF_UP).toNumber()
			: null;

		return {
			lineFor,
			totals: {
				computable: true,
				isDraft,
				subtotalExclVat: subtotal.toString(),
				chargesTotal: chargesTotal.toString(),
				vatAmount: vatAmount.toString(),
				totalInclVat: totalInclVat.toString(),
				grossMarginPercent,
			},
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [draftItems, dirtyIds, charges, vatRate, canViewCost,
		input.marginPercent, input.minMarginPercent, input.fxManual, input.fxSnapshot,
		serverTotals.subtotalExclVat, serverTotals.chargesTotal, serverTotals.vatAmount,
		serverTotals.totalInclVat, serverTotals.grossMarginPercent]);
}
