import { describe, expect, it } from "vitest";

import type { Dashboard, PermissionsResponse } from "../api/generated/model";
import { dashboardTiles, reasonBars, tileLink, wonSum } from "./dashboard";

const day = {
  day: "2026-10-11",
  leads_created: 5,
  escalations: 2,
  taken: 2,
  won: 1,
  lost: 0,
  avg_take_minutes: 4,
  cost_usd: 0.1,
};
const data = {
  daily: [day],
  days: 30,
  escalation_reasons: {},
  fallback_share: 0.25,
  funnel: {},
  open_escalations: 1,
  open_gaps: 3,
  refreshed_at: null,
  totals: day,
} as unknown as Dashboard;

const matrix = (perms: Record<string, Record<string, boolean>>) =>
  ({ permissions: perms, roles: [] }) as unknown as PermissionsResponse;
const admin = matrix({ leads: { read: true, take: true }, kb: { read: true, write: true } });
// Менеджер читает базу знаний, но пробелы разбирает админ (`kb:write`).
const manager = matrix({ leads: { read: true, take: true }, kb: { read: true } });
const viewer = matrix({ leads: { read: true } });

describe("dashboard tiles", () => {
  const tiles = dashboardTiles(data, { from: "2026-09-12", to: "2026-10-11" });

  it("puts four business metrics first", () => {
    expect(tiles.primary.map((x) => x.key)).toEqual(["leads", "taken", "won", "takeTime"]);
    expect(tiles.secondary.find((x) => x.key === "fallback")?.value).toBe("25%");
  });

  it("won deals drill down to the deals list filtered by «Выиграна» (ADR-0019)", () => {
    expect(tiles.primary.find((x) => x.key === "won")?.target).toEqual({
      resource: "deals",
      path: "/deals?stage=won",
    });
  });

  it.each([
    ["admin", admin, ["leads", "openEscalations", "gaps"]],
    ["manager", manager, ["leads", "openEscalations"]],
    ["viewer", viewer, ["leads"]],
  ])("%s gets links only to allowed sections", (_role, perms, expected) => {
    const linked = [...tiles.primary, ...tiles.secondary]
      .filter((tile) => tileLink(tile.target, perms) !== null)
      .map((tile) => tile.key);
    expect(linked).toEqual(expected);
  });

  it("leads tile links to the period", () => {
    const leads = tiles.primary[0];
    expect(tileLink(leads?.target ?? null, viewer)).toContain("from=2026-09-12");
  });
});

describe("reason bars", () => {
  it("sorts by count, drops zeros, scales to the maximum", () => {
    expect(reasonBars({ complaint: 1, agent_unavailable: 4, no_progress: 0 })).toEqual([
      { code: "agent_unavailable", value: 4, percent: 100 },
      { code: "complaint", value: 1, percent: 25 },
    ]);
  });
});

describe("won sum (audit 2026-10-12)", () => {
  const base = { days: 30, lost_by_reason: [], lost_count: 0, open_count: 0 };
  const plain = (v: string | null) => v?.replace(/\u00a0/g, " ") ?? null;
  it.each([
    ["no wins", 0, 0, [], "—", null],
    [
      "no amounts",
      2,
      2,
      [{ amount: "0", currency: "UZS" }],
      "—",
      "Суммы не указаны в выигранных сделках (2)",
    ],
    [
      "partial",
      3,
      1,
      [{ amount: "1200000", currency: "UZS" }],
      "1 200 000 UZS",
      "Сделок без суммы: 1 — итог неполный",
    ],
    ["full", 1, 0, [{ amount: "1200000", currency: "UZS" }], "1 200 000 UZS", null],
  ])("%s", (_name, won, missing, amounts, value, hint) => {
    const sum = wonSum({
      ...base,
      won_count: won,
      won_without_amount: missing,
      won_amounts: amounts,
    });
    expect(plain(sum.value)).toBe(value);
    expect(sum.hint).toBe(hint);
  });
});
