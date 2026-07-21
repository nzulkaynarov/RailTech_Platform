import { useCallback, useRef } from 'react';
import {
	rowCellsOf, columnCellsOf, siblingColumnCell, tabTargetInDom, caretAtStart, caretAtEnd,
} from './gridCellNav';

/**
 * Virtualization bridge (волна 3). When the line table is windowed, an adjacent cell may live
 * OUTSIDE the rendered DOM, so the DOM queries in `gridCellNav` cannot see it. The grid passes the
 * FULL visible row order plus a scroll-then-focus callback; the handler resolves the target from the
 * model and only treats a step as a true grid boundary when the target index is genuinely off the
 * ends of the list.
 */
export interface GridKeyboardVirtualization {
	/** Full row ids in visible (draftItems) order — the source of truth for "is there a next row?". */
	rowIds: number[];
	/** Scroll the row at `rowIndex` into the window, then focus that row's `column` cell. */
	focusCellAtRow: (rowIndex: number, column: string) => void;
	/** S1: does this row have navigable cells? SECTION/NOTE rows carry no `data-cell-col` input, so a
	 *  windowed step that lands on one must keep stepping PAST it to the next ITEM row (in the
	 *  non-windowed path they are already skipped — they contribute no cells to the DOM query). */
	isNavigable?: (rowId: number) => boolean;
}

/**
 * Excel-style keyboard navigation for the КП line grid (WP-G волна 2 п.10, extended by U6).
 *
 * Editable cells opt in by carrying `data-cell-col="<field>"` (and `data-cell-row="<id>"`) on their
 * `<input>`. A single delegated `onKeyDown` on the scroll container moves focus between cells:
 *
 *   • ArrowDown / Enter → the SAME column one row down; ArrowUp → the same column one row up;
 *   • ArrowLeft / ArrowRight → the previous/next COLUMN of the same row, but only once the caret has
 *     reached the text edge (the cells are always-editable inputs, so Left/Right serve the caret
 *     first — a press at the boundary steps to the adjacent column, like leaving a spreadsheet cell);
 *   • Tab / Shift+Tab → the next/previous CELL, wrapping to the adjacent ITEM row at a row edge;
 *   • at a true grid boundary → arrows keep focus put (Excel), Tab lets native focus escape the grid.
 *
 * Moving focus blurs the current cell, so its `NumericCell` commits the in-progress edit through its
 * normal commit-on-blur path (no separate commit wiring needed here). Deliberately inert unless focus
 * is inside a registered cell: the currency `<Select>`, the expanded detail sub-row inputs and the
 * add-row carry no `data-cell-col`, so their keys fall through to their own handlers untouched.
 */
