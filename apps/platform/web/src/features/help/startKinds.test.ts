import { describe, expect, it } from "vitest";

import type { Me } from "../../shared/api/generated/model";
import { startKindsOf } from "./startKinds";

const me = (resources: Record<string, "read" | "full">) => ({ resources }) as unknown as Me;

describe("startKindsOf", () => {
  it("по разделам каталога, а не по названию роли", () => {
    expect(startKindsOf(me({ "eds.payments": "full", "dashboard.queue": "full" }))).toEqual([
      "accountant",
    ]);
    expect(startKindsOf(me({ "eds.inbox": "full", "eds.memo.approve": "full" }))).toEqual([
      "director",
    ]);
    expect(startKindsOf(me({ "crm.leads": "full", "crm.clients": "full" }))).toEqual(["manager"]);
    expect(startKindsOf(me({ "erp.calc.goods": "full" }))).toEqual(["supply"]);
    expect(startKindsOf(me({ "erp.calc.services": "full" }))).toEqual(["engineer"]);
  });

  it("чтение не делает сотрудника исполнителем; администратор — первым", () => {
    expect(startKindsOf(me({ "eds.inbox": "read", admin: "read" }))).toEqual(["default"]);
    expect(startKindsOf(me({ "crm.leads": "full", admin: "full" }))).toEqual(["admin", "manager"]);
  });

  it("ничего подходящего — «любая роль»", () => {
    expect(startKindsOf(me({ "dashboard.queue": "full" }))).toEqual(["default"]);
  });
});
