import { describe, expect, it } from "vitest";

import { companyDayKey, companyToday, formatActivityTime, formatDate } from "./dates";

describe("formatDate (часовой пояс компании — Asia/Tashkent, UTC+5)", () => {
  const moment = new Date("2026-10-24T06:50:00Z"); // 11:50 в Ташкенте

  it("стили", () => {
    expect(formatDate(moment)).toBe("24.10.2026");
    expect(formatDate(moment, { style: "short" })).toBe("24.10");
    expect(formatDate(moment, { style: "time" })).toBe("11:50");
    expect(formatDate(moment, { style: "datetime" })).toBe("24.10.2026 11:50");
    expect(formatDate(moment, { style: "long" })).toBe("24 октября 2026");
    expect(formatDate(moment, { style: "long", language: "en" })).toContain("24 October 2026");
  });

  it("поздний вечер UTC — уже следующий день у компании", () => {
    const late = "2026-10-24T20:30:00Z";
    expect(formatDate(late)).toBe("25.10.2026");
    expect(formatDate(late, { style: "time" })).toBe("01:30");
  });

  it("принимает строку ISO и метку времени", () => {
    expect(formatDate("2026-10-24T06:50:00+00:00", { style: "time" })).toBe("11:50");
    expect(formatDate(moment.getTime(), { style: "time" })).toBe("11:50");
  });

  it("дата без времени не сдвигается поясом", () => {
    expect(formatDate("2026-10-24")).toBe("24.10.2026");
    expect(formatDate("2026-10-24", { style: "short" })).toBe("24.10");
    expect(formatDate("2026-10-24", { style: "long" })).toBe("24 октября 2026");
    expect(formatDate("2026-10-24", { style: "time" })).toBe("—");
  });

  it("пустое и неверное — «—»", () => {
    for (const value of [null, undefined, "", "не дата", new Date("x")]) {
      expect(formatDate(value)).toBe("—");
    }
  });
});

describe("formatActivityTime", () => {
  const now = new Date("2026-10-25T05:00:00Z"); // 25.10, 10:00 в Ташкенте

  it("сегодня — время, вчера — со словом, раньше — день и месяц, в прошлом году — с годом", () => {
    expect(formatActivityTime("2026-10-25T01:00:00Z", { now })).toBe("06:00");
    expect(formatActivityTime("2026-10-24T04:24:00Z", { now })).toBe("вчера 09:24");
    expect(formatActivityTime("2026-10-24T04:24:00Z", { now, language: "en" })).toBe(
      "yesterday 09:24",
    );
    expect(formatActivityTime("2026-10-20T06:50:00Z", { now })).toBe("20.10 11:50");
    expect(formatActivityTime("2025-12-31T06:50:00Z", { now })).toBe("31.12.2025 11:50");
  });

  it("«вчера» считается по календарю компании, а не по 24 часам", () => {
    // 00:30 25.10 у компании (19:30 UTC 24.10) — сегодня; 23:30 24.10 (18:30 UTC) — вчера
    expect(formatActivityTime("2026-10-24T19:30:00Z", { now })).toBe("00:30");
    expect(formatActivityTime("2026-10-24T18:30:00Z", { now })).toBe("вчера 23:30");
  });

  it("companyDayKey", () => {
    expect(companyDayKey("2026-10-24T20:30:00Z")).toBe("2026-10-25");
    expect(companyDayKey(null)).toBeNull();
  });

  it("companyToday — сегодня по Ташкенту, а не по браузеру", () => {
    expect(companyToday(new Date("2026-10-27T23:30:00Z"))).toBe("2026-10-28");
    expect(companyToday(new Date("2026-10-27T10:00:00Z"))).toBe("2026-10-27");
  });
});
