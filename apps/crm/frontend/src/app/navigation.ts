import type { PermissionsResponse } from "../api/generated/model";
import { t } from "../i18n/ru";
import { canSee } from "./providers/access";

/**
 * Информационная архитектура меню (аудит 2026-10-12, бенчмарк Front/Intercom/Linear):
 * группы по задачам, подпись пункта == заголовок страницы. Профиль и выход — в меню
 * пользователя в шапке, не в сайдбаре.
 */
export type NavKey =
  | "inbox"
  | "leads"
  | "clients"
  | "deals"
  | "dashboard"
  | "spend"
  | "kb"
  | "gaps"
  | "settings"
  | "users"
  | "integrations"
  | "models"
  | "system"
  | "backups"
  | "audit";

export type NavGroup = { key: string; title: string; items: NavKey[] };

export const NAV_GROUPS: NavGroup[] = [
  { key: "work", title: t.navGroup.work, items: ["inbox", "leads", "clients", "deals"] },
  { key: "analytics", title: t.navGroup.analytics, items: ["dashboard", "spend"] },
  { key: "bot", title: t.navGroup.bot, items: ["kb", "gaps", "settings"] },
  {
    key: "admin",
    title: t.navGroup.admin,
    items: ["users", "integrations", "models", "system", "backups", "audit"],
  },
];

const NAV_KEYS = new Set<string>(NAV_GROUPS.flatMap((g) => g.items));

/** Группы меню с видимыми пунктами; пустые группы не показываются (без «висячих» заголовков). */
export function visibleNav(
  matrix: PermissionsResponse | undefined,
  uiMode: string | null | undefined,
): NavGroup[] {
  return NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((key) => canSee(key, matrix, uiMode)),
  })).filter((g) => g.items.length > 0);
}

/** Пункт меню по адресу: `/leads/12` → `leads`. */
export function navKeyOf(pathname: string): NavKey | null {
  const first = pathname.split("/")[1] ?? "";
  return NAV_KEYS.has(first) ? (first as NavKey) : null;
}

/**
 * Стартовая страница: менеджер и админ — очередь «Входящие», наблюдатель — дашборд.
 * Без доступа к обоим — список лидов.
 */
export function homePath(matrix: PermissionsResponse | undefined): string {
  if (matrix?.permissions["leads"]?.["take"]) return "/inbox";
  if (matrix?.permissions["dashboard"]?.["read"]) return "/dashboard";
  return "/leads";
}
