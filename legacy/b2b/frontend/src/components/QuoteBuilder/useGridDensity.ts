import { useCallback, useState } from 'react';
import { GRID_DENSITIES, GRID_DENSITY_DEFAULT, type GridDensity } from './gridConstants';

/** localStorage key for the КП grid's row density preference (U7). A single flat key — the
 *  preference is per-user, not per-КП. */
const STORAGE_KEY = 'kp.grid.density';

function loadDensity(): GridDensity {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved !== null && (GRID_DENSITIES as readonly string[]).includes(saved)) {
			return saved as GridDensity;
		}
	} catch {
		/* private mode — fall through to the default */
	}
	return GRID_DENSITY_DEFAULT;
}

export interface GridDensityState {
	/** Current row density — `comfortable` (default) or `compact`. */
	gridDensity: GridDensity;
	/** Flip comfortable ↔ compact and persist the choice. */
	toggleGridDensity: () => void;
}

/**
 * U7 — owns the КП builder grid's row-density preference: `comfortable` (default) ↔ `compact`,
 * persisted in localStorage (mirrors the `useRailState` / `useSectionCollapse` pattern). Deliberately
 * UI-only and kept OUT of `draftItems`, so switching density never trips `hasUnsavedChanges` and
 * touches no API / DB. The density drives BOTH the row padding class and the virtualizer's
 * `estimateSize`, kept in lockstep via `gridConstants` (see GRID_DENSITY_ROW_HEIGHT / _PADDING).
 */
export function useGridDensity(): GridDensityState {
	const [gridDensity, setGridDensity] = useState<GridDensity>(loadDensity);

	const toggleGridDensity = useCallback(() => {
		setGridDensity((current) => {
			const next: GridDensity = current === 'comfortable' ? 'compact' : 'comfortable';
			try {
				localStorage.setItem(STORAGE_KEY, next);
			} catch {
				/* private mode — persistence is best-effort */
			}
			return next;
		});
	}, []);

	return { gridDensity, toggleGridDensity };
}
