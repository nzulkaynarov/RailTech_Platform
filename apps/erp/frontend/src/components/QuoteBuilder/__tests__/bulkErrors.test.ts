import { describe, it, expect } from 'vitest';

import { parseBulkItemErrors, extractBulkErrorRows, cellErrorKey } from '@/components/QuoteBuilder/bulkErrors';

/**
 * WP-F / spec §2 P0-4 — flattening the bulk endpoint's per-row error payload
 *   { detail: "QUOTE_ITEMS_BULK_INVALID", rows: [ { id, index, errors: { field: [CODE] } } ] }
 * into a `${id}:${field}` → CODE map the grid uses to drive aria-invalid + tooltips.
 */
describe('parseBulkItemErrors', () => {
	it('flattens per-row field codes keyed by id:field', () => {
		const rows = [
			{ id: 7, index: 0, errors: { quantity: ['QUOTE_ITEM_QTY_INVALID'], frozen_base_price: ['QUOTE_ITEM_PRICE_TOO_LARGE'] } },
			{ id: 9, index: 1, errors: { frozen_currency: ['CURRENCY_NOT_FOUND'] } },
		];
		const map = parseBulkItemErrors(rows);
		expect(map[cellErrorKey(7, 'quantity')]).toBe('QUOTE_ITEM_QTY_INVALID');
		expect(map[cellErrorKey(7, 'frozen_base_price')]).toBe('QUOTE_ITEM_PRICE_TOO_LARGE');
		expect(map[cellErrorKey(9, 'frozen_currency')]).toBe('CURRENCY_NOT_FOUND');
		expect(Object.keys(map)).toHaveLength(3);
	});

	it('skips malformed rows without crashing (defensive against schema drift)', () => {
		const map = parseBulkItemErrors([
			{ id: null, errors: { quantity: ['X'] } },
			{ id: 5, errors: undefined },
			{ id: 6, errors: { hs_code: 'PLAIN_STRING' } },
			'not-an-object',
		]);
		expect(map[cellErrorKey(6, 'hs_code')]).toBe('PLAIN_STRING');
		expect(Object.keys(map)).toHaveLength(1);
	});

	it('returns an empty map for non-array input', () => {
		expect(parseBulkItemErrors(undefined)).toEqual({});
		expect(parseBulkItemErrors(null)).toEqual({});
	});
});

describe('extractBulkErrorRows', () => {
	it('returns rows from a QUOTE_ITEMS_BULK_INVALID axios error', () => {
		const err = { response: { data: { detail: 'QUOTE_ITEMS_BULK_INVALID', rows: [{ id: 1, errors: {} }] } } };
		expect(extractBulkErrorRows(err)).toEqual([{ id: 1, errors: {} }]);
	});

	it('returns null for any other error shape', () => {
		expect(extractBulkErrorRows({ response: { data: { detail: 'QUOTE_FROZEN' } } })).toBeNull();
		expect(extractBulkErrorRows(new Error('network'))).toBeNull();
		expect(extractBulkErrorRows(null)).toBeNull();
	});
});
