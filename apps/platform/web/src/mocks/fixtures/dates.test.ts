import { describe, expect, it } from "vitest";

import { companyDayIn } from "./dates";

describe("даты фикстур от «сегодня компании»", () => {
  it("сегодня считается по Ташкенту (UTC+5), а не по UTC", () => {
    expect(companyDayIn(0, new Date("2026-10-31T20:00:00Z"))).toBe("2026-11-01");
    expect(companyDayIn(0, new Date("2026-10-31T18:59:00Z"))).toBe("2026-10-31");
  });

  it("сдвиг переходит через границу месяца и года", () => {
    expect(companyDayIn(7, new Date("2026-10-28T09:00:00Z"))).toBe("2026-11-04");
    expect(companyDayIn(7, new Date("2026-12-28T09:00:00Z"))).toBe("2027-01-04");
  });
});
