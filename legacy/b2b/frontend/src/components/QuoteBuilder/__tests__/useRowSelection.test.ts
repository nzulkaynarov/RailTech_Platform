import { describe, it, expect } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useRowSelection } from '@/components/QuoteBuilder/useRowSelection';

/**
 * WP-J / spec §5 волна 2 п.11 — row multi-select for the КП grid.
 *   • Shift+click selects the range from the last-clicked row to this one;
 *   • the header checkbox toggles all / none (indeterminate when partial);
 *   • a row that leaves the server set is pruned from the selection.
 */

describe('useRowSelection', () => {
	it('toggles a single row and reports the count', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3] },
		});

		act(() => result.current.toggle(2));
		expect(result.current.isSelected(2)).toBe(true);
		expect(result.current.count).toBe(1);

		act(() => result.current.toggle(2));
		expect(result.current.isSelected(2)).toBe(false);
		expect(result.current.count).toBe(0);
	});

	it('Shift+click selects the range from the last-clicked row', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3, 4, 5] },
		});

		act(() => result.current.toggle(2)); // anchor
		act(() => result.current.toggle(4, true)); // shift-range 2..4

		expect([...result.current.selectedIds].sort((a, b) => a - b)).toEqual([2, 3, 4]);
	});

	it('Shift+click ranges upward too (anchor above OR below the clicked row)', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3, 4, 5] },
		});

		act(() => result.current.toggle(4)); // anchor
		act(() => result.current.toggle(1, true)); // shift-range 1..4

		expect([...result.current.selectedIds].sort((a, b) => a - b)).toEqual([1, 2, 3, 4]);
	});

	it('header toggleAll selects all, then clears (all → none)', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3] },
		});

		act(() => result.current.toggleAll());
		expect(result.current.count).toBe(3);
		expect(result.current.allSelected).toBe(true);
		expect(result.current.someSelected).toBe(false);

		act(() => result.current.toggleAll());
		expect(result.current.count).toBe(0);
		expect(result.current.allSelected).toBe(false);
	});

	it('reports someSelected (indeterminate) when only part of the set is selected', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3] },
		});

		act(() => result.current.toggle(1));
		expect(result.current.someSelected).toBe(true);
		expect(result.current.allSelected).toBe(false);
	});

	it('prunes a selected id when it leaves the server row set (delete / duplicate refetch)', () => {
		const { result, rerender } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3] },
		});

		act(() => result.current.toggle(1));
		act(() => result.current.toggle(3));
		expect(result.current.count).toBe(2);

		// Row 3 removed server-side → it must drop out of the selection.
		rerender({ ids: [1, 2] });
		expect(result.current.isSelected(3)).toBe(false);
		expect([...result.current.selectedIds]).toEqual([1]);
	});

	it('clear() empties the selection', () => {
		const { result } = renderHook(({ ids }) => useRowSelection(ids), {
			initialProps: { ids: [1, 2, 3] },
		});

		act(() => result.current.toggleAll());
		expect(result.current.count).toBe(3);
		act(() => result.current.clear());
		expect(result.current.count).toBe(0);
	});
});
