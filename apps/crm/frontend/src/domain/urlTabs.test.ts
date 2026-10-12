import { describe, expect, it } from "vitest";

import { resolveTab } from "./urlTabs";

const TABS = ["contacts", "deals", "leads"] as const;

describe("resolveTab", () => {
  it.each([
    ["deals", "deals"],
    ["leads", "leads"],
    [null, "contacts"],
    ["", "contacts"],
    ["documents", "contacts"],
  ])("%s → %s", (requested, expected) => {
    expect(resolveTab(requested, TABS)).toBe(expected);
  });

  it("hidden tab (no permission) falls back to the first available", () => {
    expect(resolveTab("deals", ["contacts", "leads"])).toBe("contacts");
  });

  it("no tabs is a programming error", () => {
    expect(() => resolveTab("x", [])).toThrow();
  });
});
