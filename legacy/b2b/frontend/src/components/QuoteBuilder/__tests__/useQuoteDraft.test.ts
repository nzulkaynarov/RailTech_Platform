import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import type { QuoteItem } from '@/api/crmApi';
import { useQuoteDraft } from '@/components/QuoteBuilder/useQuoteDraft';

/**
 * WP-D / spec §2 P0-3 — the draft state machine. A refetch of `['quote-items']`
 * (fired by settings/charges/basis mutations) must merge into NON-dirty rows only;
 * a row the seller is editing keeps its local value until saved or reverted.
 */

const mkItem = (id: number, overrides: Partial<QuoteItem> = {}): QuoteItem =>
	({
		id,
		quote: 1,
		imported_raw_name: `line-${id}`,
		quantity: 1,
		frozen_base_price: '100',
		frozen_currency: 'UZS',
		logistics_cost: '0',
		customs_duty: '0',
		margin_percent: '0',
		discount_percent: '0',
		lead_time_days: 0,
		landed_cost: '100',
		final_price_excl_vat: '120',
		...overrides,
	}) as QuoteItem;

describe('useQuoteDraft', () => {
	it('seeds draftItems from the server list with nothing dirty', () => {
		const server = [mkItem(1), mkItem(2)];
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: server },
		});

		expect(result.current.draftItems).toHaveLength(2);
		expect(result.current.hasUnsavedChanges).toBe(false);
		expect(result.current.dirtyIds.size).toBe(0);
	});

	it('marks a row dirty on setField and keeps its local value across a server refetch', () => {
		const server = [mkItem(1, { frozen_base_price: '100' }), mkItem(2, { frozen_base_price: '200' })];
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: server },
		});

		// Seller edits row 1's price locally.
		act(() => result.current.setField(1, 'frozen_base_price', '999'));
		expect(result.current.dirtyIds.has(1)).toBe(true);
		expect(result.current.hasUnsavedChanges).toBe(true);

		// A refetch returns FRESH data for both rows (row 1 changed server-side, row 2 too).
		const refetched = [mkItem(1, { frozen_base_price: '100' }), mkItem(2, { frozen_base_price: '250' })];
		rerender({ items: refetched });

		const row1 = result.current.draftItems.find((item) => item.id === 1);
		const row2 = result.current.draftItems.find((item) => item.id === 2);
		// Dirty row 1 keeps the local edit; clean row 2 takes the refreshed server value.
		expect(row1?.frozen_base_price).toBe('999');
		expect(row2?.frozen_base_price).toBe('250');
	});

	it('resetRow restores the server value and clears the dirty flag', () => {
		const server = [mkItem(1, { quantity: 5 })];
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: server },
		});

		act(() => result.current.setField(1, 'quantity', '42'));
		expect(result.current.draftItems[0].quantity).toBe('42');

		act(() => result.current.resetRow(1));
		expect(result.current.draftItems[0].quantity).toBe(5);
		expect(result.current.hasUnsavedChanges).toBe(false);
	});

	it('clearDirtyAfterSave drops the ids so the next refetch re-merges server data', () => {
		const server = [mkItem(1, { frozen_base_price: '100' })];
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: server },
		});

		act(() => result.current.setField(1, 'frozen_base_price', '999'));
		expect(result.current.dirtyIds.has(1)).toBe(true);

		// Save completed → clear dirty.
		act(() => result.current.clearDirtyAfterSave([1]));
		expect(result.current.dirtyIds.has(1)).toBe(false);
		expect(result.current.hasUnsavedChanges).toBe(false);

		// The post-save refetch now flows into the (no-longer-dirty) row.
		rerender({ items: [mkItem(1, { frozen_base_price: '999' })] });
		expect(result.current.draftItems[0].frozen_base_price).toBe('999');
	});

	it('reflects row additions and deletions coming from the server list', () => {
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1)] },
		});

		rerender({ items: [mkItem(1), mkItem(2)] });
		expect(result.current.draftItems.map((item) => item.id)).toEqual([1, 2]);

		rerender({ items: [mkItem(2)] });
		expect(result.current.draftItems.map((item) => item.id)).toEqual([2]);
	});
});
