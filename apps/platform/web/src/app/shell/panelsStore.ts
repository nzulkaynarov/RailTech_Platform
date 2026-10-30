import { create } from "zustand";

/**
 * Настройки отображения панелей (docs/architecture/platform-frontend.md §1, §4.1).
 * Состояние открытия (panelOpen) живёт исключительно в URL (?panel=open).
 * В Zustand и localStorage (ключ rt-pf-panels-v2) сохраняются только предпочтения пользователя:
 * подменю (menuOpen), режим окна (panelMode: 'overlay' | 'docked') и ширина (panelWidth: 'default' | 'wide') — одни на
 * пользователя (запись `<user>|*`, UX-1a: оболочка не зависит от раздела); по разделу (`<user>|<раздел>`) — только lastTab.
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

/** Настройки оболочки, общие для всех разделов пользователя (UX-1a): подменю, режим и ширина окна. */
const USER_FIELDS = ["menuOpen", "panelMode", "panelWidth"] as const;
type UserField = (typeof USER_FIELDS)[number];

/**
 * До UX-1a подменю, режим и ширина окна помнились по разделу (`<user>|<раздел>`). Теперь каждое — одно на пользователя:
 * переносим значение, которое он выбирал чаще (при равенстве — записанное последним), в `<user>|*`, а из разделов
 * убираем; `lastTab` остаётся по разделу. Уже перенесённое не перезаписывается — перенос идемпотентный.
 */
function liftToUser(entries: Entries): { entries: Entries; changed: boolean } {
  type Vote = { counts: Map<string, number>; last: string };
  const votes = new Map<string, Map<UserField, Vote>>();
  let changed = false;
  const out: Entries = {};
  for (const [k, v] of Object.entries(entries)) {
    const bar = k.lastIndexOf("|");
    if (bar < 0 || k.slice(bar + 1) === USER_SCOPE) {
      out[k] = v;
      continue;
    }
    const user = k.slice(0, bar);
    const rest: PanelPreferencesEntry = v.lastTab === undefined ? {} : { lastTab: v.lastTab };
    for (const field of USER_FIELDS) {
      const value = v[field];
      if (value === undefined) continue;
      const byField = votes.get(user) ?? new Map<UserField, Vote>();
      const vote = byField.get(field) ?? { counts: new Map<string, number>(), last: "" };
      const key = String(value);
      vote.counts.set(key, (vote.counts.get(key) ?? 0) + 1);
      vote.last = key;
      byField.set(field, vote);
      votes.set(user, byField);
      changed = true;
    }
    if (Object.keys(rest).length > 0) out[k] = rest;
  }
  if (!changed) return { entries, changed: false };
  for (const [user, byField] of votes) {
    const key = panelsKey(user, USER_SCOPE);
    const target: Record<string, unknown> = { ...out[key] };
    for (const [field, vote] of byField) {
      if (target[field] !== undefined) continue;
      const top = Math.max(...vote.counts.values());
      const leaders = [...vote.counts].filter(([, n]) => n === top).map(([value]) => value);
      const winner = leaders.includes(vote.last) ? vote.last : (leaders[0] ?? vote.last);
      target[field] = field === "menuOpen" ? winner === "true" : winner;
    }
    out[key] = sanitizeEntry(target);
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
    const lifted = liftToUser(loaded);
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
