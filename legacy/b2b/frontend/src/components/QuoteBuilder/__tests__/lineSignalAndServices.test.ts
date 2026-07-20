import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';

import { lineSignalOf } from '../lineSignal';
import { isServiceLine, usePricingMirror, type LineMirror } from '../usePricingMirror';
import { buildDuplicatePayload } from '../duplicatePayload';
import type { QuoteItem } from '@/api/crmApi';

function makeMirrorLine(overrides: Partial<LineMirror> = {}): LineMirror {
	return {
		isDraft: false, needsServerRecalc: false, usedMarketFx: false,
		landedCost: '800', finalPriceExclVat: '1000', lineTotal: '1000',
		marginPct: 20, profit: '200', belowCost: false, belowFloor: false,
		...overrides,
	};
}

function makeItem(overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id: 1, quote: 100, imported_raw_name: 'Позиция', quantity: 1,
		frozen_base_price: '1000', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '500',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '1500', final_price_excl_vat: '1500',
		...overrides,
	} as QuoteItem;
}

function renderMirror(items: QuoteItem[], dirtyIds: Set<number>) {
	return renderHook(() => usePricingMirror({
		draftItems: items,
		dirtyIds,
		marginPercent: '0',
		vatRate: '12',
		fxSnapshot: {},
		fxManual: {},
		fxMarket: {},
		charges: [],
		canViewCost: true,
		minMarginPercent: null,
		serverTotals: {
			subtotalExclVat: '0', chargesTotal: '0', vatAmount: '0', totalInclVat: '0',
			grossMarginPercent: null,
		},
	}));
}

describe('lineSignalOf (DT4 — hoisted out of the row body)', () => {
	it('narrows a resolved mirror line to the advisory chip fields', () => {
		expect(lineSignalOf(makeMirrorLine({ marginPct: 12.5, profit: '125', belowFloor: true })))
			.toEqual({ marginPct: 12.5, profit: '125', belowCost: false, belowFloor: true });
	});

	it('returns null when the margin is unknown (cost hidden / FX unresolved)', () => {
		expect(lineSignalOf(makeMirrorLine({ marginPct: null }))).toBeNull();
		expect(lineSignalOf(makeMirrorLine({ profit: null }))).toBeNull();
	});
});

describe('isServiceLine + the SERVICES landed-cost preview (DT9)', () => {
	it('flags a line bound to a SERVICES-domain product', () => {
		expect(isServiceLine({ product_domain: 'SERVICES' })).toBe(true);
		expect(isServiceLine({ product_domain: 'RAILWAY' })).toBe(false);
		expect(isServiceLine({ product_domain: undefined })).toBe(false);
	});

	it('a dirty GOODS line still adds customs duty to landed_cost', () => {
		const item = makeItem({ product_domain: 'RAILWAY' });
		const { result } = renderMirror([item], new Set([1]));
		// (1000 base + 500 customs) × fx 1
		expect(result.current.lineFor(item).landedCost).toBe('1500');
	});

	it('a dirty SERVICES line drops customs duty, mirroring calculate_item_prices', () => {
		const item = makeItem({ product_domain: 'SERVICES' });
		const { result } = renderMirror([item], new Set([1]));
		// The server zeroes customs for a service — the preview must not overstate it as 1500.
		expect(result.current.lineFor(item).landedCost).toBe('1000');
	});

	it('a CLEAN SERVICES line still reports the server figures verbatim', () => {
		const item = makeItem({ product_domain: 'SERVICES' });
		const { result } = renderMirror([item], new Set());
		expect(result.current.lineFor(item).landedCost).toBe('1500');
	});
});

describe('DT6 — bulk-create payload needs no cast', () => {
	it('a duplicate payload is structurally a bulk-create row (assignable, not cast)', () => {
		const payload = buildDuplicatePayload(makeItem({ imported_raw_name: 'Болт' }), ' (копия)');
		// The compile-time claim (assignability to the endpoint's Record contract) is what removed
		// the `as unknown as` at the call site; assert it holds at runtime too.
		const asRow: Record<string, unknown> = payload;
		expect(asRow.imported_raw_name).toBe('Болт (копия)');
		expect(asRow).not.toHaveProperty('id');
		expect(asRow).not.toHaveProperty('landed_cost');
		expect(asRow).not.toHaveProperty('final_price_excl_vat');
	});
});
