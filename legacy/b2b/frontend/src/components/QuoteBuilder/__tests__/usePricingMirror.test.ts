import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';

import type { QuoteCharge, QuoteItem } from '@/api/crmApi';
import { usePricingMirror, resolveClientFxRate, type PricingMirrorInput } from '@/components/QuoteBuilder/usePricingMirror';

/**
 * WP-F / spec §2 P0-2 — the local pricing mirror. The expected numbers below are
 * computed BY HAND from the backend engine (crm/services/quotes.py):
 *   landed_cost      = (frozen_base_price + customs_duty) × fx_rate            → q2
 *   final_price      = landed_cost × (1 + margin%/100) × (1 − discount%/100)   → q2
 *   Сумма            = final_price × quantity
 *   subtotal         = Σ (final_price × quantity)                              → q2
 *   charge cascade   = running += q2(rate% of running | amount), clamp ≥ 0     (models/charges.py)
 *   vat              = tax_exclusive × vat_rate/100                            → q2
 *   total            = tax_exclusive + vat
 */

const mkItem = (id: number, overrides: Partial<QuoteItem> = {}): QuoteItem =>
	({
		id,
		quote: 1,
		imported_raw_name: `line-${id}`,
		quantity: 1,
		frozen_base_price: '0',
		frozen_currency: 'UZS',
		logistics_cost: '0',
		customs_duty: '0',
		// DT1: `null` = no per-line override → the line INHERITS `input.marginPercent`, which is what
		// every case below is asserting. (It used to be '0' back when the column was NOT NULL and the
		// engine ignored it; under DT1 a literal '0' is an explicit «продать по себестоимости»
		// override that would legitimately zero out the quote-level markup in these expectations.)
		margin_percent: null,
		discount_percent: '0',
		lead_time_days: 0,
		landed_cost: '0',
		final_price_excl_vat: '0',
		...overrides,
	}) as QuoteItem;

const baseInput = (overrides: Partial<PricingMirrorInput> = {}): PricingMirrorInput => ({
	draftItems: [],
	dirtyIds: new Set(),
	marginPercent: '0',
	vatRate: '12',
	fxSnapshot: {},
	fxManual: {},
	fxMarket: {},
	charges: [],
	canViewCost: true,
	minMarginPercent: null,
	serverTotals: {
		subtotalExclVat: '0',
		chargesTotal: '0',
		vatAmount: '0',
		totalInclVat: '0',
		grossMarginPercent: null,
	},
	...overrides,
});

describe('resolveClientFxRate', () => {
	it('is 1 for UZS / empty, the manual override when positive, else the snapshot, else null', () => {
		expect(resolveClientFxRate('UZS', {}, {})!.toString()).toBe('1');
		expect(resolveClientFxRate('', {}, {})!.toString()).toBe('1');
		expect(resolveClientFxRate('USD', { USD: '12800' }, { USD: '12000' })!.toString()).toBe('12800');
		expect(resolveClientFxRate('USD', {}, { USD: '12000' })!.toString()).toBe('12000');
		// A stray non-positive override is ignored (mirrors _positive_fx_rate); no snapshot → null.
		expect(resolveClientFxRate('USD', { USD: '0' }, {})).toBeNull();
		expect(resolveClientFxRate('EUR', {}, {})).toBeNull();
	});

	it('falls back to the preliminary market rate only when neither manual nor snapshot has it', () => {
		// market fills a currency absent from both maps…
		expect(resolveClientFxRate('GBP', {}, {}, { GBP: '15000' })!.toString()).toBe('15000');
		// …but snapshot (and manual) still win over market.
		expect(resolveClientFxRate('USD', {}, { USD: '12000' }, { USD: '15000' })!.toString()).toBe('12000');
		expect(resolveClientFxRate('USD', { USD: '12800' }, {}, { USD: '15000' })!.toString()).toBe('12800');
		// a non-positive market rate is ignored, like the other maps.
		expect(resolveClientFxRate('GBP', {}, {}, { GBP: '0' })).toBeNull();
	});
});

