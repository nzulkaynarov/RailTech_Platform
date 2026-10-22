import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";

/**
 * Ожидания e2e строятся прямо из `packages/contracts/platform-rbac.yaml`, а не из фикстур MSW: если матрица и моки
 * разойдутся, сценарии смены роли упадут.
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

/** Подпись роли под аватаром (короткая форма, `shell.rolesShort`) */
export const ROLE_CAPTIONS: Record<Role, string> = {
  MANAGER: "Менеджер",
  DIRECTOR: "Директор",
  SUPPLY: "Снабженец",
  ENGINEER: "Гл. инженер",
  ACCOUNTANT: "Бухгалтер",
  ADMIN: "Админ",
};

type Level = "full" | "read" | "hidden";
interface Resource {
  key: string;
  module: string;
  access: Record<Role, Level>;
}

const yamlPath = resolve(
  import.meta.dirname,
  "../../../../../packages/contracts/platform-rbac.yaml",
);
const matrix = parse(readFileSync(yamlPath, "utf8")) as { resources: Resource[] };

export const MODULE_TITLES: Record<string, string> = {
  dashboard: "Dashboard",
  crm: "CRM",
  eds: "EDS",
  erp: "ERP",
  chats: "Chats",
  admin: "Admin",
};
const MODULE_ORDER = ["dashboard", "crm", "eds", "erp", "chats", "admin"];

export function visibleModules(role: Role): string[] {
  return MODULE_ORDER.filter((module) =>
    matrix.resources.some((r) => r.module === module && r.access[role] !== "hidden"),
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
  for (const resource of matrix.resources) {
    const route = ROUTE_OF[resource.key];
    if (!route) continue;
    (resource.access[role] === "hidden" ? hidden : visible).push(route);
  }
  return { hidden, visible };
}
