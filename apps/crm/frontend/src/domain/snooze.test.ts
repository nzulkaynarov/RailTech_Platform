import dayjs from "dayjs";
import { describe, expect, it } from "vitest";

import { defaultSnooze, fromTashkentWall, snoozeDayDisabled, toTashkentWall } from "./snooze";

// 2026-10-12 22:30 UTC = 13.10 03:30 в Ташкенте (UTC+5): сутки уже другие.
const now = new Date("2026-10-12T22:30:00Z");

describe("snooze in Asia/Tashkent", () => {
  it("shows the Tashkent wall clock regardless of the browser zone", () => {
    expect(toTashkentWall(now).format("DD.MM.YYYY HH:mm")).toBe("13.10.2026 03:30");
  });

  it("defaults to two hours later", () => {
    expect(defaultSnooze(now).format("DD.MM.YYYY HH:mm")).toBe("13.10.2026 05:30");
  });

  it("converts the picked Tashkent time back to the instant", () => {
    expect(fromTashkentWall(dayjs("2026-10-13T10:00:00"))).toBe("2026-10-13T05:00:00.000Z");
    expect(fromTashkentWall(toTashkentWall(now))).toBe(now.toISOString());
  });

  it.each([
    ["2026-10-12", true],
    ["2026-10-13", false],
    ["2026-10-20", false],
    ["2026-10-21", true],
  ])("day %s disabled: %s", (day, disabled) => {
    expect(snoozeDayDisabled(dayjs(day), now)).toBe(disabled);
  });
});
