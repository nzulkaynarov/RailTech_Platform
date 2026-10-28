import { describe, expect, it } from "vitest";

import { todayLabel } from "./format";

describe("todayLabel", () => {
  const moment = new Date("2026-10-22T10:00:00Z");

  it("«четверг, 22 октября 2026» по-русски, без «г.»", () => {
    expect(todayLabel("ru", moment)).toBe("четверг, 22 октября 2026");
  });

  it("берёт часовой пояс компании: 23:30 UTC — уже следующий день в Ташкенте", () => {
    expect(todayLabel("ru", new Date("2026-10-22T23:30:00Z"))).toBe("пятница, 23 октября 2026");
  });

  it("uz — латиница без «M10» и английских дней, день считается в поясе компании", () => {
    expect(todayLabel("uz", new Date("2026-10-28T10:00:00Z"))).toBe("28-oktabr 2026, chorshanba");
    expect(todayLabel("uz", new Date("2026-12-31T20:00:00Z"))).toBe("1-yanvar 2027, juma");
  });

  it("поддерживает en и uz", () => {
    expect(todayLabel("en", moment)).toContain("22 October 2026");
    expect(todayLabel("uz", moment)).toBe("22-oktabr 2026, payshanba");
  });
});
