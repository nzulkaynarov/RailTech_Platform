import { matchPath } from "react-router";

import { admin } from "./admin/module";
import { chats } from "./chats/module";
import { crm } from "./crm/module";
import { dashboard } from "./dashboard/module";
import { eds } from "./eds/module";
import { erp } from "./erp/module";
import type { ModuleConfig, SectionConfig } from "./types";

/** Шесть модулей в порядке рейла (SPEC-v3 §6.1). Конфигурация без кода страниц: страницы модулей грузятся лениво. */
export const MODULES: readonly ModuleConfig[] = [dashboard, crm, eds, erp, chats, admin];

/** Модуль по коду; неизвестный код из `Me.modules` (новый модуль на BFF, старая сборка SPA) — undefined, а не ошибка. */
export function findModule(code: string): ModuleConfig | undefined {
  return MODULES.find((m) => m.code === code);
}

export interface SectionMatch {
  module: ModuleConfig;
  section: SectionConfig;
  /** Номер объекта из `:id` / `:userId` в карточке; для списка — undefined */
  objectId?: string;
}

/** Бизнес-номер из пути: `%D0%9A%D0%9F-2026/118` -> `КП-2026/118` (react-router декодирует `%2F`, но не остальное). */
function decoded(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function splitPath(path: string): { pathname: string; query: URLSearchParams } {
  const [pathname = "", search = ""] = path.split("?");
  return { pathname, query: new URLSearchParams(search) };
}

function queryMatches(want: URLSearchParams, have: URLSearchParams): boolean {
  for (const [key, value] of want) if (have.get(key) !== value) return false;
  return true;
}

/**
 * Раздел по адресу. Сначала пункты с `?tab=` в пути (Chats · Внутренний), затем точные пути списков,
 * затем карточки объектов (`/chats/contacts` раньше `/chats/:id`). Нет совпадения — undefined (404 внутри каркаса).
 */
export function matchSection(pathname: string, search = ""): SectionMatch | undefined {
  const have = new URLSearchParams(search);
  const all = MODULES.flatMap((module) => module.sections.map((section) => ({ module, section })));

  for (const { module, section } of all) {
    const { pathname: p, query } = splitPath(section.path);
    if (query.size > 0 && p === pathname && queryMatches(query, have)) return { module, section };
  }
  for (const { module, section } of all) {
    const { pathname: p, query } = splitPath(section.path);
    if (query.size === 0 && p === pathname) return { module, section };
  }
  for (const { module, section } of all) {
    if (!section.detail) continue;
    const hit = matchPath({ path: section.detail, end: true }, pathname);
    if (hit) {
      const id = hit.params["id"] ?? hit.params["userId"];
      return id === undefined ? { module, section } : { module, section, objectId: decoded(id) };
    }
  }
  return undefined;
}

/** Пункт подменю активен: тот же путь и те же query-параметры, что задаёт пункт; карточка объекта подсвечивает свой список. */
export function isSectionActive(section: SectionConfig, match: SectionMatch | undefined): boolean {
  return match?.section.key === section.key && match.section.path === section.path;
}
