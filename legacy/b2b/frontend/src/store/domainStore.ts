import { create } from 'zustand';

export type DomainType = 'RAILWAY_MACHINERY' | 'GENERAL_GOODS' | 'SERVICES';

interface Filters {
	category: number | null;
	manufacturer: number | null;
	equipment_groups: number | null;
	stock_status: string | null;
}

interface DomainState {
	activeDomain: DomainType | null;
	setActiveDomain: (domain: DomainType | null) => void;
	filters: Filters;
	setFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void;
	resetFilters: () => void;
}

const initialFilters: Filters = {
	category: null,
	manufacturer: null,
	equipment_groups: null,
	stock_status: null,
};

export const useDomainStore = create<DomainState>((set) => ({
	activeDomain: null,
	setActiveDomain: (domain) => set({ activeDomain: domain, filters: initialFilters }), // Reset filters on domain change
	filters: initialFilters,
	setFilter: (key, value) => set((state) => ({
		filters: { ...state.filters, [key]: value }
	})),
	resetFilters: () => set({ filters: initialFilters }),
}));
