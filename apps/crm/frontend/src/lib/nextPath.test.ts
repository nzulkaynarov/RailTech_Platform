import { describe, expect, it } from "vitest";

import { safeNextPath, withNext } from "./nextPath";

describe("safeNextPath", () => {
  it.each([
    ["/leads/12", "/leads/12"],
    ["/clients?tab=documents", "/clients?tab=documents"],
    ["/integrations?tab=erp#x", "/integrations?tab=erp#x"],
  ])("keeps an in-app path %s", (raw, expected) => {
    expect(safeNextPath(raw)).toBe(expected);
  });

  it.each([
    null,
    undefined,
    "",
    "/",
    "leads",
    "//evil.example/leads",
    "https://evil.example",
    "/\\evil.example",
    "/leads\nSet-Cookie: x",
    "/login",
    "/login?to=%2Fleads",
    "/setup",
    "/change-password",
    "/sso/exchange",
  ])("rejects %j", (raw) => {
    expect(safeNextPath(raw)).toBeNull();
  });
});

describe("withNext", () => {
  it("leaves the target alone without a saved address", () => {
    expect(withNext("/", null)).toBe("/");
    expect(withNext("/change-password", null)).toBe("/change-password");
  });

  it("replaces the root with the saved address", () => {
    expect(withNext("/", "/leads/12?x=1")).toBe("/leads/12?x=1");
  });

  it("carries the saved address through the password change step", () => {
    expect(withNext("/change-password", "/leads/12")).toBe("/change-password?to=%2Fleads%2F12");
  });
});
