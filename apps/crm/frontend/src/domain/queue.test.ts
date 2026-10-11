import { describe, expect, it } from "vitest";

import type { EscalationOut, LeadOut } from "../api/generated/model";
import { inboxQueue, isTextTarget, queueKeyAction, queuePosition } from "./queue";

const escalation = (patch: Partial<EscalationOut>): EscalationOut => ({
  id: 1,
  created_at: "2026-10-12T05:00:00Z",
  sla_due_at: "2026-10-12T05:15:00Z",
  priority: "normal",
  reason_codes: ["human_requested"],
  reason_text: null,
  recommendation: null,
  snoozed_until: null,
  status: "open",
  taken_at: null,
  taken_by_user_id: null,
  ...patch,
});

const lead = (id: number, e: Partial<EscalationOut> | null = null): LeadOut => ({
  id,
  display_name: `Лид ${String(id)}`,
  language: "ru",
  stage: e ? "handoff" : "engaged",
  score: 40,
  owner_mode: e ? "paused" : "human",
  assigned_user_id: null,
  need_summary: null,
  product_interest: [],
  last_lead_msg_at: null,
  created_at: "2026-10-12T04:00:00Z",
  escalation: e ? escalation(e) : null,
});

describe("inboxQueue", () => {
  it("orders handoffs as the inbox does, then mine, then unassigned, each lead once", () => {
    const ids = inboxQueue({
      escalations: [
        lead(1, { priority: "normal", created_at: "2026-10-12T05:00:00Z" }),
        lead(2, { priority: "hot", created_at: "2026-10-12T05:10:00Z" }),
      ],
      mine: [lead(3), lead(1)],
      unassigned: [lead(4), lead(3)],
    });
    expect(ids).toEqual([2, 1, 3, 4]);
  });

  it("is empty for an empty inbox", () => {
    expect(inboxQueue({ escalations: [], mine: [], unassigned: [] })).toEqual([]);
  });
});

describe("queuePosition", () => {
  it.each([
    [1, { index: 0, total: 3, prevId: null, nextId: 2 }],
    [2, { index: 1, total: 3, prevId: 1, nextId: 3 }],
    [3, { index: 2, total: 3, prevId: 2, nextId: null }],
    [9, null],
  ])("lead %i", (id, expected) => {
    expect(queuePosition([1, 2, 3], id)).toEqual(expected);
  });
});

describe("queueKeyAction", () => {
  const key = (code: string, patch = {}) => ({
    code,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    inField: false,
    ...patch,
  });
  it.each([
    [key("KeyJ"), "next"],
    [key("KeyK"), "prev"],
    [key("KeyJ", { inField: true }), null],
    [key("KeyJ", { metaKey: true }), null],
    [key("KeyK", { ctrlKey: true }), null],
    [key("KeyK", { altKey: true }), null],
    [key("ArrowRight"), null],
  ])("%o → %s", (k, expected) => {
    expect(queueKeyAction(k)).toBe(expected);
  });
});

describe("isTextTarget", () => {
  it.each([
    ["textarea", true],
    ["input", true],
    ["select", true],
    ["button", false],
    ["div", false],
  ])("<%s>", (tag, expected) => {
    expect(isTextTarget(document.createElement(tag))).toBe(expected);
  });

  it("treats contenteditable and non-elements correctly", () => {
    const div = document.createElement("div");
    Object.defineProperty(div, "isContentEditable", { value: true });
    expect(isTextTarget(div)).toBe(true);
    expect(isTextTarget(null)).toBe(false);
  });
});