export function useGridKeyboard(virtualization?: GridKeyboardVirtualization) {
	// Held through a ref so the handler stays referentially stable while always reading the latest
	// window model — the config is a fresh object on every render.
	const virtualizationRef = useRef(virtualization);
	virtualizationRef.current = virtualization;

	// Resolve the model index `delta` steps from `currentRowId`, skipping non-navigable (SECTION/NOTE)
	// rows. Returns the target index, or -1 at a true grid boundary / when the source row is unknown.
	// Shared by the windowed ArrowUp/Down and Tab paths.
	const stepModelIndex = useCallback((currentRowId: number, delta: number): number => {
		const config = virtualizationRef.current;
		if (!config) return -1;
		const currentModelIndex = config.rowIds.indexOf(currentRowId);
		if (currentModelIndex === -1) return -1;
		let target = currentModelIndex + delta;
		while (
			target >= 0 && target < config.rowIds.length
			&& config.isNavigable && !config.isNavigable(config.rowIds[target])
		) {
			target += delta;
		}
		return target >= 0 && target < config.rowIds.length ? target : -1;
	}, []);

	const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLElement>) => {
		const { key } = event;
		const isVertical = key === 'ArrowUp' || key === 'ArrowDown' || key === 'Enter';
		const isHorizontal = key === 'ArrowLeft' || key === 'ArrowRight';
		const isTab = key === 'Tab';
		if (!isVertical && !isHorizontal && !isTab) return;

		// Only act when focus is inside a registered navigable cell. `event.target` stays the original
		// input even if NumericCell already blurred it on Enter, so `closest` still resolves the cell.
		const target = event.target as HTMLElement;
		const cell = target.closest<HTMLElement>('[data-cell-col]');
		if (!cell) return;

		// ── Horizontal (←/→) — column navigation within the row, caret-edge gated ──────────────
		if (isHorizontal) {
			const input = target as HTMLInputElement;
			const direction = key === 'ArrowLeft' ? -1 : 1;
			const atEdge = direction === -1 ? caretAtStart(input) : caretAtEnd(input);
			if (!atEdge) return; // caret still has room → let the browser move it inside the text
			const next = siblingColumnCell(cell, direction);
			if (next) {
				event.preventDefault();
				next.focus();
			}
			// No adjacent column → Excel row-edge no-op (the pinned caret makes native inert too).
			return;
		}

		const column = cell.getAttribute('data-cell-col');
		if (!column) return;

		// ── Tab / Shift+Tab — cell-wise, wrapping to the adjacent ITEM row at a row edge ─────────
		if (isTab) {
			const direction = event.shiftKey ? -1 : 1;
			const domTarget = tabTargetInDom(event.currentTarget, cell, direction);
			if (domTarget) {
				event.preventDefault();
				domTarget.focus();
				return;
			}
			// No DOM target: either the adjacent row is scrolled out of a windowed grid, or this is the
			// true first/last cell. Resolve via the model — a real off-window row gets scroll-focused,
			// a genuine boundary lets native Tab escape the grid (never trap keyboard focus).
			const rowCells = rowCellsOf(cell);
			const firstColumn = rowCells[0]?.getAttribute('data-cell-col');
			const lastColumn = rowCells[rowCells.length - 1]?.getAttribute('data-cell-col');
			const targetColumn = direction === 1 ? firstColumn : lastColumn;
			const config = virtualizationRef.current;
			if (config && targetColumn) {
				const rowIdAttr = cell.getAttribute('data-cell-row');
				const currentRowId = rowIdAttr != null ? Number(rowIdAttr) : Number.NaN;
				const targetIndex = stepModelIndex(currentRowId, direction);
				if (targetIndex !== -1) {
					event.preventDefault();
					config.focusCellAtRow(targetIndex, targetColumn);
					return;
				}
			}
			return; // true grid boundary → native Tab moves focus out of the grid
		}

		// ── Vertical (↑/↓/Enter) — same column, adjacent row ────────────────────────────────────
		// Cells of this column in visible (DOM == draftItems) order. Detail-row inputs and the
		// currency Select carry no data-cell-col, so this list is exactly the main-row column.
		const columnCells = columnCellsOf(event.currentTarget, column);
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
		// scrolled out — resolve it from the full model and scroll-then-focus rather than treating it
		// as a boundary. `data-cell-row` on the source input carries its row id.
		const config = virtualizationRef.current;
		if (config) {
			const rowIdAttr = cell.getAttribute('data-cell-row');
			const currentRowId = rowIdAttr != null ? Number(rowIdAttr) : Number.NaN;
			const targetIndex = stepModelIndex(currentRowId, delta);
			if (targetIndex !== -1) {
				event.preventDefault();
				config.focusCellAtRow(targetIndex, column);
				return;
			}
		}

		// True grid boundary → keep focus in the source cell, consistent for arrows AND Enter.
		// Arrows: swallow the key so the caret does not jump (focus never left the cell).
		if (key !== 'Enter') {
			event.preventDefault();
			return;
		}
		// Enter: NumericCell already committed + blurred to <body>. Refocus the source cell so the
		// seller stays in the grid — but on a MICROTASK, after React has re-rendered the cell with the
		// just-committed value. A synchronous refocus would re-enter edit mode holding the STALE
		// pre-commit value (the prop hasn't updated yet), silently reverting the edit on the next blur.
		queueMicrotask(() => cell.focus());
	}, [stepModelIndex]);

	return { onKeyDown };
}
