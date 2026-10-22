import { describe, expect, it } from "vitest";

import {
  MENU,
  MODULES,
  RESOURCES,
  RESTRICTED_FIELDS,
  ROLES,
  allows,
  canSee,
  levelFor,
  menuItemVisible,
  visibleMenuItems,
  visibleModules,
  visibleRestrictedFields,
  type AccessLevel,
  type ResourceKey,
  type RoleCode,
} from "./rbac.generated";

/**
 * Эталон — матрица SPEC-v3 §4.2 дословно, независимо от YAML и генератора (как tests/rbac_oracle.py в BFF).
 * Колонки: MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT, ADMIN; F — full, R — read, H — hidden.
 * Меняется вместе с packages/contracts/platform-rbac.yaml: тесты падают, пока файл и эталон расходятся.
 */
const ORACLE: Record<string, string> = {
  "dashboard.queue": "FFFFFF",
  "dashboard.summary": "HFHHRH",
  "crm.leads": "FRHHHH",
  "crm.clients": "FRRRRH",
  "eds.inbox": "RFHHRH",
  "eds.drafts": "RFHHHH",
  "eds.projects": "RFRRFH",
  "eds.payments": "RRHHFH",
  "eds.memo.create": "FFFFFF",
  "eds.memo.approve": "HFHHHH",
  "erp.calc": "HFFFRH",
  "erp.stock": "RFFFRH",
  "chats.internal": "FFFFFF",
  "chats.external": "FRHHFH",
  admin: "HRHHHF",
};
const ORACLE_ROLES: readonly RoleCode[] = [
  "MANAGER",
  "DIRECTOR",
  "SUPPLY",
  "ENGINEER",
  "ACCOUNTANT",
  "ADMIN",
];
const LEVEL: Record<string, AccessLevel> = { F: "full", R: "read", H: "hidden" };
const RANK: Record<AccessLevel, number> = { hidden: 0, read: 1, full: 2 };

const KEYS = Object.keys(ORACLE) as ResourceKey[];

function oracleLevel(role: RoleCode, key: string): AccessLevel {
  const row = ORACLE[key];
  const letter = row?.[ORACLE_ROLES.indexOf(role)];
  const level = letter === undefined ? undefined : LEVEL[letter];
  if (level === undefined) throw new Error(`нет эталона: ${role} ${key}`);
  return level;
}

function oracleUnion(roles: readonly RoleCode[], key: string): AccessLevel {
  return roles.reduce<AccessLevel>((best, role) => {
    const level = oracleLevel(role, key);
    return RANK[level] > RANK[best] ? level : best;
  }, "hidden");
}

const CELLS = ORACLE_ROLES.flatMap((role) => KEYS.map((key) => [role, key] as const));

describe("rbac.generated: матрица", () => {
  it("шесть ролей и пятнадцать разделов в порядке SPEC-v3 §4.2", () => {
    expect([...ROLES]).toEqual(ORACLE_ROLES);
    expect(Object.keys(RESOURCES)).toEqual(KEYS);
    expect(CELLS).toHaveLength(90);
  });

  it.each(CELLS)("%s · %s: уровень, видимость, чтение и изменение", (role, key) => {
    const expected = oracleLevel(role, key);

    expect(RESOURCES[key].access[role]).toBe(expected);
    expect(levelFor([role], key)).toBe(expected);
    expect(canSee([role], key)).toBe(expected !== "hidden");
    expect(allows([role], key, "read")).toBe(RANK[expected] >= 1);
    expect(allows([role], key)).toBe(RANK[expected] >= 1);
    expect(allows([role], key, "full")).toBe(expected === "full");
  });

  it("модуль раздела — первый сегмент ключа", () => {
    for (const key of KEYS) expect(RESOURCES[key].module).toBe(key.split(".")[0]);
  });

  it("у нескольких ролей берётся максимум (все пары и все шесть)", () => {
    for (const key of KEYS) {
      for (const [i, a] of ORACLE_ROLES.entries()) {
        for (const b of ORACLE_ROLES.slice(i + 1)) {
          expect(levelFor([a, b], key)).toBe(oracleUnion([a, b], key));
          expect(levelFor([b, a], key)).toBe(oracleUnion([a, b], key));
        }
      }
      expect(levelFor(ORACLE_ROLES, key)).toBe(oracleUnion(ORACLE_ROLES, key));
      expect(levelFor([], key)).toBe("hidden");
    }
  });
});

