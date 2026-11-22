import { describe, expect, it } from "vitest";

import { formatQuantity } from "../../../shared/lib/money";
import { priceRequestLinesText } from "./priceRequestText";

describe("строки запроса цены", () => {
  it("количество — с разрядами и единицей строки", () => {
    const lines = [
      { line_id: "1", name: "Рельс Р65", article: "R65", quantity: 20000, unit: "т" },
      { line_id: "2", name: "Накладка", article: "N", quantity: 5, unit: "" },
    ];
    const text = priceRequestLinesText(lines, (v) => formatQuantity(v, { language: "ru" }));
    expect(text).toBe("Рельс Р65 · 20 000 т; Накладка · 5");
  });
});
