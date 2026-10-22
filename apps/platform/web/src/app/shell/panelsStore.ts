import { create } from "zustand";

/**
 * Состояние панелей по пользователю и разделу (03-frontend.md §1, §4): подменю, боковое окно, вкладка.
 * Хранится в Zustand и `localStorage` (каждое обращение — в try/catch: приватное окно, заблокированные
 * данные сайта); боковое окно и вкладка дополнительно живут в `?panel=&tab=` и имеют приоритет при открытии ссылки.
 */
export const PANELS_STORAGE_KEY = "rt-pf-panels-v1";

export interface PanelEntry {
  menuOpen?: boolean;
  panelOpen?: boolean;
  tab?: string;
}

type Entries = Record<string, PanelEntry>;

function readStorage(): Entries {
  try {
    const raw = window.localStorage.getItem(PANELS_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Entries)
      : {};
  } catch {
    return {};
  }
}

function writeStorage(entries: Entries): void {
  try {
    window.localStorage.setItem(PANELS_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Хранилище недоступно — состояние живёт только в памяти вкладки.
  }
}

interface PanelsState {
  entries: Entries;
  patch: (key: string, patch: PanelEntry) => void;
}

export const usePanelsStore = create<PanelsState>()((set) => ({
  entries: readStorage(),
  patch: (key, patch) => {
    set((state) => {
      const entries = { ...state.entries, [key]: { ...state.entries[key], ...patch } };
      writeStorage(entries);
      return { entries };
    });
  },
}));

export function panelsKey(userId: string, sectionPath: string): string {
  return `${userId}|${sectionPath}`;
}
