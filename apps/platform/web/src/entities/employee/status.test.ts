import { describe, expect, it } from "vitest";

import type { Employee } from "../../shared/api/generated/model";
import { anyErpPending, erpAttention, erpSyncReason } from "./status";

const base = {
  access: { crm: true, erp: true },
  status: "active",
  erp_sync: "ok",
} as Pick<Employee, "access" | "erp_sync" | "status">;

describe("erpAttention", () => {
  it("«выдаётся» и «ошибка» — словом, «ок» — без метки", () => {
    expect(erpAttention({ ...base, erp_sync: "pending" })).toBe("pending");
    expect(erpAttention({ ...base, erp_sync: "error" })).toBe("error");
    expect(erpAttention(base)).toBeNull();
  });

  it("у отключённого про выдачу доступа в ERP — ничего, даже если очередь с отзывом не пуста", () => {
    expect(erpAttention({ ...base, status: "disabled", erp_sync: "pending" })).toBeNull();
  });

  it("без доступа к ERP — ничего", () => {
    expect(
      erpAttention({ ...base, access: { crm: true, erp: false }, erp_sync: "pending" }),
    ).toBeNull();
  });
});

describe("anyErpPending", () => {
  const row = (erp_sync: Employee["erp_sync"], status: Employee["status"] = "active") =>
    ({ ...base, erp_sync, status }) as Employee;

  it("опрос нужен, пока у кого-то активного доступ выдаётся", () => {
    expect(anyErpPending([row("ok"), row("pending")])).toBe(true);
    expect(anyErpPending([row("ok"), row("error")])).toBe(false);
    expect(anyErpPending([row("pending", "disabled")])).toBe(false);
    expect(anyErpPending(undefined)).toBe(false);
  });
});

describe("erpSyncReason", () => {
  it("код причины CRM решает фразу, сам текст ошибки не показывается", () => {
    expect(erpSyncReason("erp_provision_user: erp_not_configured: ERP не подключена")).toBe(
      "not_configured",
    );
    expect(erpSyncReason("erp_provision_user: ConnectError: All connection attempts failed")).toBe(
      "unavailable",
    );
    expect(erpSyncReason("erp_provision_user: ReadTimeout: ")).toBe("unavailable");
    expect(erpSyncReason("erp_provision_user: erp_rejected: email занят")).toBe("rejected");
  });

  it("без текста ошибки причины нет", () => {
    expect(erpSyncReason(undefined)).toBeNull();
    expect(erpSyncReason("")).toBeNull();
  });
});
