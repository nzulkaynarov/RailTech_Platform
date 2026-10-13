import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useGridDensity } from '@/components/QuoteBuilder/useGridDensity';
import {
	GRID_DENSITY_DEFAULT,
	GRID_DENSITY_ROW_HEIGHT,
	GRID_DENSITY_ROW_PADDING,
} from '@/components/QuoteBuilder/gridConstants';

const STORAGE_KEY = 'kp.grid.density';

/**
 * U7 — the КП grid's row-density preference (comfortable ↔ compact), persisted in localStorage.
 * The estimateSize (row height) and the padding class MUST stay in lockstep — a mismatch makes the
 * virtualizer reserve the wrong height for off-screen rows and the scrollbar jumps.
 */
describe('useGridDensity', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('defaults to comfortable when nothing is persisted', () => {
		const { result } = renderHook(() => useGridDensity());
		expect(result.current.gridDensity).toBe('comfortable');
		expect(GRID_DENSITY_DEFAULT).toBe('comfortable');
	});

	it('toggles comfortable ↔ compact', () => {
		const { result } = renderHook(() => useGridDensity());

		act(() => result.current.toggleGridDensity());
		expect(result.current.gridDensity).toBe('compact');

		act(() => result.current.toggleGridDensity());
		expect(result.current.gridDensity).toBe('comfortable');
	});

	it('persists the choice to localStorage', () => {
		const { result } = renderHook(() => useGridDensity());

		act(() => result.current.toggleGridDensity());
		expect(localStorage.getItem(STORAGE_KEY)).toBe('compact');
	});

	it('restores the persisted density on mount', () => {
		localStorage.setItem(STORAGE_KEY, 'compact');
		const { result } = renderHook(() => useGridDensity());
		expect(result.current.gridDensity).toBe('compact');
	});

	it('ignores a corrupt persisted value and falls back to the default', () => {
		localStorage.setItem(STORAGE_KEY, 'ultra-dense');
		const { result } = renderHook(() => useGridDensity());
		expect(result.current.gridDensity).toBe('comfortable');
	});

	it('keeps estimateSize and the padding class consistent — compact is shorter and less padded', () => {
		// The virtualizer estimate and the padding class are the two things density changes; if they
		// ever disagree the window math breaks. Compact MUST be both a smaller height and a smaller
		// vertical padding than comfortable.
		expect(GRID_DENSITY_ROW_HEIGHT.compact).toBeLessThan(GRID_DENSITY_ROW_HEIGHT.comfortable);
		expect(GRID_DENSITY_ROW_PADDING.comfortable).toBe('py-1.5');
		expect(GRID_DENSITY_ROW_PADDING.compact).toBe('py-0.5');
		// Both densities must be defined for the whole GridDensity union.
		expect(Object.keys(GRID_DENSITY_ROW_HEIGHT).sort()).toEqual(Object.keys(GRID_DENSITY_ROW_PADDING).sort());
	});
});
