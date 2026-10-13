import { describe, expect, it } from "vitest";

import type { EscalationOut, LeadOut } from "../api/generated/model";
import { formatWait, isWaiting, openHandoffCount, slaState, sortHandoffs } from "./sla";

const escalation = (patch: Partial<EscalationOut> = {}): EscalationOut => ({
  id: 1,
  created_at: "2026-10-12T05:00:00Z",
  sla_due_at: "2026-10-12T05:15:00Z",
  priority: "hot",
  reason_codes: ["human_requested"],
  reason_text: null,
  recommendation: null,
  snoozed_until: null,
  status: "open",
  taken_at: null,
  taken_by_user_id: null,
  ...patch,
});

const lead = (id: number, patch: Partial<EscalationOut> | null): LeadOut => ({
  id,
  display_name: `Лид ${String(id)}`,
  language: "ru",
  stage: "handoff",
  score: 40,
  owner_mode: "paused",
  assigned_user_id: null,
  need_summary: null,
  product_interest: [],
  last_lead_msg_at: null,
  created_at: "2026-10-12T04:00:00Z",
  escalation: patch === null ? null : escalation({ id, ...patch }),
});

const at = (iso: string) => new Date(iso);

describe("slaState", () => {
  it.each([
    ["just created", "2026-10-12T05:01:00Z", {}, "ok"],
    ["before 80% of the window", "2026-10-12T05:11:00Z", {}, "ok"],
    ["at 80% of the window", "2026-10-12T05:12:00Z", {}, "warning"],
    ["at the due time", "2026-10-12T05:15:00Z", {}, "overdue"],
    ["long overdue", "2026-10-13T08:00:00Z", {}, "overdue"],
    [
      "snoozed into the future",
      "2026-10-12T06:00:00Z",
      { status: "snoozed", snoozed_until: "2026-10-12T09:00:00Z" },
      "snoozed",
    ],
    [
      "snooze already expired",
      "2026-10-12T10:00:00Z",
      { status: "snoozed", snoozed_until: "2026-10-12T09:00:00Z" },
      "overdue",
    ],
    ["no due time → default 15 min", "2026-10-12T05:16:00Z", { sla_due_at: null }, "overdue"],
    ["no due time, early", "2026-10-12T05:05:00Z", { sla_due_at: null }, "ok"],
    // Срок в рабочих минутах: передача вечером — срок утром, ночью не краснеет.
    [
      "off-hours: due next morning",
      "2026-10-12T15:00:00Z",
      { created_at: "2026-10-12T14:00:00Z", sla_due_at: "2026-10-13T04:15:00Z" },
      "ok",
    ],
    [
      "off-hours: no early warning in the morning before work",
      "2026-10-13T03:50:00Z",
      { created_at: "2026-10-12T14:00:00Z", sla_due_at: "2026-10-13T04:15:00Z" },
      "ok",
    ],
    [
      "off-hours: warning 12 min before the due time",
      "2026-10-13T04:03:00Z",
      { created_at: "2026-10-12T14:00:00Z", sla_due_at: "2026-10-13T04:15:00Z" },
      "warning",
    ],
  ] as const)("%s", (_, now, patch, level) => {
    expect(slaState(escalation(patch), at(now)).level).toBe(level);
  });

  it("measures waiting from the handoff time and never negative", () => {
    expect(slaState(escalation(), at("2026-10-12T05:10:00Z")).waitingMs).toBe(10 * 60_000);
    expect(slaState(escalation(), at("2026-10-12T04:00:00Z")).waitingMs).toBe(0);
  });
});

describe("formatWait", () => {
  it.each([
    [30_000, "< 1 мин"],
    [12 * 60_000, "12 мин"],
    [60 * 60_000, "1 ч"],
    [65 * 60_000, "1 ч 5 мин"],
    [24 * 60 * 60_000, "1 д"],
    [26 * 60 * 60_000 + 59 * 60_000, "1 д 2 ч"],
  ])("%s ms → %s", (ms, text) => {
    expect(formatWait(ms)).toBe(text);
  });
});

describe("sortHandoffs", () => {
  it("puts hot first, then the longest waiting; snoozed and info go down", () => {
    const leads = [
      lead(1, { priority: "warm", created_at: "2026-10-12T03:00:00Z" }),
      lead(2, { priority: "hot", created_at: "2026-10-12T05:00:00Z" }),
      lead(3, { priority: "hot", created_at: "2026-10-12T04:00:00Z" }),
      lead(4, { priority: "hot", status: "snoozed", created_at: "2026-10-12T01:00:00Z" }),
      lead(5, { priority: "info", created_at: "2026-10-12T00:00:00Z" }),
      lead(6, null),
    ];
    expect(sortHandoffs(leads).map((l) => l.id)).toEqual([3, 2, 1, 5, 4, 6]);
  });

  it("does not mutate the input", () => {
    const leads = [lead(2, { priority: "warm" }), lead(1, { priority: "hot" })];
    sortHandoffs(leads);
    expect(leads.map((l) => l.id)).toEqual([2, 1]);
  });
});

describe("openHandoffCount", () => {
  it("counts only open handoffs", () => {
    const escalations = [lead(1, {}), lead(2, { status: "snoozed" }), lead(3, {})];
    expect(openHandoffCount({ escalations })).toBe(2);
    expect(openHandoffCount(undefined)).toBe(0);
  });
});

describe("isWaiting", () => {
  it.each([
    ["open", true],
    ["snoozed", true],
    ["taken", false],
    ["closed", false],
  ])("%s → %s", (status, waiting) => {
    expect(isWaiting(escalation({ status }))).toBe(waiting);
  });

  it("no escalation is not waiting", () => {
    expect(isWaiting(null)).toBe(false);
  });
});
