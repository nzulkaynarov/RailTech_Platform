import { create } from "zustand";

/**
 * Настройки отображения панелей по пользователю и разделу (docs/architecture/platform-frontend.md §1, §4).
 * Состояние открытия (panelOpen) живёт исключительно в URL (?panel=open).
 * В Zustand и localStorage (ключ rt-pf-panels-v2) сохраняются только предпочтения пользователя:
 * menuOpen, panelMode ('overlay' | 'docked'), panelWidth ('default' | 'wide'), lastTab.
 */
export const PANELS_STORAGE_KEY = "rt-pf-panels-v2";
/** Прежний ключ (до 2026-10-30): `{ menuOpen, panelOpen, tab }`; переносится один раз, `panelOpen` отбрасывается. */
export const LEGACY_PANELS_STORAGE_KEY = "rt-pf-panels-v1";

export type PanelLayoutMode = "overlay" | "docked";
export type PanelWidthPreset = "default" | "wide"; // 440px vs 600px

export interface PanelPreferencesEntry {
  menuOpen?: boolean;
  panelMode?: PanelLayoutMode; // По умолчанию 'overlay'
  panelWidth?: PanelWidthPreset; // По умолчанию 'default'
  lastTab?: string; // Фоллбэк вкладки, если в URL не передан ?tab=
}

export type PanelEntry = PanelPreferencesEntry;

type Entries = Record<string, PanelPreferencesEntry>;

function sanitizeEntry(raw: unknown): PanelPreferencesEntry {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const obj = raw as Record<string, unknown>;
  const entry: PanelPreferencesEntry = {};
  if (typeof obj.menuOpen === "boolean") entry.menuOpen = obj.menuOpen;
  if (obj.panelMode === "overlay" || obj.panelMode === "docked") entry.panelMode = obj.panelMode;
  if (obj.panelWidth === "default" || obj.panelWidth === "wide") entry.panelWidth = obj.panelWidth;
  if (typeof obj.lastTab === "string") entry.lastTab = obj.lastTab;
  return entry;
}

function migrateLegacy(): Entries {
  const raw = window.localStorage.getItem(LEGACY_PANELS_STORAGE_KEY);
  if (raw === null) return {};
  window.localStorage.removeItem(LEGACY_PANELS_STORAGE_KEY);
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  const out: Entries = {};
  for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
    if (!v || typeof v !== "object" || Array.isArray(v)) continue;
    const old = v as Record<string, unknown>;
    out[k] = sanitizeEntry({ menuOpen: old.menuOpen, lastTab: old.tab });
  }
  writeStorage(out);
  return out;
}

function readStorage(): Entries {
  try {
    const raw = window.localStorage.getItem(PANELS_STORAGE_KEY);
    if (!raw) return migrateLegacy();
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Entries = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      out[k] = sanitizeEntry(v);
    }
    return out;
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
  /** Перечитать хранилище (тесты переноса со старого ключа) */
  reload: () => void;
}

export const usePanelsStore = create<PanelsState>()((set) => ({
  entries: readStorage(),
  reload: () => {
    set({ entries: readStorage() });
  },
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
