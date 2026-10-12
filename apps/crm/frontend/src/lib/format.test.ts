import { describe, expect, it } from "vitest";

import { formatDuration, formatNumber, formatUsd } from "./format";

const plain = (s: string) => s.replace(/ /g, " ");

describe("ru-RU formatting", () => {
  it.each([
    [0, "0"],
    [1073, "1 073"],
    [1200000, "1 200 000"],
  ])("number %s → %s", (value, expected) => {
    expect(plain(formatNumber(value))).toBe(expected);
  });

  it("keeps a comma for fractions", () => {
    expect(plain(formatNumber(1073.25, 1))).toBe("1 073,3");
  });

  it.each([
    [0.13, "$0,13"],
    [1204.5, "$1 204,50"],
  ])("usd %s → %s", (value, expected) => {
    expect(plain(formatUsd(value))).toBe(expected);
  });

  it.each([
    [null, "—"],
    [0, "0 мин"],
    [45.4, "45 мин"],
    [60, "1 ч"],
    [1073.3, "17 ч 53 мин"],
    [1440, "1 дн"],
    [3060, "2 дн 3 ч"],
  ])("duration %s → %s", (value, expected) => {
    expect(plain(formatDuration(value))).toBe(expected);
  });
});
