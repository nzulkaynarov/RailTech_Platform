import { create } from "zustand";

/**
 * Настройки отображения панелей (docs/architecture/platform-frontend.md §1, §4.1).
 * Состояние открытия (panelOpen) живёт исключительно в URL (?panel=open).
 * В Zustand и localStorage (ключ rt-pf-panels-v2) сохраняются только предпочтения пользователя:
 * подменю (menuOpen) — одно на пользователя (запись `<user>|*`, UX-1a); по разделу (`<user>|<раздел>`) —
 * panelMode ('overlay' | 'docked'), panelWidth ('default' | 'wide'), lastTab.
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

/** Раздел записи с настройками пользователя целиком (подменю): `<user>|*`. */
export const USER_SCOPE = "*";

/**
 * До UX-1a подменю помнилось по разделу (`<user>|<раздел>`.menuOpen). Теперь значение одно на пользователя: переносим
 * выбор, который он делал чаще (при равенстве — записанный последним), в `<user>|*`, а из разделов убираем. Записи без
 * menuOpen и уже перенесённые не трогаем — перенос идемпотентный.
 */
function liftMenuToUser(entries: Entries): { entries: Entries; changed: boolean } {
  const votes = new Map<string, { open: number; closed: number; last: boolean }>();
  for (const [k, v] of Object.entries(entries)) {
    const bar = k.lastIndexOf("|");
    if (bar < 0 || k.slice(bar + 1) === USER_SCOPE || v.menuOpen === undefined) continue;
    const user = k.slice(0, bar);
    const vote = votes.get(user) ?? { open: 0, closed: 0, last: v.menuOpen };
    if (v.menuOpen) vote.open += 1;
    else vote.closed += 1;
    vote.last = v.menuOpen;
    votes.set(user, vote);
  }
  if (votes.size === 0) return { entries, changed: false };
  const out: Entries = {};
  for (const [k, v] of Object.entries(entries)) {
    const bar = k.lastIndexOf("|");
    if (bar >= 0 && k.slice(bar + 1) !== USER_SCOPE && v.menuOpen !== undefined) {
      const rest = { ...v };
      delete rest.menuOpen;
      if (Object.keys(rest).length > 0) out[k] = rest;
    } else {
      out[k] = v;
    }
  }
  for (const [user, vote] of votes) {
    const key = panelsKey(user, USER_SCOPE);
    if (out[key]?.menuOpen !== undefined) continue;
    const menuOpen = vote.open === vote.closed ? vote.last : vote.open > vote.closed;
    out[key] = { ...out[key], menuOpen };
  }
  return { entries: out, changed: true };
}

function readStorage(): Entries {
  try {
    const raw = window.localStorage.getItem(PANELS_STORAGE_KEY);
    const loaded = (() => {
      if (!raw) return migrateLegacy();
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
      const out: Entries = {};
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        out[k] = sanitizeEntry(v);
      }
      return out;
    })();
    const lifted = liftMenuToUser(loaded);
    if (lifted.changed) writeStorage(lifted.entries);
    return lifted.entries;
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
