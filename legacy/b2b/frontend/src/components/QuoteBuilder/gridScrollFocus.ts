/**
 * Scroll a windowed (virtualized) КП row into view, then focus one of its cells (волна 3).
 *
 * When the line table is virtualized, the target of an ArrowUp/ArrowDown/Enter step may live
 * OUTSIDE the rendered window, so its `<input data-cell-row data-cell-col>` is not yet in the
 * DOM. `useGridKeyboard` calls this helper: it asks the virtualizer to scroll the row into view,
 * then — across a few animation frames, because React re-renders the window asynchronously after
 * the scroll — polls for the freshly-rendered cell and focuses it. Extracted as a pure function
 * (frame scheduler injectable) so it is unit-testable without a real virtualizer or layout engine.
 */

export interface ScrollFocusDeps {
	/** Ask the virtualizer to bring the row at this index into the visible window. */
	scrollToIndex: (index: number) => void;
	/** The scroll container to query the target cell inside (null → give up gracefully). */
	getContainer: () => HTMLElement | null;
	/** Frame scheduler — defaults to requestAnimationFrame; injected as a sync stub in tests. */
	requestFrame?: (callback: () => void) => void;
	/** How many frames to keep polling for the target cell before giving up (default 6). */
	maxAttempts?: number;
}

/** CSS selector for the cell in a given row + column (matches NumericCell's data attributes). */
export const cellSelector = (rowId: number, column: string): string =>
	`[data-cell-row="${rowId}"][data-cell-col="${column}"]`;

export function scrollToRowAndFocusCell(
	rowIndex: number,
	rowId: number,
	column: string,
	deps: ScrollFocusDeps,
): void {
	const requestFrame = deps.requestFrame ?? ((callback: () => void) => requestAnimationFrame(callback));
	const maxAttempts = deps.maxAttempts ?? 6;

	deps.scrollToIndex(rowIndex);

	let attempts = 0;
	const tryFocus = () => {
		const container = deps.getContainer();
		const cell = container?.querySelector<HTMLElement>(cellSelector(rowId, column));
		if (cell) {
			cell.focus();
			return;
		}
		attempts += 1;
		if (attempts < maxAttempts) requestFrame(tryFocus);
	};

	requestFrame(tryFocus);
}
