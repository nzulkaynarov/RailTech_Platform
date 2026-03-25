import { create } from 'zustand';

interface LoadingState {
    isPageLoading: boolean;
    setPageLoading: (loading: boolean) => void;
}

export const useLoadingStore = create<LoadingState>((set) => ({
    isPageLoading: false,
    setPageLoading: (loading) => set({ isPageLoading: loading }),
}));
