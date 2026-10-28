import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { parse } from "yaml";
import { describe, expect, it } from "vitest";

import { MODULES as REGISTRY } from "../modules/registry";
import {
  MENU,
  MODULES,
  QUEUE,
  RESOURCE_KEYS,
  RESOURCES,
  RESTRICTED_FIELDS,
  SYSTEM_ROLES,
  TEMPLATES,
  allows,
  menuItemVisible,
  mergeAccess,
  modulesOf,
  sectionsWithBackend,
  visibleMenuItems,
  type Access,
  type ModuleCode,
} from "./rbac.generated";

/**
 * Каталог возможностей версии 2 (ADR-0012): сгенерированный файл = `packages/contracts/platform-rbac.yaml`, а функции
 * доступа считают по матрицам ролей (данным), а не по кодам. Эталон шести предустановок — отдельно, дословно (как
 * tests/rbac_oracle.py в BFF): колонки ADMIN, DIRECTOR, MANAGER, SUPPLY, ENGINEER, ACCOUNTANT; F — full, R — read, H — скрыто.
 */
interface Yaml {
  version: number;
  resources: { key: string; module: string; levels?: string[]; label: Record<string, string> }[];
  menu: Record<string, Record<string, string[]>>;
  restricted_fields: Record<string, { description: Record<string, string> }>;
  queue: Record<string, { resource: string; level: string }>;
  system_roles: Record<string, { name: Record<string, string>; access: Record<string, string> }>;
  templates: Record<string, { name: Record<string, string>; access: Record<string, string> }>;
}
const spec = parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../packages/contracts/platform-rbac.yaml"),
    "utf8",
  ),
) as Yaml;

const ORACLE: Record<string, string> = {
  "dashboard.queue": "FFFFFF",
  "dashboard.summary": "HFHHHR",
  "crm.leads": "HRFHHH",
  "crm.clients": "HFFRRR",
  "eds.inbox": "HFRHHR",
  "eds.drafts": "HFRHHH",
  "eds.projects": "HFRRRF",
  "eds.payments": "HRRHHF",
  "eds.memo.create": "FFFFFF",
  "eds.memo.approve": "HFHHHH",
  "erp.calc": "HFHFFR",
  "erp.calc.goods": "HFHFHH",
  "erp.calc.services": "HFHHFH",
  "erp.stock": "HFRFFR",
  "chats.internal": "FFFFFF",
  "chats.external": "HRFHHF",
  admin: "FRHHHH",
  "company.settings": "FFHHHH",
};
const COLUMNS = ["ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"] as const;
type Column = (typeof COLUMNS)[number];

function oracleAccess(code: Column): Access {
  const access: Access = {};
  for (const [key, row] of Object.entries(ORACLE)) {
    const letter = row[COLUMNS.indexOf(code)];
    if (letter === "F") access[key] = "full";
    if (letter === "R") access[key] = "read";
  }
  return access;
}

const catalog = { ...SYSTEM_ROLES, ...TEMPLATES } as Record<Column, { access: Access }>;

describe("rbac.generated: каталог = контракт", () => {
  it("version 2, разделы в порядке контракта с модулем, уровнями и подписью", () => {
    expect(spec.version).toBe(2);
    expect(RESOURCE_KEYS).toEqual(spec.resources.map((r) => r.key));
    for (const row of spec.resources) {
      const def = RESOURCES[row.key as keyof typeof RESOURCES];
      expect(def.module).toBe(row.module);
      expect([...def.levels]).toEqual(row.levels ?? ["read", "full"]);
      expect(def.label).toEqual(row.label);
    }
    expect(MODULES).toEqual(Object.keys(spec.menu));
  });

  it("меню, поля с ограничением и очередь — как в контракте", () => {
    expect(MENU).toEqual(spec.menu);
    expect(Object.keys(RESTRICTED_FIELDS)).toEqual(Object.keys(spec.restricted_fields));
    for (const [name, field] of Object.entries(spec.restricted_fields)) {
      expect(RESTRICTED_FIELDS[name as keyof typeof RESTRICTED_FIELDS]).toEqual(field.description);
    }
    expect(QUEUE).toEqual(spec.queue);
  });

  it("системные роли и шаблоны = эталон (матрица каталога версии 2)", () => {
    expect(Object.keys(SYSTEM_ROLES)).toEqual(["ADMIN", "DIRECTOR"]);
    expect(Object.keys(TEMPLATES)).toEqual(["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"]);
    for (const code of COLUMNS) {
      expect(catalog[code].access, code).toEqual(oracleAccess(code));
      const source = spec.system_roles[code] ?? spec.templates[code];
      expect(source?.access).toEqual(oracleAccess(code));
    }
  });

  it("подменю модулей Платформы = секция menu каталога (пункты и разделы)", () => {
    for (const module of REGISTRY) {
      const items = MENU[module.code];
      expect(
        module.sections.filter((s) => !s.hidden).map((s) => s.key),
        module.code,
      ).toEqual(Object.keys(items));
      for (const section of module.sections.filter((s) => !s.hidden)) {
        const rule = section.menuAccess ?? section.access;
        const sections = "resource" in rule ? [rule.resource] : [...rule.anyOf];
        const expected = (items as Record<string, readonly string[]>)[section.key] ?? [];
        expect([...sections].sort(), `${module.code}.${section.key}`).toEqual([...expected].sort());
      }
    }
  });
});

