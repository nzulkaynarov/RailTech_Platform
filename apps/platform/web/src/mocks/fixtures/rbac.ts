import type { AccessLevel, ModuleCode, RoleCode } from "../../shared/api/generated/model";

/**
 * Ролевая матрица для MSW-фикстур: SPEC-v3 §4.2, ключи и уровни — `packages/contracts/platform-rbac.yaml`.
 * Только для моков (`pnpm dev:mock`, e2e, тесты): боевой код берёт модули и разделы из `Me`. Совпадение с YAML
 * проверяет `rbac.test.ts`; сгенерированную матрицу для SPA делает PLT-10/11 (`rbac.generated.ts`).
 */
export const ROLES: readonly RoleCode[] = [
  "MANAGER",
  "DIRECTOR",
  "SUPPLY",
  "ENGINEER",
  "ACCOUNTANT",
  "ADMIN",
];

export const MODULE_ORDER: readonly ModuleCode[] = [
  "dashboard",
  "crm",
  "eds",
  "erp",
  "chats",
  "admin",
];

type Cell = AccessLevel | "hidden";
/** Колонки: MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT, ADMIN */
type Row = readonly [Cell, Cell, Cell, Cell, Cell, Cell];

const F = "full";
const R = "read";
const H = "hidden";

export const MATRIX: Record<string, { module: ModuleCode; access: Row }> = {
  "dashboard.queue": { module: "dashboard", access: [F, F, F, F, F, F] },
  "dashboard.summary": { module: "dashboard", access: [H, F, H, H, R, H] },
  "crm.leads": { module: "crm", access: [F, R, H, H, H, H] },
  "crm.clients": { module: "crm", access: [F, R, R, R, R, H] },
  "eds.inbox": { module: "eds", access: [R, F, H, H, R, H] },
  "eds.drafts": { module: "eds", access: [R, F, H, H, H, H] },
  "eds.projects": { module: "eds", access: [R, F, R, R, F, H] },
  "eds.payments": { module: "eds", access: [R, R, H, H, F, H] },
  "eds.memo.create": { module: "eds", access: [F, F, F, F, F, F] },
  "eds.memo.approve": { module: "eds", access: [H, F, H, H, H, H] },
  "erp.calc": { module: "erp", access: [H, F, F, F, R, H] },
  "erp.stock": { module: "erp", access: [R, F, F, F, R, H] },
  "chats.internal": { module: "chats", access: [F, F, F, F, F, F] },
  "chats.external": { module: "chats", access: [F, R, H, H, F, H] },
  admin: { module: "admin", access: [H, R, H, H, H, F] },
};

export const RESTRICTED_FIELDS: Record<string, readonly RoleCode[]> = {
  cost_margin: ["DIRECTOR", "SUPPLY"],
  totals_only: ["ACCOUNTANT"],
  supplier_prices: ["DIRECTOR", "SUPPLY", "ACCOUNTANT"],
};

/** Роли с доступом в ERP (`erp_role_codes` не пуст в YAML): у ADMIN его нет. */
const ERP_ROLES: ReadonlySet<RoleCode> = new Set([
  "MANAGER",
  "DIRECTOR",
  "SUPPLY",
  "ENGINEER",
  "ACCOUNTANT",
]);

export interface ComputedAccess {
  modules: ModuleCode[];
  resources: Record<string, AccessLevel>;
  restricted_fields: string[];
  access: { crm: boolean; erp: boolean };
}

/** Объединение ролей: берётся максимум full > read > hidden (platform-rbac.yaml). */
export function computeAccess(roles: readonly RoleCode[]): ComputedAccess {
  const resources: Record<string, AccessLevel> = {};
  for (const [key, row] of Object.entries(MATRIX)) {
    let best: AccessLevel | undefined;
    for (const role of roles) {
      const cell = row.access[ROLES.indexOf(role)];
      if (cell === "full") best = "full";
      else if (cell === "read" && best !== "full") best = "read";
    }
    if (best) resources[key] = best;
  }
  const modules = MODULE_ORDER.filter((module) =>
    Object.entries(MATRIX).some(([key, row]) => row.module === module && key in resources),
  );
  const restricted_fields = Object.entries(RESTRICTED_FIELDS)
    .filter(([, visible]) => roles.some((role) => visible.includes(role)))
    .map(([name]) => name);
  return {
    modules,
    resources,
    restricted_fields,
    access: { crm: true, erp: roles.some((role) => ERP_ROLES.has(role)) },
  };
}
