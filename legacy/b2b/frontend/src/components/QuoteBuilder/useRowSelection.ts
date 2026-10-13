import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useLatestRef } from '@/hooks/useLatestRef';

export interface UseRowSelectionResult {
	/** The currently selected row ids. */
	selectedIds: Set<number>;
	/** Number of selected rows (convenience for the toolbar «Выбрано: N»). */
	count: number;
	/** Is this row selected? */
	isSelected: (id: number) => boolean;
	/** Toggle one row; with `shiftKey` selects the range from the last-clicked row to this one. */
	toggle: (id: number, shiftKey?: boolean) => void;
	/** Header checkbox: select all when not all are selected, else clear. */
	toggleAll: () => void;
	/** Every row selected (and there is ≥1 row). */
	allSelected: boolean;
	/** Some — but not all — rows selected (header checkbox → indeterminate). */
	someSelected: boolean;
	/** Clear the whole selection (after a successful bulk action). */
	clear: () => void;
}

/**
 * Row multi-select for the КП line grid (WP-J / spec §5 волна 2 п.11).
 *
 * Holds a `Set<id>` of selected rows plus a "last clicked" anchor for Shift+range.
 * Selection PERSISTS across tab switches and focus-mode (it lives above the grid),
 * is pruned automatically when a row leaves the server set (delete / duplicate refetch),
 * and is cleared explicitly by the caller after a successful bulk action.
 *
 * `orderedIds` is the visible row order (draftItems order) — it drives Shift-range,
 * all/none, and the prune. It is read through a ref so the callbacks stay stable.
 */
export function useRowSelection(orderedIds: number[], selectableIds?: number[]): UseRowSelectionResult {
	const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
	const lastSelectedIdRef = useRef<number | null>(null);

	// U4: the currently VISIBLE subset (filter applied), in the same order. It drives Shift+range,
	// «выбрать все» and the header checkbox state, so a «select all» under an active filter selects
	// exactly the rows the seller can see — never a hidden line a later bulk delete would take with
	// it. The PRUNE deliberately stays on `orderedIds` (below), so merely hiding a row by filtering
	// does not drop its selection. Omitted ⇒ byte-identical to the pre-filter behaviour.
	const visibleIds = selectableIds ?? orderedIds;
	const visibleIdsRef = useLatestRef(visibleIds);

	// Stable access to the latest row order inside the callbacks (orderedIds is a fresh array
	// every render — a new draftItems.map — so we never want it in a callback dep list).
	const orderedIdsRef = useLatestRef(orderedIds);

	// Prune ids that left the server row set (a deleted / replaced row must not stay selected).
	// Keyed on the joined id list so it only runs when the actual set of rows changes.
	const idsKey = orderedIds.join(',');
	useEffect(() => {
		const present = new Set(orderedIdsRef.current);
		setSelectedIds((previous) => {
			const next = new Set([...previous].filter((id) => present.has(id)));
			return next.size === previous.size ? previous : next;
		});
	}, [idsKey, orderedIdsRef]);

	const toggle = useCallback((id: number, shiftKey = false) => {
		// Shift-range walks the VISIBLE order: under a filter the range is what sits between the two
		// clicked rows on screen, not the hidden lines the unfiltered document has between them.
		const ordered = visibleIdsRef.current;
		setSelectedIds((previous) => {
			const next = new Set(previous);
			const anchor = lastSelectedIdRef.current;
			if (shiftKey && anchor != null) {
				const from = ordered.indexOf(anchor);
				const to = ordered.indexOf(id);
				if (from !== -1 && to !== -1) {
					const [lo, hi] = from <= to ? [from, to] : [to, from];
					for (let index = lo; index <= hi; index += 1) next.add(ordered[index]);
					lastSelectedIdRef.current = id;
					return next;
				}
			}
			if (next.has(id)) next.delete(id);
			else next.add(id);
			lastSelectedIdRef.current = id;
			return next;
		});
	}, [visibleIdsRef]);

	// "All" means all VISIBLE rows (== all rows when no filter is active).
	const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
	const someSelected = selectedIds.size > 0 && !allSelected;

	const toggleAll = useCallback(() => {
		const visible = visibleIdsRef.current;
		setSelectedIds((previous) => {
			const everyVisibleSelected = visible.length > 0 && visible.every((id) => previous.has(id));
			const next = new Set(previous);
			// Toggling OFF only clears the visible rows — a selection made before filtering survives.
			if (everyVisibleSelected) visible.forEach((id) => next.delete(id));
			else visible.forEach((id) => next.add(id));
			return next;
		});
	}, [visibleIdsRef]);

	const clear = useCallback(() => {
		setSelectedIds((previous) => (previous.size === 0 ? previous : new Set()));
		lastSelectedIdRef.current = null;
	}, []);

	const isSelected = useCallback((id: number) => selectedIds.has(id), [selectedIds]);

	return useMemo(
		() => ({
			selectedIds,
			count: selectedIds.size,
			isSelected,
			toggle,
			toggleAll,
			allSelected,
			someSelected,
			clear,
		}),
		[selectedIds, isSelected, toggle, toggleAll, allSelected, someSelected, clear],
	);
}
