import { useCallback } from 'react';

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
export function useGridKeyboard() {
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
		if (!nextCell) {
			// Grid boundary → keep focus in place. For arrows, swallow the key so the caret does
			// not jump; Enter already committed via NumericCell, so nothing else to do.
			if (key !== 'Enter') event.preventDefault();
			return;
		}

		event.preventDefault();
		// Focus move blurs the current cell → NumericCell commits its edit on blur.
		nextCell.focus();
	}, []);

	return { onKeyDown };
}
