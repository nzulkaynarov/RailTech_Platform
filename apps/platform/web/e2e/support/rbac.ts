import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";

/**
 * Ожидания e2e строятся прямо из `packages/contracts/platform-rbac.yaml` (каталог версии 2: системные роли и шаблоны),
 * а не из фикстур MSW: если каталог и моки разойдутся, сценарии смены роли упадут.
 */
export type Role = "MANAGER" | "DIRECTOR" | "SUPPLY" | "ENGINEER" | "ACCOUNTANT" | "ADMIN";
export const ROLES: readonly Role[] = [
  "MANAGER",
  "DIRECTOR",
  "SUPPLY",
  "ENGINEER",
  "ACCOUNTANT",
  "ADMIN",
];
export const ROLE_NAMES: Record<Role, string> = {
  MANAGER: "Менеджер",
  DIRECTOR: "Директор",
  SUPPLY: "Снабженец",
  ENGINEER: "Гл. инженер",
  ACCOUNTANT: "Бухгалтер",
  ADMIN: "Администратор",
};

/** Подпись роли под аватаром — название роли из данных (ADR-0012), без сокращений по коду. */
export const ROLE_CAPTIONS: Record<Role, string> = ROLE_NAMES;

type Level = "full" | "read";
interface CatalogRole {
  access: Partial<Record<string, Level>>;
}
interface Catalog {
  resources: { key: string; module: string }[];
  menu: Record<string, Record<string, string[]>>;
  system_roles: Partial<Record<string, CatalogRole>>;
  templates: Partial<Record<string, CatalogRole>>;
}

const yamlPath = resolve(
  import.meta.dirname,
  "../../../../../packages/contracts/platform-rbac.yaml",
);
const catalog = parse(readFileSync(yamlPath, "utf8")) as Catalog;

/** Матрица предустановки (системной роли или шаблона) — роли из MSW создаются по ней (id 1–6). */
function accessOf(role: Role): Partial<Record<string, Level>> {
  return (catalog.system_roles[role] ?? catalog.templates[role])?.access ?? {};
}

/** Имена модулей в рейле (ru, `modules:<code>.name`, UX-оценка 2026-10-27 §6.1). */
export const MODULE_TITLES: Record<string, string> = {
  dashboard: "Главная",
  crm: "Клиенты",
  eds: "Документы",
  erp: "Расчёт",
  chats: "Чаты",
  admin: "Настройки",
};
const MODULE_ORDER = ["dashboard", "crm", "eds", "erp", "chats", "admin"];

/** Модули рейла роли: виден хотя бы один пункт меню модуля (секция `menu` каталога). */
export function visibleModules(role: Role): string[] {
  const access = accessOf(role);
  return MODULE_ORDER.filter((module) =>
    Object.values(catalog.menu[module] ?? {}).some((sections) =>
      sections.some((key) => access[key] !== undefined),
    ),
  ).map((module) => MODULE_TITLES[module] ?? module);
}

/** Адрес раздела, который открывает ресурс матрицы; у ресурсов без отдельного экрана адреса нет. */
const ROUTE_OF: Record<string, string> = {
  "dashboard.summary": "/dashboard/summary",
  "crm.leads": "/crm/leads",
  "crm.clients": "/crm/clients",
  "eds.inbox": "/eds/inbox",
  "eds.drafts": "/eds/drafts",
  "eds.projects": "/eds/projects",
  "eds.payments": "/eds/payments",
  "erp.calc": "/erp/calc",
  "erp.stock": "/erp/stock",
  "chats.external": "/chats?scope=external",
  admin: "/admin/roles",
};

export function routesFor(role: Role): { hidden: string[]; visible: string[] } {
  const hidden: string[] = [];
  const visible: string[] = [];
  const access = accessOf(role);
  for (const resource of catalog.resources) {
    const route = ROUTE_OF[resource.key];
    if (!route) continue;
    (access[resource.key] === undefined ? hidden : visible).push(route);
  }
  return { hidden, visible };
}
