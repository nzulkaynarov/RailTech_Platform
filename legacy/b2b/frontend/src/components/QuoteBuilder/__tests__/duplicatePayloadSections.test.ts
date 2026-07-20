import { describe, it, expect } from 'vitest';

import type { QuoteItem } from '@/api/crmApi';
import { buildDuplicatePayload } from '@/components/QuoteBuilder/duplicatePayload';

/**
 * S1 — a duplicated КП line preserves its display_type + optionality, so a copied section stays a
 * section and a copied optional line stays optional (spec §5 п.19, point 7).
 */

const mkItem = (overrides: Partial<QuoteItem> = {}): QuoteItem =>
	({
		id: 7,
		quote: 1,
		display_type: 'ITEM',
		is_optional: false,
		imported_raw_name: 'Болт М12',
		quantity: 4,
		frozen_base_price: '0',
		frozen_currency: 'UZS',
		logistics_cost: '0',
		customs_duty: '0',
		margin_percent: '0',
		discount_percent: '0',
		lead_time_days: 0,
		landed_cost: '0',
		final_price_excl_vat: '0',
		...overrides,
	}) as QuoteItem;

describe('buildDuplicatePayload — sections / optional (S1)', () => {
	it('preserves a SECTION display_type on the copy', () => {
		const payload = buildDuplicatePayload(mkItem({ display_type: 'SECTION', imported_raw_name: 'Механика' }), ' (копия)');
		expect(payload.display_type).toBe('SECTION');
		expect(payload.is_optional).toBe(false);
		expect(payload.imported_raw_name).toBe('Механика (копия)');
	});

	it('preserves a NOTE display_type on the copy', () => {
		const payload = buildDuplicatePayload(mkItem({ display_type: 'NOTE', imported_raw_name: 'Примечание' }), ' (копия)');
		expect(payload.display_type).toBe('NOTE');
	});

	it('preserves the optional flag on a duplicated ITEM', () => {
		const payload = buildDuplicatePayload(mkItem({ is_optional: true }), ' (копия)');
		expect(payload.display_type).toBe('ITEM');
		expect(payload.is_optional).toBe(true);
	});

	it('defaults a legacy row (no display_type) to a plain ITEM', () => {
		const payload = buildDuplicatePayload(mkItem({ display_type: undefined }), ' (копия)');
		expect(payload.display_type).toBe('ITEM');
		expect(payload.is_optional).toBe(false);
	});
});
