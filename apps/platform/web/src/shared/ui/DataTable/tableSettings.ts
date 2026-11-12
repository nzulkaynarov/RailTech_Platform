import { create } from "zustand";

/**
 * Настройки таблиц рабочих списков, которые сотрудник меняет сам (пункт «Т» плана 2026-11-12, platform-frontend.md §4.2):
 * ширина, видимость, порядок и закрепление столбцов. Хранятся в браузере на пользователя (localStorage, ключ
 * rt-pf-tables-v1, запись `<пользователь>|<таблица>`), как настройки окон (rt-pf-panels-v2); сервер не нужен — BFF без БД.
 * Нет записи или хранилище недоступно (приватное окно) — таблица по умолчанию: ширина по типу столбца.
 */
export const TABLES_STORAGE_KEY = "rt-pf-tables-v1";

export interface TableSettings {
  /** Ширина, заданная мышью или клавиатурой, px */
  sizing?: Record<string, number>;
  /** Скрытые столбцы */
  hidden?: string[];
  /** Порядок столбцов (идентификаторы) */
  order?: string[];
  /** Закреплённые слева столбцы, по порядку */
  pinned?: string[];
}

type Entries = Record<string, TableSettings>;

function strings(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const out = value.filter((item): item is string => typeof item === "string");
  return out.length > 0 ? out : undefined;
}

export function sanitizeSettings(raw: unknown): TableSettings {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const obj = raw as Record<string, unknown>;
  const out: TableSettings = {};
  if (obj.sizing && typeof obj.sizing === "object" && !Array.isArray(obj.sizing)) {
    const sizing: Record<string, number> = {};
    for (const [key, value] of Object.entries(obj.sizing as Record<string, unknown>)) {
      if (typeof value === "number" && Number.isFinite(value) && value > 0)
        sizing[key] = Math.round(value);
    }
    if (Object.keys(sizing).length > 0) out.sizing = sizing;
  }
  const hidden = strings(obj.hidden);
  if (hidden) out.hidden = hidden;
  const order = strings(obj.order);
  if (order) out.order = order;
  const pinned = strings(obj.pinned);
  if (pinned) out.pinned = pinned;
  return out;
}

function readStorage(): Entries {
  try {
    const raw = window.localStorage.getItem(TABLES_STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Entries = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      const entry = sanitizeSettings(value);
      if (Object.keys(entry).length > 0) out[key] = entry;
    }
    return out;
  } catch {
    return {};
  }
}

function writeStorage(entries: Entries): void {
  try {
    window.localStorage.setItem(TABLES_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // хранилище недоступно (приватное окно, квота) — настройка живёт до перезагрузки страницы
  }
}

function without(entries: Entries, key: string): Entries {
  return Object.fromEntries(Object.entries(entries).filter(([k]) => k !== key));
}

export function tableKey(userId: string, tableId: string): string {
  return `${userId}|${tableId}`;
}

interface TablesState {
  entries: Entries;
  /** Заменить часть настроек таблицы; пустое значение удаляет поле, пустая запись — запись целиком */
  update: (key: string, patch: Partial<TableSettings>) => void;
  reset: (key: string) => void;
}

export const useTablesStore = create<TablesState>((set) => ({
  entries: readStorage(),
  update: (key, patch) => {
    set((state) => {
      const next = sanitizeSettings({ ...state.entries[key], ...patch });
      const entries =
        Object.keys(next).length > 0
          ? { ...state.entries, [key]: next }
          : without(state.entries, key);
      writeStorage(entries);
      return { entries };
    });
  },
  reset: (key) => {
    set((state) => {
      if (!(key in state.entries)) return state;
      const entries = without(state.entries, key);
      writeStorage(entries);
      return { entries };
    });
  },
}));
