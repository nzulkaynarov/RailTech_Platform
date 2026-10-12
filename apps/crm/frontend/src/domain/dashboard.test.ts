import { describe, expect, it } from "vitest";

import type { Dashboard, PermissionsResponse } from "../api/generated/model";
import { dashboardTiles, reasonBars, tileLink } from "./dashboard";

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
const admin = matrix({ leads: { read: true, take: true }, kb: { read: true } });
const manager = matrix({ leads: { read: true, take: true } });
const viewer = matrix({ leads: { read: true } });

describe("dashboard tiles", () => {
  const tiles = dashboardTiles(data, { from: "2026-09-12", to: "2026-10-11" });

  it("puts four business metrics first", () => {
    expect(tiles.primary.map((x) => x.key)).toEqual(["leads", "taken", "won", "takeTime"]);
    expect(tiles.secondary.find((x) => x.key === "fallback")?.value).toBe("25%");
  });

  it("won deals have no drill-down (they move on to «Клиент»)", () => {
    expect(tiles.primary.find((x) => x.key === "won")?.target).toBeNull();
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
