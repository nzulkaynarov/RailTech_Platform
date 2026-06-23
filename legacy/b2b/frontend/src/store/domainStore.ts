import { create } from 'zustand';

/**
 * Domain code is a string from the DB (e.g. 'RAILWAY_MACHINERY').
 * NOT hardcoded as a union — new domains can be added via admin panel.
 */
export type DomainCode = string;

interface Filters {
	category: number | null;
	brand: number | null;
	equipment_groups: number | null;
	stock_status: string | null;
}

interface DomainState {
	activeDomain: DomainCode | null;
	setActiveDomain: (domain: DomainCode | null) => void;
	filters: Filters;
	setFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void;
	resetFilters: () => void;
}

const initialFilters: Filters = {
	category: null,
	brand: null,
	equipment_groups: null,
	stock_status: null,
};

export const useDomainStore = create<DomainState>((set) => ({
	activeDomain: null,
	setActiveDomain: (domain) => set({ activeDomain: domain, filters: initialFilters }),
	filters: initialFilters,
	setFilter: (key, value) => set((state) => ({
		filters: { ...state.filters, [key]: value }
	})),
	resetFilters: () => set({ filters: initialFilters }),
}));
