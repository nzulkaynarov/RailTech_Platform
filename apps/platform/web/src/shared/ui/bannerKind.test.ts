import { describe, expect, it } from "vitest";

import { bannerKind } from "./bannerKind";

describe("плашка частичных данных: какой текст", () => {
  it("один источник — его ключ; CRM и ERP — both; сочетания с EDS — multi", () => {
    expect(bannerKind(true, false, false)).toBe("crm");
    expect(bannerKind(false, true, false)).toBe("erp");
    expect(bannerKind(false, false, true)).toBe("eds");
    expect(bannerKind(true, true, false)).toBe("both");
    expect(bannerKind(true, false, true)).toBe("multi");
    expect(bannerKind(false, true, true)).toBe("multi");
    expect(bannerKind(true, true, true)).toBe("multi");
  });
});
