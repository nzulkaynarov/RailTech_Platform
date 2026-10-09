import { describe, expect, it } from "vitest";

import type { LeadDetail } from "../api/generated/model";
import {
  type ActionRights,
  availableActions,
  isTakeover,
  leadActionStates,
  replyState,
} from "./leadActionRules";

const lead = (patch: Partial<LeadDetail>): LeadDetail => ({
  id: 1,
  display_name: "Азиз",
  language: "ru",
  stage: "handoff",
  score: 40,
  owner_mode: "paused",
  assigned_user_id: null,
  need_summary: null,
  product_interest: [],
  last_lead_msg_at: null,
  created_at: "2026-10-08T10:00:00Z",
  escalation: null,
  qualification: {},
  consent_given_at: null,
  tg_username: null,
  notes_count: 0,
  snoozed_until: null,
  ...patch,
});

const manager: ActionRights = {
  take: true,
  work: true,
  note: true,
  reply: true,
  userId: 7,
  isAdmin: false,
};
const admin: ActionRights = { ...manager, userId: 1, isAdmin: true };
const viewer: ActionRights = { take: false, work: false, note: false, userId: 9, isAdmin: false };

describe("availableActions", () => {
  it("offers take and return for an escalated lead", () => {
    const actions = availableActions(lead({}), manager);
    expect(actions).toMatchObject({ take: true, returnToBot: true, close: false });
  });

  it("lets the owner close an in-progress lead", () => {
    const mine = lead({ stage: "in_progress", owner_mode: "human", assigned_user_id: 7 });
    expect(availableActions(mine, manager)).toMatchObject({ take: false, close: true });
  });

  it("hides owner actions for someone else's lead", () => {
    const theirs = lead({ stage: "in_progress", owner_mode: "human", assigned_user_id: 3 });
    expect(availableActions(theirs, manager)).toMatchObject({ returnToBot: false, close: false });
  });

  it("lets a returning lost lead be taken again (ADR-0015)", () => {
    const lost = lead({ stage: "lost", owner_mode: "bot", assigned_user_id: 3 });
    expect(availableActions(lost, manager)).toMatchObject({ take: true, close: false });
  });

  it("offers a new deal for a customer the bot is serving", () => {
    const customer = lead({ stage: "customer", owner_mode: "bot", assigned_user_id: 7 });
    expect(availableActions(customer, manager)).toMatchObject({ newDeal: true, assign: false });
  });

  it("lets the owner hand the lead over to a colleague", () => {
    const mine = lead({ stage: "in_progress", owner_mode: "human", assigned_user_id: 7 });
    const theirs = lead({ stage: "in_progress", owner_mode: "human", assigned_user_id: 3 });
    expect(availableActions(mine, manager).assign).toBe(true);
    expect(availableActions(theirs, manager).assign).toBe(false);
  });

  it("shows nothing to a viewer", () => {
    expect(Object.values(availableActions(lead({}), viewer)).some(Boolean)).toBe(false);
  });
});

describe("leadActionStates — why an action is unavailable", () => {
  const theirs = lead({
    stage: "in_progress",
    owner_mode: "human",
    assigned_user_id: 3,
    assigned_user_name: "Азиза",
  });

  it("shows owner actions of someone else's lead as disabled with the owner's name", () => {
    const states = leadActionStates(theirs, manager);
    expect(states.close.visible).toBe(true);
    expect(states.close.reason).toContain("Азиза");
    expect(states.take.reason).toContain("Азиза");
    expect(states.returnToBot.reason).toContain("Азиза");
  });

  it("asks to take an escalated lead before closing it", () => {
    expect(leadActionStates(lead({}), manager).close).toEqual({
      visible: true,
      reason: "Сначала нажмите «Забрать»",
    });
  });

  it("lets an admin take over, but confirms it", () => {
    expect(leadActionStates(theirs, admin).take).toEqual({ visible: true });
    expect(isTakeover(theirs, admin)).toBe(true);
    expect(isTakeover(lead({}), admin)).toBe(false);
  });

  it("hides return to bot for a closed lead already with the bot", () => {
    const won = lead({ stage: "won", owner_mode: "bot", assigned_user_id: 7 });
    expect(leadActionStates(won, manager).returnToBot.visible).toBe(false);
  });

  it.each([
    ["viewer", lead({}), viewer, false, "Наблюдатель"],
    ["someone else's lead", theirs, manager, false, "Азиза"],
    ["not taken yet", lead({}), manager, false, "Забрать"],
    ["my lead", lead({ owner_mode: "human", assigned_user_id: 7 }), manager, true, ""],
    ["admin on any human lead", theirs, admin, true, ""],
  ])("reply: %s", (_, item, rights, can, hint) => {
    const state = replyState(item, rights);
    expect(state.can).toBe(can);
    expect(state.hint).toContain(hint);
  });
});
