import { describe, expect, it } from "vitest";

import { decimalInputProps } from "./numberInput";

const typed = { userTyping: false, input: "" };

describe("decimalInputProps", () => {
  it("ru: запятая, без хвостового нуля", () => {
    const p = decimalInputProps("ru");
    expect(p.decimalSeparator).toBe(",");
    expect(p.formatter("18.00", typed)).toBe("18");
    expect(p.formatter("18.50", typed)).toBe("18,5");
    expect(p.formatter("5.0", typed)).toBe("5");
  });
  it("en: точка", () => {
    const p = decimalInputProps("en");
    expect(p.decimalSeparator).toBe(".");
    expect(p.formatter("18.50", typed)).toBe("18.5");
  });
  it("пока печатают — текст как есть; разбор возвращает точку", () => {
    const p = decimalInputProps("ru");
    expect(p.formatter("18", { userTyping: true, input: "18," })).toBe("18,");
    expect(p.parser("18,5")).toBe("18.5");
  });
});
