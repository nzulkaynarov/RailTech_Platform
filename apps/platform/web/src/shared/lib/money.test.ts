import { describe, expect, it } from "vitest";

import { MINUS, NBSP, formatMoney, formatNumber, formatPercent } from "./money";

describe("formatMoney", () => {
  it("«1 234 567 сум» с неразрывными пробелами", () => {
    expect(formatMoney(1234567)).toBe(`1${NBSP}234${NBSP}567${NBSP}сум`);
    expect(formatMoney(1234567)).not.toContain(" ");
  });

  it("строка от BFF не теряет точность и не показывает нулевых копеек", () => {
    expect(formatMoney("134400000.00")).toBe(`134${NBSP}400${NBSP}000${NBSP}сум`);
    expect(formatMoney("9007199254740993.00")).toBe(
      `9${NBSP}007${NBSP}199${NBSP}254${NBSP}740${NBSP}993${NBSP}сум`,
    );
  });

  it("копейки — до сотых, половина вверх", () => {
    expect(formatMoney("1200.5")).toBe(`1${NBSP}200,50${NBSP}сум`);
    expect(formatMoney("0.005")).toBe(`0,01${NBSP}сум`);
    expect(formatMoney("1.994")).toBe(`1,99${NBSP}сум`);
    expect(formatMoney("999.999")).toBe(`1${NBSP}000${NBSP}сум`);
  });

  it("ровное число знаков по запросу", () => {
    expect(formatMoney(5, { fractionDigits: 2 })).toBe(`5,00${NBSP}сум`);
    expect(formatMoney("12.345", { fractionDigits: 0 })).toBe(`12${NBSP}сум`);
  });

  it("отрицательная сумма — настоящий минус, «−0» не бывает", () => {
    expect(formatMoney(-450000)).toBe(`${MINUS}450${NBSP}000${NBSP}сум`);
    expect(formatMoney("-0.001")).toBe(`0${NBSP}сум`);
  });

  it("без валюты, со своей валютой и по языкам", () => {
    expect(formatMoney(61000000, { currency: false })).toBe(`61${NBSP}000${NBSP}000`);
    expect(formatMoney(100, { currency: "USD" })).toBe(`100${NBSP}USD`);
    expect(formatMoney(1234, { language: "uz" })).toBe(`1${NBSP}234${NBSP}so‘m`);
    expect(formatMoney(1234.5, { language: "en" })).toBe(`1,234.50${NBSP}UZS`);
    expect(formatMoney(1234, { language: "ru-RU" })).toBe(`1${NBSP}234${NBSP}сум`);
  });

  it("пустое и нечисловое — «—», а не «NaN сум»", () => {
    for (const value of [null, undefined, "", "abc", Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatMoney(value)).toBe("—");
    }
  });
});

describe("formatNumber и formatPercent", () => {
  it("тысячи группируются, малые числа не меняются", () => {
    expect(formatNumber(7)).toBe("7");
    expect(formatNumber(1204)).toBe(`1${NBSP}204`);
    expect(formatNumber(1000000)).toBe(`1${NBSP}000${NBSP}000`);
  });

  it("процент: «30,0 %» с неразрывным пробелом", () => {
    expect(formatPercent(30)).toBe(`30,0${NBSP}%`);
    expect(formatPercent("23.44")).toBe(`23,4${NBSP}%`);
    expect(formatPercent(22, { fractionDigits: 0, language: "en" })).toBe(`22${NBSP}%`);
    expect(formatPercent(null)).toBe("—");
  });
});
