import { describe, expect, it } from "vitest";

import {
  currencyOptions,
  formatMoney,
  groupThousands,
  isErpMirror,
  parseAmount,
  stageFromSearch,
  stageLabel,
} from "./deals";

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

describe("deal form helpers", () => {
  it.each([
    [1500000, "1 500 000"],
    ["999", "999"],
    [undefined, ""],
  ] as const)("groupThousands(%s) = %s", (value, expected) => {
    expect(groupThousands(value)).toBe(expected);
  });

  it.each([
    ["1 500 000", 1500000],
    ["", 0],
  ] as const)("parseAmount(%s) = %s", (text, expected) => {
    expect(parseAmount(text)).toBe(expected);
  });

  it("currency options start from the settings currency without duplicates", () => {
    expect(currencyOptions("USD")).toEqual(["USD", "UZS"]);
    expect(currencyOptions("EUR")).toEqual(["EUR", "UZS", "USD"]);
  });

  it("isErpMirror: зеркало заявки ERP — по erp_deal_id", () => {
    expect(isErpMirror({ erp_deal_id: 22 })).toBe(true);
    expect(isErpMirror({ erp_deal_id: null })).toBe(false);
    expect(isErpMirror({})).toBe(false);
  });
});
