import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface DemoState {
  /** When true, demo/simulation controls are visible (for investor presentations) */
  isDemoMode: boolean;
  enableDemoMode: () => void;
  disableDemoMode: () => void;
  toggleDemoMode: () => void;
}

export const useDemoStore = create<DemoState>()(
  persist(
    (set) => ({
      isDemoMode: false,
      enableDemoMode: () => set({ isDemoMode: true }),
      disableDemoMode: () => set({ isDemoMode: false }),
      toggleDemoMode: () => set((s) => ({ isDemoMode: !s.isDemoMode })),
    }),
    {
      name: 'railtech-demo',
    }
  )
);
