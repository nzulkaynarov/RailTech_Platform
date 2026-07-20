import { describe, it, expect } from 'vitest';
import type { QuoteItem } from '@/api/crmApi';
import {
	filterQuoteItems, matchesQuoteItemFilter, normalizeFilterQuery,
} from '@/components/QuoteBuilder/filterItems';

/**
 * U4 — the «найти в КП» predicate. The grid's filtered rendering is only as trustworthy as this
 * function, so the matched-field surface, the normalisation and the empty-query identity guarantee
 * are pinned here.
 */

function makeItem(id: number, overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id, quote: 100, display_type: 'ITEM', is_optional: false, position: id,
		imported_raw_name: `Позиция ${id}`, quantity: 1,
		frozen_base_price: '0', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '0', final_price_excl_vat: '0', version: 1,
		...overrides,
	} as QuoteItem;
}

describe('normalizeFilterQuery', () => {
	it('trims, folds inner whitespace and lowercases', () => {
		expect(normalizeFilterQuery('  ГОСТ   1234 ')).toBe('гост 1234');
	});

	it('treats a whitespace-only query as empty (no filter)', () => {
		expect(normalizeFilterQuery('   ')).toBe('');
	});
});

describe('matchesQuoteItemFilter', () => {
	it('matches the free-typed name case-insensitively', () => {
		const item = makeItem(1, { imported_raw_name: 'Рельс Р65 закалённый' });
		expect(matchesQuoteItemFilter(item, 'рельс')).toBe(true);
		expect(matchesQuoteItemFilter(item, 'РЕЛЬС')).toBe(true);
		expect(matchesQuoteItemFilter(item, 'шпала')).toBe(false);
	});

	it('matches the CATALOG name of a bound line, not just the raw import text', () => {
		const item = makeItem(2, { imported_raw_name: 'р65 крив.накл', product: 11, product_name: 'Рельс Р65' });
		expect(matchesQuoteItemFilter(item, 'Рельс')).toBe(true);
	});

	it('matches the identity codes a seller actually searches by (SKU / ГОСТ / MPN / ТН ВЭД)', () => {
		const item = makeItem(3, {
			imported_raw_name: 'без имени',
			product_sku: 'R65-A', product_gost: 'ГОСТ Р 51685', product_mpn: 'MPN-65',
			mpn: 'LINE-MPN', gost_drawing: 'ГОСТ 7174', hs_code: '7302100000',
		});
		for (const query of ['r65-a', 'ГОСТ Р 51685', 'mpn-65', 'line-mpn', 'ГОСТ 7174', '73021']) {
			expect(matchesQuoteItemFilter(item, query)).toBe(true);
		}
		expect(matchesQuoteItemFilter(item, 'нет-такого')).toBe(false);
	});

	it('normalises whitespace on BOTH sides, so «ГОСТ  1234» finds «ГОСТ 1234»', () => {
		const item = makeItem(4, { imported_raw_name: 'Болт ГОСТ 1234 стальной' });
		expect(matchesQuoteItemFilter(item, 'ГОСТ  1234')).toBe(true);
	});

	it('matches SECTION / NOTE text too, so filtering by a heading keeps it visible', () => {
		const section = makeItem(5, { display_type: 'SECTION', imported_raw_name: 'МЕХАНИКА' });
		expect(matchesQuoteItemFilter(section, 'механ')).toBe(true);
	});

	it('an empty query matches everything', () => {
		expect(matchesQuoteItemFilter(makeItem(6), '')).toBe(true);
		expect(matchesQuoteItemFilter(makeItem(6), '   ')).toBe(true);
	});

	it('ignores blank/undefined fields instead of matching on them', () => {
		const item = makeItem(7, { imported_raw_name: 'Шпала', product_sku: '   ' });
		expect(matchesQuoteItemFilter(item, ' ')).toBe(true); // empty query → everything
		expect(matchesQuoteItemFilter(item, 'x')).toBe(false);
	});
});

describe('filterQuoteItems', () => {
	const items = [
		makeItem(1, { imported_raw_name: 'Рельс Р65' }),
		makeItem(2, { imported_raw_name: 'Шпала ЖБ' }),
		makeItem(3, { imported_raw_name: 'Рельс Р50' }),
	];

	it('keeps only matching rows, in document order', () => {
		expect(filterQuoteItems(items, 'рельс').map((item) => item.id)).toEqual([1, 3]);
	});

	it('returns the SAME array reference for an empty query (no needless re-render churn)', () => {
		// The virtualizer count + the selection prune key off this array; allocating a fresh one on
		// every render of the unfiltered (normal) path would churn them for nothing.
		expect(filterQuoteItems(items, '')).toBe(items);
		expect(filterQuoteItems(items, '   ')).toBe(items);
	});

	it('returns an empty list when nothing matches (the grid renders its «не найдено» row)', () => {
		expect(filterQuoteItems(items, 'вагон')).toEqual([]);
	});
});
