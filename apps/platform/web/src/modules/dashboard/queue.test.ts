import { describe, expect, it } from "vitest";

import type { Me } from "../../shared/api/generated/model";
import { isUrgent, queueEmptyKind } from "./queue";

const me = (resources: Record<string, "read" | "full">): Me =>
  ({ resources, modules: [], roles: [] }) as unknown as Me;

describe("queueEmptyKind: пустое состояние — по разделам каталога, не по кодам ролей", () => {
  it.each([
    ["письма и резолюции", { "eds.inbox": "full" }, "director"],
    ["одобрение КП", { "eds.drafts": "full", "eds.payments": "full" }, "director"],
    ["согласование служебок", { "eds.memo.approve": "full" }, "director"],
    ["платёжки", { "eds.payments": "full", "erp.calc": "read" }, "accountant"],
    ["виза товаров и склада", { "erp.calc.goods": "full", "erp.stock": "full" }, "supply"],
    ["виза услуг", { "erp.calc.services": "full", "erp.stock": "full" }, "engineer"],
    ["лиды", { "crm.leads": "full", "eds.inbox": "read" }, "manager"],
    ["настройки", { admin: "full" }, "admin"],
    ["только чтение", { "crm.leads": "read", "eds.payments": "read" }, "default"],
    ["ничего", {}, "default"],
  ] as const)("%s → %s", (_name, resources, expected) => {
    expect(queueEmptyKind(me({ ...resources }))).toBe(expected);
  });
});

describe("isUrgent: primary у «сегодня» и «просрочено»", () => {
  it.each([
    ["overdue", true],
    ["today", true],
    ["tomorrow", false],
    ["later", false],
    ["memo", false],
  ] as const)("%s → %s", (label, expected) => {
    expect(isUrgent({ due_label: label })).toBe(expected);
  });
});
