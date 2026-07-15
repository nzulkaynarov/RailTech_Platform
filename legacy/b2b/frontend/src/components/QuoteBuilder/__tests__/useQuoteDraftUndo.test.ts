import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import type { QuoteItem } from '@/api/crmApi';
import { useQuoteDraft } from '@/components/QuoteBuilder/useQuoteDraft';

/**
 * WP-J / spec §5 волна 2 п.11 — the draft machine's undo stack + bulk apply.
 *   • applyBulk marks every touched row dirty with the new value (one undo step);
 *   • undo reverts the last setField / applyBulk;
 *   • the undo stack is cleared on a server ROW-SET change (delete / duplicate).
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

describe('useQuoteDraft — undo + applyBulk (WP-J)', () => {
	it('applyBulk marks the touched rows dirty with the new value in one undo step', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1), mkItem(2), mkItem(3)] },
		});

		act(() =>
			result.current.applyBulk([
				{ id: 1, field: 'discount_percent', value: '10' },
				{ id: 2, field: 'discount_percent', value: '10' },
			]),
		);

		expect(result.current.dirtyIds.has(1)).toBe(true);
		expect(result.current.dirtyIds.has(2)).toBe(true);
		expect(result.current.dirtyIds.has(3)).toBe(false);
		expect(result.current.draftItems.find((item) => item.id === 1)?.discount_percent).toBe('10');
		expect(result.current.draftItems.find((item) => item.id === 2)?.discount_percent).toBe('10');
		expect(result.current.canUndo).toBe(true);
	});

	it('undo reverts the last setField and clears the dirty flag when it was the only edit', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1, { quantity: 2 })] },
		});

		act(() => result.current.setField(1, 'quantity', '5'));
		expect(result.current.draftItems[0].quantity).toBe('5');
		expect(result.current.hasUnsavedChanges).toBe(true);
		expect(result.current.canUndo).toBe(true);

		act(() => result.current.undo());
		expect(result.current.draftItems[0].quantity).toBe(2);
		expect(result.current.hasUnsavedChanges).toBe(false);
		expect(result.current.canUndo).toBe(false);
	});

	it('undo peels edits off one at a time (last-in-first-out)', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1, { quantity: 1 })] },
		});

		act(() => result.current.setField(1, 'quantity', '2'));
		act(() => result.current.setField(1, 'quantity', '3'));
		expect(result.current.draftItems[0].quantity).toBe('3');

		act(() => result.current.undo());
		expect(result.current.draftItems[0].quantity).toBe('2');

		act(() => result.current.undo());
		expect(result.current.draftItems[0].quantity).toBe(1);
		expect(result.current.canUndo).toBe(false);
	});

	it('undo reverts a whole applyBulk in one step', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1), mkItem(2)] },
		});

		act(() =>
			result.current.applyBulk([
				{ id: 1, field: 'frozen_base_price', value: '90' },
				{ id: 2, field: 'frozen_base_price', value: '180' },
			]),
		);
		act(() => result.current.undo());

		expect(result.current.draftItems.find((item) => item.id === 1)?.frozen_base_price).toBe('100');
		expect(result.current.draftItems.find((item) => item.id === 2)?.frozen_base_price).toBe('100');
		expect(result.current.hasUnsavedChanges).toBe(false);
	});

	it('clears the undo stack when the server row set changes (delete / duplicate)', () => {
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1), mkItem(2)] },
		});

		act(() => result.current.setField(1, 'quantity', '9'));
		expect(result.current.canUndo).toBe(true);

		// A row was duplicated (id 3 appears) → old snapshots reference a stale row set.
		rerender({ items: [mkItem(1, { quantity: 9 }), mkItem(2), mkItem(3)] });
		expect(result.current.canUndo).toBe(false);
	});

	it('undo restores only dirty rows — clean rows keep CURRENT server values after a refetch', () => {
		// Adversarial-review MAJOR: replaying the whole snapshot rolled clean rows back to
		// pre-refetch values (stale money display). Undo must rebuild clean rows from the
		// live server list and restore ONLY the snapshot's dirty rows.
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1), mkItem(2)] },
		});

		act(() => result.current.setField(1, 'frozen_base_price', '500'));
		act(() => result.current.setField(1, 'frozen_base_price', '700'));

		// Field-only refetch: same row ids, row 2 (clean) got a NEW server value.
		rerender({ items: [mkItem(1), mkItem(2, { frozen_base_price: '999' })] });

		act(() => result.current.undo());

		const rowById = new Map(result.current.draftItems.map((item) => [item.id, item]));
		expect(rowById.get(1)?.frozen_base_price).toBe('500'); // dirty row rolled back one step
		expect(rowById.get(2)?.frozen_base_price).toBe('999'); // clean row keeps server truth
	});
});
