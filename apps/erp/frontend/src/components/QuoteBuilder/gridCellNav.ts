/**
 * Pure DOM helpers for Excel-style cell navigation in the КП grid (U6 — full keyboard navigation).
 *
 * Editable cells opt in with `data-cell-col="<field>"` on their `<input>`; each lives inside a
 * `<tr data-row-id="<id>">`. SECTION/NOTE inputs carry NO `data-cell-col`, so every query here skips
 * them automatically (they contribute no navigable cells). Extracted as side-effect-free functions
 * so `useGridKeyboard` stays thin and the traversal is unit-testable without a React tree.
 */

/** The editable cells of the row that CONTAINS `cell`, in visual (DOM) left→right order. */
export function rowCellsOf(cell: HTMLElement): HTMLElement[] {
	const row = cell.closest<HTMLElement>('[data-row-id]');
	if (!row) return [];
	return Array.from(row.querySelectorAll<HTMLElement>('[data-cell-col]'));
}

/** Every editable cell of one column across the whole container, in DOM (row) order (↑/↓ path). */
export function columnCellsOf(container: HTMLElement, column: string): HTMLElement[] {
	return Array.from(container.querySelectorAll<HTMLElement>(`[data-cell-col="${column}"]`));
}

/** Main rows that actually carry navigable cells — i.e. ITEM rows; SECTION/NOTE rows drop out. */
export function navigableRowsOf(container: HTMLElement): HTMLElement[] {
	return Array.from(container.querySelectorAll<HTMLElement>('[data-row-id]')).filter(
		(row) => row.querySelector('[data-cell-col]') !== null,
	);
}

/** The in-row neighbour cell `direction` (-1 left / +1 right) from `cell`, or null at the row edge. */
export function siblingColumnCell(cell: HTMLElement, direction: -1 | 1): HTMLElement | null {
	const cells = rowCellsOf(cell);
	const index = cells.indexOf(cell);
	if (index === -1) return null;
	return cells[index + direction] ?? null;
}

/**
 * The Tab target for `cell`: the next/previous editable cell, wrapping to the adjacent ITEM row at a
 * row edge (Excel/Sheets semantics). Returns null ONLY when the adjacent row is not present in the
 * DOM — the caller then decides between a windowed scroll-focus (off-window row) and letting native
 * Tab escape the grid (a true first/last boundary).
 */
export function tabTargetInDom(container: HTMLElement, cell: HTMLElement, direction: -1 | 1): HTMLElement | null {
	const within = siblingColumnCell(cell, direction);
	if (within) return within;
	const rows = navigableRowsOf(container);
	const row = cell.closest<HTMLElement>('[data-row-id]');
	if (!row) return null;
	const rowIndex = rows.indexOf(row);
	const targetRow = rows[rowIndex + direction];
	if (!targetRow) return null;
	const targetCells = Array.from(targetRow.querySelectorAll<HTMLElement>('[data-cell-col]'));
	if (targetCells.length === 0) return null;
	return direction === 1 ? targetCells[0] : targetCells[targetCells.length - 1];
}

/** True when the input's caret is collapsed at the very start (nothing selected). */
export function caretAtStart(input: HTMLInputElement): boolean {
	return input.selectionStart === 0 && input.selectionEnd === 0;
}

/** True when the input's caret is collapsed at the very end (nothing selected). */
export function caretAtEnd(input: HTMLInputElement): boolean {
	const end = input.value.length;
	return input.selectionStart === end && input.selectionEnd === end;
}
