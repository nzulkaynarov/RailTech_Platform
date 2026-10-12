import { describe, expect, it } from "vitest";

import { formatMoney, stageFromSearch, stageLabel } from "./deals";

describe("deals", () => {
  it.each([
    ["1250000", "UZS", "1 250 000 UZS"],
    ["99.50", "USD", "99,5 USD"],
    [0, "UZS", "0 UZS"],
    [null, "UZS", "—"],
    ["abc", "UZS", "—"],
  ])("formatMoney(%s, %s)", (amount, currency, expected) => {
    expect(formatMoney(amount, currency)).toBe(expected);
  });

  it("stage helpers", () => {
    expect(stageLabel("won")).toBe("Выиграна");
    expect(stageFromSearch("lost")).toBe("lost");
    expect(stageFromSearch("bogus")).toBeUndefined();
    expect(stageFromSearch(null)).toBeUndefined();
  });
});
