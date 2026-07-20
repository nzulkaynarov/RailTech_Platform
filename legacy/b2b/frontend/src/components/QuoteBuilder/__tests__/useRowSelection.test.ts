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

/**
 * U4 — with the «найти в КП» filter active the hook receives a second argument: the VISIBLE subset.
 * The split matters for safety: pruning must follow the FULL row set (hiding a row is not deleting
 * it, so its selection survives), while «выбрать все» and Shift-range must follow the VISIBLE subset
 * (a select-all under a filter followed by a bulk delete must never take a row off-screen with it).
 */
describe('useRowSelection — filtered (visible) subset', () => {
	it('toggleAll selects only the VISIBLE rows', () => {
		const { result } = renderHook(() => useRowSelection([1, 2, 3, 4], [2, 4]));

		act(() => result.current.toggleAll());

		expect([...result.current.selectedIds].sort()).toEqual([2, 4]);
		expect(result.current.allSelected).toBe(true); // "all" == all visible
	});

	it('toggleAll a second time clears ONLY the visible rows, keeping a pre-filter selection', () => {
		const { result, rerender } = renderHook(
			({ all, visible }) => useRowSelection(all, visible),
			{ initialProps: { all: [1, 2, 3, 4], visible: [1, 2, 3, 4] } },
		);

		act(() => result.current.toggle(1)); // selected before filtering
		rerender({ all: [1, 2, 3, 4], visible: [2, 4] });

		act(() => result.current.toggleAll()); // adds 2 + 4
		expect([...result.current.selectedIds].sort()).toEqual([1, 2, 4]);

		act(() => result.current.toggleAll()); // removes 2 + 4 only
		expect([...result.current.selectedIds]).toEqual([1]);
	});

	it('a row merely HIDDEN by the filter keeps its selection (prune follows the full set)', () => {
		const { result, rerender } = renderHook(
			({ all, visible }) => useRowSelection(all, visible),
			{ initialProps: { all: [1, 2, 3], visible: [1, 2, 3] } },
		);

		act(() => result.current.toggle(2));
		rerender({ all: [1, 2, 3], visible: [1, 3] }); // #2 filtered out, still on the server

		expect(result.current.isSelected(2)).toBe(true);
	});

	it('a row DELETED server-side is still pruned while a filter is active', () => {
		const { result, rerender } = renderHook(
			({ all, visible }) => useRowSelection(all, visible),
			{ initialProps: { all: [1, 2, 3], visible: [1, 2, 3] } },
		);

		act(() => result.current.toggle(2));
		rerender({ all: [1, 3], visible: [1, 3] });

		expect(result.current.isSelected(2)).toBe(false);
	});

	it('Shift-range walks the VISIBLE order, not the hidden rows between the two clicks', () => {
		// Document 1..5, filter leaves 1, 3, 5. Shift-clicking 1 then 5 selects the three VISIBLE
		// rows — never the hidden 2 and 4.
		const { result } = renderHook(() => useRowSelection([1, 2, 3, 4, 5], [1, 3, 5]));

		act(() => result.current.toggle(1));
		act(() => result.current.toggle(5, true));

		expect([...result.current.selectedIds].sort()).toEqual([1, 3, 5]);
	});

	it('omitting the visible subset is identical to the pre-filter behaviour', () => {
		const { result } = renderHook(() => useRowSelection([1, 2, 3]));

		act(() => result.current.toggleAll());
		expect([...result.current.selectedIds].sort()).toEqual([1, 2, 3]);
		expect(result.current.allSelected).toBe(true);
	});
});
