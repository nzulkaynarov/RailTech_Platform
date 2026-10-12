import { describe, expect, it } from "vitest";

import type { DailyStat, SpendReport } from "../api/generated/model";
import {
  dealPoints,
  flowPoints,
  funnelSlices,
  isDarkColor,
  isEmpty,
  limitRows,
  lostSlices,
  purposeSlices,
  reasonSlices,
  seriesTotals,
  shortDay,
  spendPoints,
  summarize,
  trend,
} from "./dashboardCharts";

const day = (d: string, leads: number, won = 0): DailyStat => ({
  day: d,
  leads_created: leads,
  escalations: 1,
  taken: 1,
  won,
  lost: 0,
  bot_answers: 3,
  fallbacks: 1,
  avg_take_minutes: 5,
  cost_usd: 0.1,
});

describe("series", () => {
  it("builds long-format points per series with short day labels", () => {
    const points = flowPoints([day("2026-10-11", 5, 1), day("2026-10-12", 2)]);
    expect(points).toHaveLength(8);
    expect(points[0]).toEqual({ day: "11.10", series: "Новые лиды", value: 5 });
    expect(seriesTotals(points)).toEqual([
      { label: "Новые лиды", value: 7 },
      { label: "Передачи", value: 2 },
      { label: "Забрали", value: 2 },
      { label: "Выиграно", value: 1 },
    ]);
  });

  it("deal series: won and lost per day", () => {
    expect(dealPoints([{ day: "2026-10-01", won: 2, lost: 1 }])).toEqual([
      { day: "01.10", series: "Выиграно", value: 2 },
      { day: "01.10", series: "Проиграно", value: 1 },
    ]);
  });

  it("spend series: test stack only when there were tests", () => {
    const rows = [{ day: "2026-10-12", work_usd: 0.5, test_usd: 0.2 }];
    expect(spendPoints(rows, false).map((p) => p.series)).toEqual(["Работа"]);
    expect(spendPoints(rows, true).map((p) => p.value)).toEqual([0.5, 0.2]);
  });

  it("short day is timezone-independent", () => {
    expect(shortDay("2026-01-05")).toBe("05.01");
  });
});

describe("slices", () => {
  it("funnel keeps every stage in order, zeros included", () => {
    const slices = funnelSlices({ handoff: 2 });
    expect(slices).toHaveLength(9);
    expect(slices.filter((s) => s.value > 0)).toEqual([{ label: "Передан", value: 2 }]);
  });

  it("reasons sorted by count, zeros dropped, labelled", () => {
    const slices = reasonSlices({ complaint: 1, agent_unavailable: 4, no_progress: 0 });
    expect(slices.map((s) => s.value)).toEqual([4, 1]);
    expect(slices.every((s) => !s.label.includes("_"))).toBe(true);
  });

  it("lost reasons and purposes drop empty slices", () => {
    expect(lostSlices([{ reason: "Дорого", count: 2, amount: "0" }])).toEqual([
      { label: "Дорого", value: 2 },
    ]);
    const purposes = purposeSlices([
      { key: "dialog", calls: 3, cost_usd: 0.12 },
      { key: "probe", calls: 1, cost_usd: 0 },
    ]);
    expect(purposes).toEqual([{ label: "Диалог с клиентом", value: 0.12 }]);
  });
});

describe("empty state", () => {
  it.each([
    [[], true],
    [[{ value: 0 }, { value: 0 }], true],
    [[{ value: 0 }, { value: 1 }], false],
  ])("%j → %s", (rows, expected) => {
    expect(isEmpty(rows)).toBe(expected);
  });
});

describe("trend vs previous period", () => {
  it.each([
    [10, null, null],
    [10, undefined, null],
    [null, 5, null],
    [0, 0, { direction: "flat", text: "как в прошлом периоде" }],
    [3, 0, { direction: "up", text: "в прошлом периоде — 0" }],
    [15, 10, { direction: "up", text: "+50% к прошлому периоду" }],
    [5, 10, { direction: "down", text: "−50% к прошлому периоду" }],
    [10, 10, { direction: "flat", text: "как в прошлом периоде" }],
  ])("%s vs %s", (current, previous, expected) => {
    expect(trend(current, previous)).toEqual(expected);
  });
});

describe("text alternative", () => {
  it("lists title and key numbers; empty says so", () => {
    expect(summarize("Воронка", [{ label: "Новый", value: 1200 }])).toBe("Воронка. Новый — 1 200");
    expect(summarize("Воронка", [])).toBe("Воронка. За период данных нет");
  });
});

describe("limits bullet", () => {
  it("percent of each limit; no limit — no row", () => {
    const report = {
      providers: [
        { provider: "anthropic", spent_usd: 1, limit_usd: 4 },
        { provider: "gemini", spent_usd: 1, limit_usd: 0 },
      ],
      today_usd: 3,
      daily_usd: 2,
    } as unknown as SpendReport;
    expect(limitRows(report)).toEqual([
      { title: "anthropic", ranges: [100, 80], measures: [25], targets: [100] },
      {
        title: "Дневной бюджет (переход на резервную модель)",
        ranges: [100, 80],
        measures: [150],
        targets: [100],
      },
    ]);
  });
});

describe("chart theme", () => {
  it.each([
    ["#ffffff", false],
    ["#141414", true],
    ["#000", true],
    ["#fff", false],
    ["not-a-color", false],
  ])("%s dark=%s", (color, dark) => {
    expect(isDarkColor(color)).toBe(dark);
  });
});
