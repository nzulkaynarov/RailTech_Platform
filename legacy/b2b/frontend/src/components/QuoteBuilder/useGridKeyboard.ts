import { useCallback, useRef } from 'react';

/**
 * Virtualization bridge (волна 3). When the line table is windowed, the next column-cell may be
 * outside the rendered DOM, so `columnCells` cannot see it. The grid passes the FULL visible row
 * order plus a scroll-then-focus callback; the handler resolves the target from the model, and only
 * treats a step as a true grid boundary when the target index is genuinely off the ends of the list.
 */
export interface GridKeyboardVirtualization {
	/** Full row ids in visible (draftItems) order — the source of truth for "is there a next row?". */
	rowIds: number[];
	/** Scroll the row at `rowIndex` into the window, then focus that row's `column` cell. */
	focusCellAtRow: (rowIndex: number, column: string) => void;
	/** S1: does this row have navigable cells? SECTION/NOTE rows carry no `data-cell-col` input, so a
	 *  windowed ArrowUp/Down that lands on one must keep stepping PAST it to the next ITEM row (in the
	 *  non-windowed path they are already skipped — they contribute no cells to the column query). */
	isNavigable?: (rowId: number) => boolean;
}

/**
 * Excel-style keyboard navigation for the КП line grid (WP-G / spec §5 волна 2 п.10).
 *
 * Editable cells opt in by carrying `data-cell-col="<field>"` (and `data-cell-row="<id>"`)
 * on their `<input>`. A single delegated `onKeyDown` on the scroll container then moves
 * focus between the SAME column of adjacent rows:
 *
 *   • ArrowDown / Enter → the same column one row down;
 *   • ArrowUp           → the same column one row up;
 *   • at the first/last row → no-op (focus stays put), like Excel at the grid boundary.
 *
 * Moving focus blurs the current cell, so its `NumericCell` commits the in-progress edit
 * through its normal commit-on-blur path (no separate commit wiring needed here). Enter is
 * ALSO handled by `NumericCell` (preventDefault + blur → commit) before this fires; here we
 * only add the "then move down" step, so the seller can type down a column hands-free.
 *
 * Deliberately inert unless focus is inside a registered cell: the currency `<Select>`, the
 * expanded detail sub-row inputs, and the add-row carry no `data-cell-col`, so their arrows
 * and Enter fall through to their own handlers / native caret behaviour untouched. Tab and
 * Shift+Tab are never intercepted — the browser's native focus order still owns them.
 */
export function useGridKeyboard(virtualization?: GridKeyboardVirtualization) {
	// Held through a ref so the handler stays referentially stable (deps `[]`, as before) while
	// always reading the latest window model — the config is a fresh object on every render.
	const virtualizationRef = useRef(virtualization);
	virtualizationRef.current = virtualization;

	const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLElement>) => {
		const { key } = event;
		if (key !== 'ArrowUp' && key !== 'ArrowDown' && key !== 'Enter') return;

		// Only act when focus is inside a registered navigable cell. `event.target` stays the
		// original input even if NumericCell already blurred it on Enter, so `closest` still
		// resolves the source cell.
		const target = event.target as HTMLElement;
		const cell = target.closest<HTMLElement>('[data-cell-col]');
		if (!cell) return;

		const column = cell.getAttribute('data-cell-col');
		if (!column) return;

		// Cells of this column in visible (DOM == draftItems) order. Detail-row inputs and the
		// currency Select carry no data-cell-col, so this list is exactly the main-row column.
		const container = event.currentTarget;
		const columnCells = Array.from(
			container.querySelectorAll<HTMLElement>(`[data-cell-col="${column}"]`),
		);
		const index = columnCells.indexOf(cell);
		if (index === -1) return;

		const delta = key === 'ArrowUp' ? -1 : 1; // Enter behaves like ArrowDown
		const nextCell = columnCells[index + delta];
		if (nextCell) {
			event.preventDefault();
			// Focus move blurs the current cell → NumericCell commits its edit on blur.
			nextCell.focus();
			return;
		}

		// No next cell IN THE DOM. When the grid is windowed, that may just mean the target row is
		// scrolled out — resolve it from the full model and scroll-then-focus rather than treating
		// it as a boundary. `data-cell-row` on the source input carries its row id.
		const virtualizationConfig = virtualizationRef.current;
		if (virtualizationConfig) {
			const rowIdAttr = cell.getAttribute('data-cell-row');
			const currentRowId = rowIdAttr != null ? Number(rowIdAttr) : Number.NaN;
			const currentModelIndex = virtualizationConfig.rowIds.indexOf(currentRowId);
			if (currentModelIndex !== -1) {
				const { rowIds, isNavigable } = virtualizationConfig;
				// Step in the arrow direction, skipping non-navigable (SECTION/NOTE) rows so focus lands
				// on the next real ITEM cell — mirroring the non-windowed path where those rows have no
				// column cell at all.
				let targetModelIndex = currentModelIndex + delta;
				while (
					targetModelIndex >= 0 && targetModelIndex < rowIds.length
					&& isNavigable && !isNavigable(rowIds[targetModelIndex])
				) {
					targetModelIndex += delta;
				}
				if (targetModelIndex >= 0 && targetModelIndex < rowIds.length) {
					event.preventDefault();
					virtualizationConfig.focusCellAtRow(targetModelIndex, column);
					return;
				}
			}
		}

		// True grid boundary → keep focus in the source cell, consistent for arrows AND Enter.
		// Arrows: swallow the key so the caret does not jump (focus never left the cell).
		if (key !== 'Enter') {
			event.preventDefault();
			return;
		}
		// Enter: NumericCell already committed + blurred to <body>. Refocus the source cell so
		// the seller stays in the grid — but on a MICROTASK, after React has re-rendered the cell
		// with the just-committed value. A synchronous refocus would re-enter edit mode holding
		// the STALE pre-commit value (the prop hasn't updated yet), silently reverting the edit
		// on the next blur. By the microtask the committed value is live, so it re-enters cleanly.
		queueMicrotask(() => cell.focus());
	}, []);

	return { onKeyDown };
}
