import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { scrollToRowAndFocusCell, cellSelector } from '../gridScrollFocus';

/**
 * волна 3 — the scroll-then-focus bridge that lets keyboard navigation cross the virtualized
 * window edge. The target cell is NOT in the DOM when the step fires (its row is scrolled out),
 * so the helper must ask the virtualizer to scroll, then poll across frames until React has
 * re-rendered the window and the cell exists, and only then focus it (giving up after maxAttempts).
 */
describe('scrollToRowAndFocusCell', () => {
	let container: HTMLDivElement;

	beforeEach(() => {
		container = document.createElement('div');
		document.body.appendChild(container);
	});

	afterEach(() => {
		container.remove();
	});

	const makeCell = (rowId: number, column: string): HTMLInputElement => {
		const input = document.createElement('input');
		input.setAttribute('data-cell-row', String(rowId));
		input.setAttribute('data-cell-col', column);
		return input;
	};

	it('cellSelector targets the exact row + column cell', () => {
		expect(cellSelector(42, 'quantity')).toBe('[data-cell-row="42"][data-cell-col="quantity"]');
	});

	it('scrolls to the row, then focuses the cell once it appears on a later frame', () => {
		// A manual frame queue: we flush callbacks by hand to simulate rAF turns deterministically.
		const frames: Array<() => void> = [];
		const requestFrame = (cb: () => void) => { frames.push(cb); };
		const scrollToIndex = vi.fn();

		scrollToRowAndFocusCell(7, 700, 'frozen_base_price', {
			scrollToIndex,
			getContainer: () => container,
			requestFrame,
			maxAttempts: 6,
		});

		// The scroll was requested up front; the cell is still out of the DOM.
		expect(scrollToIndex).toHaveBeenCalledWith(7);
		expect(frames).toHaveLength(1);

		// Frame 1: cell absent → the helper re-schedules another poll.
		frames.shift()?.();
		expect(frames).toHaveLength(1);

		// The virtualizer's re-render brings the row into the DOM, then frame 2 finds + focuses it.
		const cell = makeCell(700, 'frozen_base_price');
		container.appendChild(cell);
		frames.shift()?.();

		expect(document.activeElement).toBe(cell);
		expect(frames).toHaveLength(0); // stopped polling after a hit
	});

	it('focuses immediately when the cell already exists on the first frame', () => {
		const existing = makeCell(11, 'quantity');
		container.appendChild(existing);
		const frames: Array<() => void> = [];
		const requestFrame = (cb: () => void) => { frames.push(cb); };

		scrollToRowAndFocusCell(0, 11, 'quantity', {
			scrollToIndex: vi.fn(),
			getContainer: () => container,
			requestFrame,
		});
		frames.shift()?.(); // first frame

		expect(document.activeElement).toBe(existing);
		// No further frames were scheduled once the cell was found.
		expect(frames).toHaveLength(0);
	});

	it('gives up after maxAttempts when the cell never renders (no crash, no focus)', () => {
		const frames: Array<() => void> = [];
		const requestFrame = (cb: () => void) => { frames.push(cb); };
		const scrollToIndex = vi.fn();

		scrollToRowAndFocusCell(3, 999, 'quantity', {
			scrollToIndex,
			getContainer: () => container,
			requestFrame,
			maxAttempts: 4,
		});

		let scheduled = 0;
		let guard = 0;
		while (frames.length && guard < 50) {
			scheduled += 1;
			frames.shift()?.();
			guard += 1;
		}
		// Exactly maxAttempts frames ran; nothing was focused (the cell never appeared).
		expect(scheduled).toBe(4);
		expect(document.activeElement).toBe(document.body);
	});
});
