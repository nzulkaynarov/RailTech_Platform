import { describe, expect, it } from "vitest";

import { fromCents, normalizeAmount, remainderAfter, showTab, toCents } from "./model";

describe("сумма из поля ввода", () => {
  it.each([
    ["112000000.00", "112000000.00"],
    ["112 000 000", "112000000.00"],
    ["1 500,5", "1500.50"],
    ["0,01", "0.01"],
    ["007.10", "7.10"],
  ])("%s -> %s", (input, expected) => {
    expect(normalizeAmount(input)).toBe(expected);
  });

  it.each(["", "0", "0.00", "-5", "12.345", "abc", "1,2,3", "1e5"])("«%s» — не сумма", (input) => {
    expect(normalizeAmount(input)).toBeNull();
  });
});

describe("деньги без плавающей точки", () => {
  it("копейки туда и обратно, остаток после частичной оплаты", () => {
    expect(toCents("112000000.00")).toBe(11_200_000_000n);
    expect(fromCents(7_200_000_000n)).toBe("72000000.00");
    expect(fromCents(5n)).toBe("0.05");
    expect(
      remainderAfter({ balance: { amount: "112000000.00", currency: "UZS" } }, "40000000.00"),
    ).toBe("72000000.00");
    expect(remainderAfter({ balance: { amount: "0.10", currency: "UZS" } }, "0.07")).toBe("0.03");
  });
});

describe("вкладка из адреса", () => {
  it("известная — как есть, любая другая — «Ждут оплаты»", () => {
    expect(showTab("proofs")).toBe("proofs");
    expect(showTab("memos")).toBe("memos");
    expect(showTab("paid")).toBe("awaiting");
    expect(showTab(null)).toBe("awaiting");
  });
});
