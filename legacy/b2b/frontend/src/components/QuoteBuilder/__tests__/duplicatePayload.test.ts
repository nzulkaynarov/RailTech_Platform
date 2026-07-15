import { describe, it, expect } from 'vitest';

import type { QuoteItem } from '@/api/crmApi';
import { buildDuplicatePayload } from '@/components/QuoteBuilder/duplicatePayload';

/**
 * WP-J — the bulk-create payload for a duplicated КП line copies only the writable fields
 * (mirror of the backend `_BULK_CREATE_WRITABLE_FIELDS`) and appends a «(копия)» suffix.
 */

const mkItem = (overrides: Partial<QuoteItem> = {}): QuoteItem =>
	({
		id: 7,
		quote: 1,
		imported_raw_name: 'Болт М12',
		quantity: 4,
		frozen_base_price: '1500',
		frozen_currency: 'USD',
		logistics_cost: '50',
		customs_duty: '30',
		margin_percent: '0',
		discount_percent: '5',
		lead_time_days: 14,
		hs_code: '7318',
		landed_cost: '0',
		final_price_excl_vat: '0',
		...overrides,
	}) as QuoteItem;

describe('buildDuplicatePayload', () => {
	it('copies the writable fields and appends the copy suffix to the name', () => {
		const payload = buildDuplicatePayload(mkItem(), ' (копия)');

		expect(payload.imported_raw_name).toBe('Болт М12 (копия)');
		expect(payload.quantity).toBe(4);
		expect(payload.frozen_base_price).toBe('1500');
		expect(payload.frozen_currency).toBe('USD');
		expect(payload.logistics_cost).toBe('50');
		expect(payload.customs_duty).toBe('30');
		expect(payload.discount_percent).toBe('5');
		expect(payload.lead_time_days).toBe(14);
		expect(payload.hs_code).toBe('7318');
	});

	it('never carries the read-only / derived fields (id, landed_cost, final_price_excl_vat, quote)', () => {
		const payload = buildDuplicatePayload(mkItem(), ' (копия)');
		expect('id' in payload).toBe(false);
		expect('landed_cost' in payload).toBe(false);
		expect('final_price_excl_vat' in payload).toBe(false);
		expect('quote' in payload).toBe(false);
	});

	it('omits empty optional text fields and defaults the currency to UZS', () => {
		const payload = buildDuplicatePayload(
			mkItem({ hs_code: '', mpn: '', gost_drawing: '', note: '', frozen_currency: '' }),
			' (копия)',
		);
		expect('hs_code' in payload).toBe(false);
		expect('mpn' in payload).toBe(false);
		expect(payload.frozen_currency).toBe('UZS');
	});
});
