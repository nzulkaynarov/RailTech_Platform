import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, formatWhen, fromNow } from "./time";

describe("time in Asia/Tashkent", () => {
  it("shows Tashkent time regardless of the browser zone", () => {
    expect(formatDateTime("2026-10-09T05:30:00Z")).toBe("09.10.2026 10:30");
  });

  it("keeps date-only values on the same day", () => {
    expect(formatDate("2026-07-14")).toBe("14.07.2026");
  });

  it("crosses midnight by Tashkent, not UTC", () => {
    expect(formatDate("2026-10-09T20:00:00Z")).toBe("10.10.2026");
  });

  it.each([
    ["2026-10-09T05:30:00Z", "10:30"],
    ["2026-03-01T05:30:00Z", "01.03 10:30"],
    ["2025-12-31T05:30:00Z", "31.12.2025 10:30"],
  ])("formatWhen %s", (value, expected) => {
    expect(formatWhen(value, "2026-10-09T09:00:00Z")).toBe(expected);
  });

  it("speaks Russian for relative time", () => {
    expect(fromNow("2026-10-09T08:00:00Z", "2026-10-09T09:00:00Z")).toBe("час назад");
  });
});
