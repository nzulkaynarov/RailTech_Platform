import { renderUi as render } from "../../test/renderUi";
import { describe, expect, it } from "vitest";

import { daysUntil } from "../lib/format";
import { TimeLeft } from "./TimeLeft";

// Полдень 14.10.2026 в Ташкенте.
const NOW = Date.parse("2026-10-14T07:00:00Z");

describe("TimeLeft (план §3f РЕФ-3)", () => {
  it("считает дни по календарю компании", () => {
    expect(daysUntil("2026-10-24", NOW)).toBe(10);
    expect(daysUntil("2026-10-14T23:00:00+05:00", NOW)).toBe(0);
    expect(daysUntil("2026-10-13", NOW)).toBe(-1);
  });

  it("осталось N дн., сегодня — последний день; два дня и меньше — предупреждением", () => {
    expect(render(<TimeLeft date="2026-10-24" now={NOW} />).container).toHaveTextContent(
      "осталось 10 дн.",
    );
    expect(render(<TimeLeft date="2026-10-14" now={NOW} />).container).toHaveTextContent(
      "сегодня последний день",
    );
    expect(
      render(<TimeLeft date="2026-10-16" now={NOW} />).container.querySelector(".pf-time-left"),
    ).toHaveClass("pf-time-left--soon");
    expect(
      render(<TimeLeft date="2026-10-20" now={NOW} />).container.querySelector(".pf-time-left"),
    ).not.toHaveClass("pf-time-left--soon");
  });

  it("прошедший срок и пустая дата не показываются", () => {
    expect(
      render(<TimeLeft date="2026-10-13" now={NOW} />).container.querySelector(".pf-time-left"),
    ).toBeNull();
    expect(
      render(<TimeLeft date={null} now={NOW} />).container.querySelector(".pf-time-left"),
    ).toBeNull();
  });
});
