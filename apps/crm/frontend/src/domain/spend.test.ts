import { describe, expect, it } from "vitest";

import { barStatus, hasTestSpend, limitPercent, purposeLabel, roleLabel, usd } from "./spend";

describe("spend helpers", () => {
  it("detects test spend", () => {
    expect(hasTestSpend({ by_kind: [{ key: "work", cost_usd: 1 }] })).toBe(false);
    expect(hasTestSpend({ by_kind: [{ key: "test", cost_usd: 0 }] })).toBe(false);
    expect(hasTestSpend({ by_kind: [{ key: "test", cost_usd: 0.2 }] })).toBe(true);
  });

  it.each([
    [0, "$0.00"],
    [0.0042, "< $0.01"],
    [1.5, "$1.50"],
    [12.345, "$12.35"],
  ])("formats %s as %s", (value, expected) => {
    expect(usd(value)).toBe(expected);
  });

  it.each([
    [1, 0, null],
    [1.5, 3, 50],
    [3, 3, 100],
    [9, 3, 100],
  ])("percent of %s / %s = %s", (spent, limit, expected) => {
    expect(limitPercent(spent, limit)).toBe(expected);
  });

  it.each([
    [null, "normal"],
    [50, "normal"],
    [81, "active"],
    [100, "exception"],
  ] as const)("bar status for %s is %s", (percent, expected) => {
    expect(barStatus(percent)).toBe(expected);
  });

  it("translates purposes and roles, keeps unknown keys", () => {
    expect(purposeLabel("embed_query")).toBe("Поиск по базе знаний");
    expect(roleLabel("dialog-model")).toBe("Диалог");
    expect(roleLabel("custom")).toBe("custom");
  });
});
