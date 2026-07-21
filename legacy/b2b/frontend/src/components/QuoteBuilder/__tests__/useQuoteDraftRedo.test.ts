import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import type { QuoteItem } from '@/api/crmApi';
import { useQuoteDraft } from '@/components/QuoteBuilder/useQuoteDraft';

/**
 * U6 — the draft machine's REDO stack (symmetric with the WP-J undo stack).
 *   • undo → redo walks the edit back and forward again;
 *   • a fresh edit after an undo discards the redo future;
 *   • clearDirtyAfterSave (a successful Save) drops both histories;
 *   • redo restores ONLY the snapshot's dirty rows — clean rows keep current server truth.
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

describe('useQuoteDraft — redo (U6)', () => {
	it('redo re-applies the last undone edit and flips canUndo/canRedo symmetrically', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1, { quantity: 2 })] },
		});

		act(() => result.current.setField(1, 'quantity', '5'));
		expect(result.current.canRedo).toBe(false);

		act(() => result.current.undo());
		expect(result.current.draftItems[0].quantity).toBe(2);
		expect(result.current.canUndo).toBe(false);
		expect(result.current.canRedo).toBe(true);

		act(() => result.current.redo());
		expect(result.current.draftItems[0].quantity).toBe('5');
		expect(result.current.hasUnsavedChanges).toBe(true);
		expect(result.current.canUndo).toBe(true);
		expect(result.current.canRedo).toBe(false);
	});

	it('a fresh edit after an undo discards the redo future', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1, { quantity: 1 })] },
		});

		act(() => result.current.setField(1, 'quantity', '5'));
		act(() => result.current.undo());
		expect(result.current.canRedo).toBe(true);

		act(() => result.current.setField(1, 'quantity', '8'));
		expect(result.current.canRedo).toBe(false);
		expect(result.current.draftItems[0].quantity).toBe('8');
	});

	it('redo walks a multi-step history back to the top', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1, { quantity: 1 })] },
		});

		act(() => result.current.setField(1, 'quantity', '2'));
		act(() => result.current.setField(1, 'quantity', '3'));
		act(() => result.current.undo());
		act(() => result.current.undo());
		expect(result.current.draftItems[0].quantity).toBe(1);

		act(() => result.current.redo());
		expect(result.current.draftItems[0].quantity).toBe('2');
		act(() => result.current.redo());
		expect(result.current.draftItems[0].quantity).toBe('3');
		expect(result.current.canRedo).toBe(false);
	});

	it('clearDirtyAfterSave drops the redo history (saved values are the new baseline)', () => {
		const { result } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1)] },
		});

		act(() => result.current.setField(1, 'frozen_base_price', '500'));
		act(() => result.current.undo());
		expect(result.current.canRedo).toBe(true);

		act(() => result.current.clearDirtyAfterSave([1]));
		expect(result.current.canRedo).toBe(false);
		expect(result.current.canUndo).toBe(false);
	});

	it('a server row-set change clears BOTH undo and redo histories', () => {
		const { result, rerender } = renderHook(({ items }) => useQuoteDraft(items), {
			initialProps: { items: [mkItem(1), mkItem(2)] },
		});

		act(() => result.current.setField(1, 'quantity', '9'));
		act(() => result.current.undo());
		expect(result.current.canRedo).toBe(true);

		// A row was duplicated (id 3 appears) → the redo snapshots reference a stale row set.
		rerender({ items: [mkItem(1, { quantity: 9 }), mkItem(2), mkItem(3)] });
		expect(result.current.canRedo).toBe(false);
		expect(result.current.canUndo).toBe(false);
	});
});