describe("rbac.generated: модули и меню", () => {
  it.each(ORACLE_ROLES)("%s: модули — те, где виден хотя бы один раздел", (role) => {
    const expected = MODULES.filter((m) =>
      KEYS.some((key) => key.split(".")[0] === m && oracleLevel(role, key) !== "hidden"),
    );

    expect(visibleModules([role])).toEqual(expected);
    expect(visibleModules([role])).toContain("dashboard");
  });

  it.each(ORACLE_ROLES)("%s: пункт меню виден, если виден хотя бы один из разделов", (role) => {
    for (const module of MODULES) {
      const items = MENU[module] as Record<string, readonly ResourceKey[]>;
      for (const [item, sections] of Object.entries(items)) {
        const expected = sections.some((key) => oracleLevel(role, key) !== "hidden");
        expect(menuItemVisible([role], module, item)).toBe(expected);
      }
      expect(visibleMenuItems([role], module)).toEqual(
        Object.keys(items).filter((item) => menuItemVisible([role], module, item)),
      );
    }
    // Модуль виден тогда и только тогда, когда виден хотя бы один его пункт.
    expect(MODULES.filter((m) => visibleMenuItems([role], m).length > 0)).toEqual(
      visibleModules([role]),
    );
  });

  it("каждый раздел матрицы входит хотя бы в один пункт меню", () => {
    const covered = new Set<string>();
    for (const module of MODULES) {
      for (const sections of Object.values(MENU[module] as Record<string, readonly string[]>)) {
        for (const key of sections) covered.add(key);
      }
    }
    expect([...covered].sort()).toEqual([...KEYS].sort());
  });

  it("примеры SPEC-v3: смешанные реестры и read", () => {
    expect(visibleMenuItems(["ADMIN"], "dashboard")).toEqual(["queue"]);
    expect(visibleMenuItems(["SUPPLY"], "chats")).toEqual(["all", "internal", "contacts"]);
    expect(menuItemVisible(["ACCOUNTANT"], "dashboard", "summary")).toBe(true);
    expect(menuItemVisible(["MANAGER", "SUPPLY"], "dashboard", "summary")).toBe(false);
    expect(menuItemVisible(["MANAGER"], "dashboard", "no-such-item")).toBe(false);
  });
});

describe("rbac.generated: поля с ограничением", () => {
  const ORACLE_FIELDS: Record<string, readonly RoleCode[]> = {
    cost_margin: ["DIRECTOR", "SUPPLY"],
    totals_only: ["ACCOUNTANT"],
    supplier_prices: ["DIRECTOR", "SUPPLY", "ACCOUNTANT"],
  };

  it("группы и роли совпадают с эталоном", () => {
    expect(RESTRICTED_FIELDS).toEqual(ORACLE_FIELDS);
  });

  it.each(ORACLE_ROLES)("%s: видимые группы", (role) => {
    const expected = Object.entries(ORACLE_FIELDS)
      .filter(([, roles]) => roles.includes(role))
      .map(([name]) => name);

    expect(visibleRestrictedFields([role])).toEqual(expected);
  });

  it("объединение ролей раскрывает поле", () => {
    expect(visibleRestrictedFields(["DIRECTOR", "ACCOUNTANT"])).toEqual([
      "cost_margin",
      "totals_only",
      "supplier_prices",
    ]);
    expect(visibleRestrictedFields(["MANAGER", "ENGINEER", "ADMIN"])).toEqual([]);
  });
});
