import { describe, expect, it } from "vitest";

import { PERMISSION_SECTIONS, RESOURCES } from "../../app/rbac.generated";
import { ApiError } from "../api/errors";
import { missingSectionName } from "./permissionSection";

const forbidden = (details: Record<string, unknown>, status = 403) =>
  new ApiError(status, "FORBIDDEN", "Действие не положено вашей роли.", "eds", details);

describe("missingSectionName", () => {
  it("право из отказа 403 называется разделом словами, на языке сотрудника", () => {
    const error = forbidden({ permission: "letters.resolve" });
    expect(missingSectionName(error, "ru")).toBe("Документы · Входящие · резолюция");
    expect(missingSectionName(error, "en")).toBe("Documents · Incoming · resolution");
    expect(missingSectionName(error, "uz")).toBe("Hujjatlar · Kiruvçi · rezolyutsiya");
  });

  it("нет кода, неизвестный код или не 403 — раздела нет, код не показывается", () => {
    expect(missingSectionName(forbidden({}))).toBeNull();
    expect(missingSectionName(forbidden({ permission: "unknown.permission" }))).toBeNull();
    expect(missingSectionName(forbidden({ permission: "letters.resolve" }, 409))).toBeNull();
    expect(missingSectionName(new Error("x"))).toBeNull();
  });

  it("каждое право каталога указывает на существующий раздел", () => {
    for (const key of Object.values(PERMISSION_SECTIONS)) expect(RESOURCES).toHaveProperty(key);
  });
});
