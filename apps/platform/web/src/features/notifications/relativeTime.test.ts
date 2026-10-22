import { describe, expect, it } from "vitest";

import { relativeTime } from "./relativeTime";

const labels = {
  now: "сейчас",
  minutes: (n: number) => `${String(n)} мин`,
  hours: (n: number) => `${String(n)} ч`,
};
const NOW = new Date("2026-10-22T08:00:00Z"); // 13:00 в Ташкенте
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();

describe("relativeTime", () => {
  it("минуты и часы", () => {
    expect(relativeTime(ago(20_000), NOW, labels, "ru")).toBe("сейчас");
    expect(relativeTime(ago(5 * 60_000), NOW, labels, "ru")).toBe("5 мин");
    expect(relativeTime(ago(59 * 60_000), NOW, labels, "ru")).toBe("59 мин");
    expect(relativeTime(ago(60 * 60_000), NOW, labels, "ru")).toBe("1 ч");
    expect(relativeTime(ago(23 * 3_600_000), NOW, labels, "ru")).toBe("23 ч");
  });

  it("старше суток — «вчера» с временем или дата в поясе компании", () => {
    expect(relativeTime("2026-10-21T04:24:00Z", NOW, labels, "ru")).toBe("вчера 09:24");
    expect(relativeTime("2026-10-18T06:50:00Z", NOW, labels, "ru")).toBe("18.10 11:50");
  });

  it("мусор вместо времени — пустая строка", () => {
    expect(relativeTime("не дата", NOW, labels, "ru")).toBe("");
  });
});
