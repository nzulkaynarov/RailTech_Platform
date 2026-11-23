import { describe, expect, it } from "vitest";

import {
  DISMISS_MS,
  WARN_BEFORE_MS,
  companyTime,
  maintenanceView,
  parseNotice,
} from "./maintenance";

const STARTS = Date.parse("2026-11-23T19:15:00+05:00");
const MIN = 60_000;
const notice = (extra: Record<string, unknown> = {}) =>
  parseNotice({ starts_at: "2026-11-23T19:15:00+05:00", minutes: 3, kind: "planned", ...extra });

describe("parseNotice", () => {
  it("читает полный файл", () => {
    expect(notice()).toEqual({ startsAt: STARTS, minutes: 3, kind: "planned" });
  });
  it("minutes по умолчанию 3, kind по умолчанию planned, urgent узнаётся", () => {
    expect(parseNotice({ starts_at: "2026-11-23T14:15:00Z" })).toEqual({
      startsAt: STARTS,
      minutes: 3,
      kind: "planned",
    });
    expect(notice({ kind: "urgent", minutes: 5 })).toMatchObject({ kind: "urgent", minutes: 5 });
    expect(notice({ minutes: "много" })?.minutes).toBe(3);
  });
  it.each([
    ["пустой объект", {}],
    ["null", null],
    ["строка", "19:15"],
    ["нет starts_at", { minutes: 3 }],
    ["время без пояса", { starts_at: "2026-11-23T19:15:00" }],
    ["не дата", { starts_at: "завтра" }],
    ["несуществующая дата", { starts_at: "2026-13-45T25:61:00+05:00" }],
    ["число вместо строки", { starts_at: 1795000000 }],
  ])("%s — баннера нет", (_name, raw) => {
    expect(parseNotice(raw)).toBeNull();
  });
});

describe("maintenanceView", () => {
  const n = notice();
  it("нет предупреждения — нет баннера", () => {
    expect(maintenanceView(null, STARTS)).toBeNull();
  });
  it("до окна — нет", () => {
    expect(maintenanceView(n, STARTS - WARN_BEFORE_MS - 1)).toBeNull();
  });
  it("ровно за 30 минут — «soon» с временем по Ташкенту и «2–3»", () => {
    expect(maintenanceView(n, STARTS - WARN_BEFORE_MS)).toMatchObject({
      phase: "soon",
      time: "19:15",
      from: 2,
      to: 3,
      kind: "planned",
      dismissible: true,
    });
  });
  it("внутри работ — «running», без кнопки скрытия", () => {
    expect(maintenanceView(n, STARTS)).toMatchObject({ phase: "running", dismissible: false });
    expect(maintenanceView(n, STARTS + 3 * MIN - 1)).toMatchObject({ phase: "running" });
  });
  it("после окна — нет", () => {
    expect(maintenanceView(n, STARTS + 3 * MIN)).toBeNull();
  });
  it("скрытие: держится 10 минут, но возвращается за 5 минут до начала", () => {
    const at = STARTS - 25 * MIN;
    const until = at + DISMISS_MS;
    expect(maintenanceView(n, at + MIN, until)).toBeNull();
    expect(maintenanceView(n, until + 1, until)).not.toBeNull();
    // скрыли за 8 минут до начала: срок скрытия ещё идёт, но осталось ≤ 5 минут — баннер возвращается
    expect(maintenanceView(n, STARTS - 5 * MIN, STARTS - 8 * MIN + DISMISS_MS)).toMatchObject({
      phase: "soon",
      dismissible: false,
    });
    expect(maintenanceView(n, STARTS - 5 * MIN - 1, STARTS)).toBeNull();
  });
  it("скрытие не прячет работы", () => {
    expect(maintenanceView(n, STARTS + MIN, STARTS + 10 * MIN)).toMatchObject({
      phase: "running",
    });
  });
  it("срочное — kind urgent", () => {
    expect(maintenanceView(notice({ kind: "urgent" }), STARTS - MIN)?.kind).toBe("urgent");
  });
});

describe("companyTime", () => {
  it("всегда по Ташкенту", () => {
    expect(companyTime(Date.parse("2026-11-23T14:15:00Z"))).toBe("19:15");
    expect(companyTime(Date.parse("2026-11-23T19:05:00Z"))).toBe("00:05");
  });
});
