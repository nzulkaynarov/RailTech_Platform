import { describe, expect, it } from "vitest";

import type { AiSpendReport, AiSpendRow } from "../api/generated/model";
import {
  budgetText,
  dayColumnsSystems,
  daysNewestFirst,
  erpNotConnected,
  overrunText,
  periodRange,
  sliceLabel,
  systemCost,
  systemTiles,
  usdPrecise,
} from "./aiSpend";

const row = (key: string, systems: [string, number][]): AiSpendRow => ({
  key,
  calls: systems.length,
  failed_calls: 0,
  input_tokens: 10,
  output_tokens: 5,
  cost_usd: systems.reduce((s, [, c]) => s + c, 0),
  fallback_calls: 0,
  by_system: systems.map(([system, cost_usd]) => ({ system, cost_usd, calls: 1 })),
});

const budget = (system: string, period_calls = 1) => ({
  system,
  daily_usd: 1,
  today_usd: 0,
  today_calls: 0,
  over_today: false,
  period_usd: 0,
  period_calls,
  fallback_calls: 0,
  days_over: 0,
  connected: period_calls > 0,
});

const report = (over: Partial<AiSpendReport> = {}): AiSpendReport => ({
  date_from: "2026-10-08",
  date_to: "2026-10-14",
  group: "day",
  timezone: "Asia/Tashkent",
  rows: [],
  totals: {
    calls: 0,
    failed_calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: 0,
    fallback_calls: 0,
  },
  systems: [budget("crm"), budget("erp", 0), budget("other", 0)],
  overruns: [],
  erp_connected: false,
  truncated: false,
  fetched_at: "2026-10-14T05:00:00Z",
  ...over,
});

describe("aiSpend", () => {
  it("period is the last N days in Tashkent, today included", () => {
    // 20:30 UTC 13-го — уже 01:30 14-го в Ташкенте.
    expect(periodRange(7, new Date("2026-10-13T20:30:00Z"))).toEqual({
      from: "2026-10-08",
      to: "2026-10-14",
    });
    expect(periodRange(1, new Date("2026-10-14T05:00:00Z"))).toEqual({
      from: "2026-10-14",
      to: "2026-10-14",
    });
  });

  it.each([
    [0, "$0,00"],
    [0.0000135, "$0,000014"],
    [0.00427, "$0,00427"],
    [1.5, "$1,50"],
  ])("usdPrecise(%s) = %s", (value, text) => {
    expect(usdPrecise(value).replace(/\s/g, " ")).toBe(text);
  });

  it("budget text shows limit or no limit", () => {
    expect(budgetText({ today_usd: 0.5, daily_usd: 2 })).toBe("$0,50 из $2,00");
    expect(budgetText({ today_usd: 0.5, daily_usd: 0 })).toBe("$0,50, без лимита");
  });

  it.each([
    ["system", "crm", "CRM"],
    ["system", "other", "Без тега"],
    ["system", "cabinet", "CABINET"],
    ["feature", "kb-search", "Поиск по базе знаний"],
    ["feature", "intake", "ERP: разбор запроса"],
    ["feature", "new-thing", "new-thing"],
    ["model", "dialog-model", "Диалог (dialog-model)"],
    ["model", "intake-model", "intake-model"],
  ] as const)("slice label %s/%s", (group, key, label) => {
    expect(sliceLabel(group, key)).toBe(label);
  });

  it("tiles: CRM and ERP always, untagged only when used", () => {
    expect(systemTiles(report()).map((s) => s.system)).toEqual(["crm", "erp"]);
    const withOther = report({ systems: [budget("crm"), budget("erp"), budget("other", 2)] });
    expect(systemTiles(withOther).map((s) => s.system)).toEqual(["crm", "erp", "other"]);
  });

  it("ERP not connected until it has rows", () => {
    expect(erpNotConnected(report())).toBe(true);
    expect(erpNotConnected(report({ erp_connected: true }))).toBe(false);
  });

  it("day columns: CRM, ERP, then others; cost per system", () => {
    const first = row("2026-10-13", [["crm", 0.2]]);
    const rows = [first, row("2026-10-14", [["other", 0.1]])];
    expect(dayColumnsSystems(rows)).toEqual(["crm", "erp", "other"]);
    expect(systemCost(first, "crm")).toBe(0.2);
    expect(systemCost(first, "erp")).toBe(0);
    expect(daysNewestFirst(rows).map((r) => r.key)).toEqual(["2026-10-14", "2026-10-13"]);
  });

  it("overrun text", () => {
    expect(overrunText({ system: "erp", day: "2026-10-14", cost_usd: 1.2, daily_usd: 1 })).toBe(
      "ERP: 14.10.2026 — $1,20 при бюджете $1,00",
    );
  });
});
