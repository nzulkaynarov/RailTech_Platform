import { useCallback, useState } from 'react';

/** localStorage key for the set of collapsed SECTION row ids (U5). Quote-item ids are globally
 *  unique, so a single flat key never collides across КП. */
const STORAGE_KEY = 'kp.sections.collapsed';

function loadCollapsed(): Set<number> {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (!saved) return new Set();
		const parsed: unknown = JSON.parse(saved);
		if (!Array.isArray(parsed)) return new Set();
		return new Set(parsed.filter((value): value is number => typeof value === 'number'));
	} catch {
		return new Set();
	}
}

export interface SectionCollapseState {
	/** Row ids of the currently collapsed SECTION headings. */
	collapsedSections: Set<number>;
	/** Is this SECTION collapsed right now? */
	isSectionCollapsed: (sectionId: number) => boolean;
	/** Collapse ↔ expand a SECTION and persist the change. */
	toggleSectionCollapse: (sectionId: number) => void;
}

/**
 * U5 — owns the КП builder's collapsed-section view state: a set of SECTION row ids, persisted in
 * localStorage (mirrors the `useRailState` pattern). Deliberately UI-only and kept OUT of
 * `draftItems`, so collapsing a section never trips `hasUnsavedChanges` and touches no API / DB.
 */
export function useSectionCollapse(): SectionCollapseState {
	const [collapsedSections, setCollapsedSections] = useState<Set<number>>(loadCollapsed);

	const toggleSectionCollapse = useCallback((sectionId: number) => {
		setCollapsedSections((current) => {
			const next = new Set(current);
			if (next.has(sectionId)) next.delete(sectionId);
			else next.add(sectionId);
			try {
				localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
			} catch {
				/* private mode — persistence is best-effort */
			}
			return next;
		});
	}, []);

	const isSectionCollapsed = useCallback(
		(sectionId: number) => collapsedSections.has(sectionId),
		[collapsedSections],
	);

	return { collapsedSections, isSectionCollapsed, toggleSectionCollapse };
}
