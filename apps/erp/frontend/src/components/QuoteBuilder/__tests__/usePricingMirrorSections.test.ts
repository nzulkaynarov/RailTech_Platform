import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';

import type { QuoteItem } from '@/api/crmApi';
import { usePricingMirror, isBillableItem, type PricingMirrorInput } from '@/components/QuoteBuilder/usePricingMirror';

/**
 * S1 (спека §5 п.19) — the pricing mirror must exclude optional lines and SECTION/NOTE rows
 * from subtotal / НДС / итого / маржа (mirror of the backend `QuoteItem.objects.billable()`), and
 * expose a LIVE подытог per SECTION. These are the «деньги» invariants: the client preview must
 * agree with the server total to the kopeck.
 */

const mkItem = (id: number, overrides: Partial<QuoteItem> = {}): QuoteItem =>
	({
		id,
		quote: 1,
		display_type: 'ITEM',
		is_optional: false,
		imported_raw_name: `line-${id}`,
		quantity: 1,
		frozen_base_price: '0',
		frozen_currency: 'UZS',
		logistics_cost: '0',
		customs_duty: '0',
		// DT1: `null` = no per-line override → the line inherits the КП markup (see the note on the
		// same fixture in usePricingMirror.test.ts). A literal '0' would now mean «по себестоимости».
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
		subtotalExclVat: '999', // deliberately WRONG so a computable result proves it recomputed
		chargesTotal: '0',
		vatAmount: '0',
		totalInclVat: '0',
		grossMarginPercent: null,
	},
	...overrides,
});

describe('isBillableItem', () => {
	it('is true only for a non-optional ITEM; false for optional ITEM / SECTION / NOTE', () => {
		expect(isBillableItem({ display_type: 'ITEM', is_optional: false })).toBe(true);
		expect(isBillableItem({ display_type: undefined, is_optional: false })).toBe(true); // legacy → ITEM
		expect(isBillableItem({ display_type: 'ITEM', is_optional: true })).toBe(false);
		expect(isBillableItem({ display_type: 'SECTION', is_optional: false })).toBe(false);
		expect(isBillableItem({ display_type: 'NOTE', is_optional: false })).toBe(false);
	});
});

describe('usePricingMirror — optional / section exclusion (money)', () => {
	it('excludes an optional line from the subtotal preview but still shows its own «Сумма»', () => {
		// billable: base 1000 × margin0 = 1000 final, qty 2 → 2000. optional: base 500, qty 1 → 500.
		const billable = mkItem(1, { frozen_base_price: '1000', quantity: 2 });
		const optional = mkItem(2, { frozen_base_price: '500', quantity: 1, is_optional: true });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [billable, optional],
				dirtyIds: new Set([1, 2]),
				marginPercent: '0',
			})),
		);
		expect(result.current.totals.computable).toBe(true);
		// subtotal counts ONLY the non-optional billable line — the optional 500 is excluded.
		expect(result.current.totals.subtotalExclVat).toBe('2000');
		// …but the optional row still previews its own line total on the row.
		expect(result.current.lineFor(optional).lineTotal).toBe('500');
		expect(result.current.lineFor(billable).lineTotal).toBe('2000');
	});

	it('an optional row with an unknown FX rate never forces the server fallback', () => {
		const billable = mkItem(1, { frozen_base_price: '1000', quantity: 1 });
		// EUR is on none of the FX maps → needsServerRecalc, but it is optional so must NOT block totals.
		const optionalUnknownFx = mkItem(2, { frozen_base_price: '7', frozen_currency: 'EUR', is_optional: true });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [billable, optionalUnknownFx],
				dirtyIds: new Set([1, 2]),
			})),
		);
		expect(result.current.lineFor(optionalUnknownFx).needsServerRecalc).toBe(true);
		expect(result.current.totals.computable).toBe(true);
		expect(result.current.totals.subtotalExclVat).toBe('1000');
	});

	it('SECTION / NOTE rows contribute nothing to the subtotal', () => {
		const section = mkItem(1, { display_type: 'SECTION', imported_raw_name: 'Механика' });
		const item = mkItem(2, { frozen_base_price: '300', quantity: 4 }); // 1200
		const note = mkItem(3, { display_type: 'NOTE', imported_raw_name: 'сроки уточняются' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({ draftItems: [section, item, note], dirtyIds: new Set([2]) })),
		);
		expect(result.current.totals.subtotalExclVat).toBe('1200');
	});
});

describe('usePricingMirror — section subtotals', () => {
	it('sums the billable lines under each SECTION up to the next SECTION', () => {
		// Section A: items 100×2=200 and 50×1=50 → 250. Section B: item 400×1=400. Optional under B excluded.
		const sectionA = mkItem(1, { display_type: 'SECTION' });
		const a1 = mkItem(2, { final_price_excl_vat: '100', quantity: 2 });
		const a2 = mkItem(3, { final_price_excl_vat: '50', quantity: 1 });
		const sectionB = mkItem(4, { display_type: 'SECTION' });
		const b1 = mkItem(5, { final_price_excl_vat: '400', quantity: 1 });
		const bOptional = mkItem(6, { final_price_excl_vat: '999', quantity: 1, is_optional: true });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [sectionA, a1, a2, sectionB, b1, bOptional],
				dirtyIds: new Set(), // clean rows → serverLine reads final_price_excl_vat
			})),
		);
		expect(result.current.sectionSubtotalFor(sectionA.id)).toBe('250');
		expect(result.current.sectionSubtotalFor(sectionB.id)).toBe('400');
	});

	it('returns null for a SECTION with no billable rows under it', () => {
		const emptySection = mkItem(1, { display_type: 'SECTION' });
		const note = mkItem(2, { display_type: 'NOTE' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({ draftItems: [emptySection, note], dirtyIds: new Set() })),
		);
		expect(result.current.sectionSubtotalFor(emptySection.id)).toBeNull();
	});

	it('tracks a dirty edit live in the section подытог', () => {
		const section = mkItem(1, { display_type: 'SECTION' });
		// dirty base 1000 × margin 25% = 1250 final, qty 2 → 2500.
		const item = mkItem(2, { frozen_base_price: '1000', quantity: 2 });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [section, item],
				dirtyIds: new Set([2]),
				marginPercent: '25',
			})),
		);
		expect(result.current.sectionSubtotalFor(section.id)).toBe('2500');
	});
});