describe("rbac.generated: доступ по матрицам ролей", () => {
  it("объединение — максимум по разделу, порядок каталога", () => {
    const merged = mergeAccess([
      { "crm.leads": "read", "eds.payments": "full" },
      { "crm.leads": "full", "eds.inbox": "read" },
    ]);
    expect(merged).toEqual({ "crm.leads": "full", "eds.inbox": "read", "eds.payments": "full" });
    expect(Object.keys(merged)).toEqual(["crm.leads", "eds.inbox", "eds.payments"]);
    expect(mergeAccess([])).toEqual({});
  });

  it.each(COLUMNS)("предустановка %s: allows по каждой ячейке эталона", (code) => {
    const access = catalog[code].access;
    for (const key of RESOURCE_KEYS) {
      const level = access[key];
      expect(allows(access, key, "read"), `${code} ${key}`).toBe(level !== undefined);
      expect(allows(access, key, "full"), `${code} ${key}`).toBe(level === "full");
    }
  });

  it("модули — по видимым пунктам меню; виза расчёта без пункта модуль не открывает", () => {
    // W13-A5: «База знаний» CRM открывает и раздел `admin` — у администратора есть модуль CRM (только этот пункт)
    // W15-H4: базу знаний администратор открывает из Настроек · Telegram-бот — Клиентов в его рейле нет
    expect(modulesOf(catalog.ADMIN.access)).toEqual(["dashboard", "eds", "chats", "admin"]);
    expect(visibleMenuItems(catalog.ADMIN.access, "crm")).toEqual([]);
    expect(modulesOf(catalog.DIRECTOR.access)).toEqual<ModuleCode[]>([...MODULES]);
    expect(modulesOf({ "crm.leads": "full", "eds.payments": "full" })).toEqual(["crm", "eds"]);
    expect(modulesOf({ "erp.calc.goods": "full" })).toEqual([]);
    expect(modulesOf({})).toEqual([]);
  });

  it("пункты меню: виден любой из разделов пункта", () => {
    const mixed: Access = { "crm.leads": "full", "eds.payments": "full" };
    expect(visibleMenuItems(mixed, "crm")).toEqual(["messages", "leads", "channels", "kb"]);
    expect(visibleMenuItems(mixed, "eds")).toEqual(["documents", "payments"]);
    expect(menuItemVisible(catalog.ACCOUNTANT.access, "dashboard", "summary")).toBe(true);
    expect(menuItemVisible(catalog.MANAGER.access, "dashboard", "summary")).toBe(false);
    expect(menuItemVisible(mixed, "crm", "no-such-item")).toBe(false);
  });

  it("разделы с правами бэкенда: CRM у лидов, ERP у счетов и оплат", () => {
    const mixed: Access = { "crm.leads": "full", "eds.payments": "full" };
    expect(sectionsWithBackend(mixed, "crm")).toEqual(["crm.leads"]);
    expect(sectionsWithBackend(mixed, "erp")).toEqual(["eds.payments"]);
    expect(sectionsWithBackend({ "dashboard.queue": "full" }, "erp")).toEqual([]);
  });
});
