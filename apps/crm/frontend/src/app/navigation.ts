import type { PermissionsResponse } from "../api/generated/model";
import { t } from "../i18n/ru";
import { allowed, canSee, sectionPermission } from "./providers/access";

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
  | "sandbox"
  | "settings"
  | "templates"
  | "users"
  | "integrations"
  | "models"
  | "system"
  | "external-services"
  | "backups"
  | "audit";

export type NavGroup = { key: string; title: string; items: NavKey[] };

export const NAV_GROUPS: NavGroup[] = [
  { key: "work", title: t.navGroup.work, items: ["inbox", "leads", "clients", "deals"] },
  { key: "analytics", title: t.navGroup.analytics, items: ["dashboard", "spend"] },
  { key: "bot", title: t.navGroup.bot, items: ["kb", "gaps", "sandbox", "templates", "settings"] },
  {
    key: "admin",
    title: t.navGroup.admin,
    items: ["users", "integrations", "models", "system", "external-services", "backups", "audit"],
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
 * Порядок поиска стартового раздела: очередь работы, дашборд, лиды, клиенты, сделки; затем администрирование
 * (пользователи, подключения, ...) и остальные разделы в порядке меню. Системному «Администратору»
 * без бизнес-прав это даёт «Пользователи», а не «Настройки бота».
 */
const ADMIN_ITEMS = NAV_GROUPS.find((g) => g.key === "admin")?.items ?? [];
const START_ORDER: NavKey[] = [
  "inbox",
  "dashboard",
  "leads",
  "clients",
  "deals",
  ...ADMIN_ITEMS,
  ...NAV_GROUPS.flatMap((g) => g.items),
];

/**
 * Стартовая страница — первый доступный по правам раздел (одно правило для «/», входа и `/setup`):
 * менеджер и админ с бизнес-правами — «Входящие», наблюдатель — дашборд, системный «Администратор»
 * без прав на лиды — «Пользователи». Режим «Админ/Менеджер» не учитывается: он только навигация,
 * а админский раздел в режиме «Менеджер» открывается с баннером возврата. «Профиль» доступен всем.
 */
export function homePath(matrix: PermissionsResponse | undefined): string {
  for (const key of START_ORDER) {
    const target = sectionPermission(key);
    if (target && allowed(matrix, target[0], target[1])) return `/${key}`;
  }
  return "/profile";
}