describe('usePricingMirror', () => {
	it('previews a dirty UZS row: landed / final / Сумма / margin exactly per the backend formula', () => {
		// base 1000 + customs 200 = 1200 landed (fx 1); ×1.25 markup ×0.90 discount = 1350 final;
		// Сумма = 1350 × 4 = 5400; cost = 1200 × 4 = 4800; margin = 600/5400 ×100 = 11.111…%
		const item = mkItem(1, {
			frozen_base_price: '1000', customs_duty: '200', discount_percent: '10',
			quantity: 4, landed_cost: '0', final_price_excl_vat: '0',
		});
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([1]), marginPercent: '25', minMarginPercent: 15,
			})),
		);

		const line = result.current.lineFor(item);
		expect(line.isDraft).toBe(true);
		expect(line.needsServerRecalc).toBe(false);
		expect(line.landedCost).toBe('1200');
		expect(line.finalPriceExclVat).toBe('1350');
		expect(line.lineTotal).toBe('5400');
		expect(line.profit).toBe('600');
		expect(line.marginPct).toBeCloseTo(11.1111, 3);
		expect(line.belowCost).toBe(false);
		expect(line.belowFloor).toBe(true); // 11.11% < 15% floor
	});

	it('converts a non-UZS dirty row through the frozen FX snapshot', () => {
		// base 100 USD × 12500 = 1,250,000 landed; ×1.20 markup = 1,500,000 final; Сумма ×2 = 3,000,000.
		const item = mkItem(2, {
			frozen_base_price: '100', frozen_currency: 'USD', quantity: 2,
		});
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([2]), marginPercent: '20',
				fxSnapshot: { USD: '12500' },
			})),
		);
		const line = result.current.lineFor(item);
		expect(line.landedCost).toBe('1250000');
		expect(line.finalPriceExclVat).toBe('1500000');
		expect(line.lineTotal).toBe('3000000');
	});

	it('previews a market-only currency off fx_market and flags it usedMarketFx (preliminary)', () => {
		// base 100 GBP × 15000 = 1,500,000 landed; ×1.20 markup = 1,800,000 final; Сумма ×1 = 1,800,000.
		// GBP is on NEITHER snapshot nor manual — only the preliminary public market map.
		const item = mkItem(4, { frozen_base_price: '100', frozen_currency: 'GBP', quantity: 1 });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([4]), marginPercent: '20',
				fxMarket: { GBP: '15000' },
			})),
		);
		const line = result.current.lineFor(item);
		expect(line.needsServerRecalc).toBe(false);
		expect(line.usedMarketFx).toBe(true);
		expect(line.landedCost).toBe('1500000');
		expect(line.finalPriceExclVat).toBe('1800000');
		expect(line.lineTotal).toBe('1800000');
	});

	it('does NOT flag usedMarketFx when the snapshot already covers the currency', () => {
		// USD is in the snapshot → the frozen rate wins over the market rate; no «market» hint.
		const item = mkItem(5, { frozen_base_price: '100', frozen_currency: 'USD', quantity: 1 });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([5]), marginPercent: '20',
				fxSnapshot: { USD: '12500' }, fxMarket: { USD: '15000' },
			})),
		);
		const line = result.current.lineFor(item);
		expect(line.usedMarketFx).toBe(false);
		expect(line.landedCost).toBe('1250000'); // 100 × 12500, not the 15000 market rate
	});

	it('flags a non-UZS row with NO client-known rate as needsServerRecalc (never faked)', () => {
		const item = mkItem(3, { frozen_base_price: '100', frozen_currency: 'EUR', quantity: 1, final_price_excl_vat: '999' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({ draftItems: [item], dirtyIds: new Set([3]), marginPercent: '20' })),
		);
		const line = result.current.lineFor(item);
		expect(line.needsServerRecalc).toBe(true);
		expect(line.usedMarketFx).toBe(false);
		expect(line.landedCost).toBeNull();
		// «Сумма» still shows the server value so the column isn't blank.
		expect(line.lineTotal).toBe('999');
		// The totals fall back to the server figures (not computable) rather than guess.
		expect(result.current.totals.computable).toBe(false);
	});

	it('recomputes КП totals with the charge cascade and VAT off the dirty preview', () => {
		// One dirty line → subtotal 5400. Freight 10% (charge, +) → 540 → running 5940 = tax-excl.
		// VAT 12% of 5940 = 712.80; total = 6652.80. Gross margin = (5400−4800)/5400 = 11.1%.
		const item = mkItem(1, {
			frozen_base_price: '1000', customs_duty: '200', discount_percent: '10', quantity: 4,
		});
		const charge: QuoteCharge = {
			id: 1, quote: 1, charge_type: 'FREIGHT', amount: '0', rate_percent: '10',
			is_deduction: false, sort_order: 1,
		};
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([1]), marginPercent: '25',
				vatRate: '12', charges: [charge],
			})),
		);
		const totals = result.current.totals;
		expect(totals.computable).toBe(true);
		expect(totals.isDraft).toBe(true);
		expect(totals.subtotalExclVat).toBe('5400');
		expect(totals.chargesTotal).toBe('540');
		expect(totals.vatAmount).toBe('712.8');
		expect(totals.totalInclVat).toBe('6652.8');
		expect(totals.grossMarginPercent).toBeCloseTo(11.1, 5);
	});

	it('reports server values for a clean row and server totals when nothing is dirty', () => {
		const item = mkItem(1, { landed_cost: '1200', final_price_excl_vat: '1350', quantity: 4 });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set(),
				serverTotals: { subtotalExclVat: '5400', chargesTotal: '0', vatAmount: '648', totalInclVat: '6048', grossMarginPercent: 11.1 },
			})),
		);
		const line = result.current.lineFor(item);
		expect(line.isDraft).toBe(false);
		expect(line.lineTotal).toBe('5400');
		expect(result.current.totals.isDraft).toBe(false);
		expect(result.current.totals.totalInclVat).toBe('6048');
	});

	it('without cost visibility a dirty qty edit moves Сумма via the server unit price only', () => {
		// Non-cost-viewer edits quantity 2→5; final unchanged (server 1350) → Сумма 6750. No cost preview.
		const item = mkItem(1, { final_price_excl_vat: '1350', quantity: 5 });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [item], dirtyIds: new Set([1]), canViewCost: false,
			})),
		);
		const line = result.current.lineFor(item);
		expect(line.lineTotal).toBe('6750');
		expect(line.landedCost).toBeNull();
		expect(line.marginPct).toBeNull();
	});
});
