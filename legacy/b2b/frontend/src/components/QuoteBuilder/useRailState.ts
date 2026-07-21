import { useState, type Dispatch, type SetStateAction } from 'react';
import { useMediaQuery } from '@/hooks/use-mobile';

/** Economics-rail view state: open/collapsed (persisted), and inline-aside-vs-slide-over Sheet. */
export interface RailState {
	/** Below xl the rail becomes a slide-over Sheet; ≥xl it stays the inline collapsible <aside>. */
	railAsSheet: boolean;
	/** Inline rail expanded (≥xl) — persisted across sessions in localStorage. */
	railOpen: boolean;
	/** Slide-over Sheet open (below xl). */
	railSheetOpen: boolean;
	setRailSheetOpen: Dispatch<SetStateAction<boolean>>;
	/** Toggle + persist the inline rail's open/collapsed state. */
	toggleRail: () => void;
}

/**
 * Owns the КП economics-rail's UI-only view state (волна 3 split, extracted verbatim from the former
 * monolithic `QuoteBuilderGrid`). Deliberately kept OUT of draftItems so a rail toggle never trips
 * `hasUnsavedChanges`. No behaviour change — the same localStorage key and media queries as before.
 */
export function useRailState(): RailState {
	const [railOpen, setRailOpen] = useState<boolean>(() => {
		try {
			const saved = localStorage.getItem('kp.rail.open');
			if (saved !== null) return saved !== 'false'; // an explicit user toggle always wins
			// Default: open on wide screens, COLLAPSED on laptops (≤~1400px) so the fixed 320px rail
			// doesn't squeeze the line table into truncation/overflow (audit A1).
			return typeof window === 'undefined' || window.innerWidth >= 1400;
		} catch { return true; }
	});
	const toggleRail = () => {
		setRailOpen((open) => {
			const next = !open;
			try { localStorage.setItem('kp.rail.open', String(next)); } catch { /* private mode */ }
			return next;
		});
	};

	// Below xl the rail becomes a slide-over Sheet; ≥xl it stays the inline collapsible <aside>.
	const railAsSheet = useMediaQuery('(max-width: 1279px)');
	const [railSheetOpen, setRailSheetOpen] = useState(false);

	return { railAsSheet, railOpen, railSheetOpen, setRailSheetOpen, toggleRail };
}
