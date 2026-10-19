import { describe, expect, it } from "vitest";

import { canSwitchToErp, hasErpAccess, withErpAccess } from "./platformAccess";

describe("platform access (FIX-11)", () => {
  it.each([
    [{ platform_access: ["crm", "erp"] }, true],
    [{ platform_access: ["crm"] }, false],
    [{ platform_access: [] }, false],
    [{}, false],
    [null, false],
    [undefined, false],
  ])("hasErpAccess(%j) → %s", (user, expected) => {
    expect(hasErpAccess(user)).toBe(expected);
  });

  // Матрица «без доступа переключателя нет»: нужны оба — SSO включён и доступ выдан.
  it.each([
    { sso_enabled: true, platform_access: ["crm", "erp"], shown: true },
    { sso_enabled: true, platform_access: ["crm"], shown: false },
    { sso_enabled: false, platform_access: ["crm", "erp"], shown: false },
    { sso_enabled: false, platform_access: ["crm"], shown: false },
    { sso_enabled: true, platform_access: undefined, shown: false },
    { sso_enabled: undefined, platform_access: ["crm", "erp"], shown: false },
  ])("canSwitchToErp(%j)", ({ shown, ...identity }) => {
    expect(canSwitchToErp(identity)).toBe(shown);
  });

  it("canSwitchToErp tolerates a missing identity", () => {
    expect(canSwitchToErp(null)).toBe(false);
    expect(canSwitchToErp(undefined)).toBe(false);
  });

  it("withErpAccess always keeps CRM", () => {
    expect(withErpAccess(true)).toEqual(["crm", "erp"]);
    expect(withErpAccess(false)).toEqual(["crm"]);
  });
});
