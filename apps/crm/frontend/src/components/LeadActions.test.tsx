import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { LeadDetail } from "../api/generated/model";
import { LeadActions, OwnerBanner } from "./LeadActions";
import { type ActionRights, availableActions, leadActionPlan, replyState } from "./leadActionRules";

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

const openEscalation = {
  id: 5,
  created_at: "2026-10-08T10:00:00Z",
  priority: "hot",
  reason_codes: ["human_requested"],
  reason_text: null,
  recommendation: null,
  sla_due_at: null,
  snoozed_until: null,
  status: "open",
  taken_at: null,
  taken_by_user_id: null,
};

const manager: ActionRights = {
  take: true,
  work: true,
  note: true,
  reply: true,
  clients: true,
  userId: 7,
  isAdmin: false,
};
const admin: ActionRights = { ...manager, userId: 1, isAdmin: true };
const viewer: ActionRights = { take: false, work: false, note: false, userId: 9, isAdmin: false };

const handoff = lead({ escalation: openEscalation });
const mine = lead({ stage: "in_progress", owner_mode: "human", assigned_user_id: 7 });
const theirs = lead({
  stage: "in_progress",
  owner_mode: "human",
  assigned_user_id: 3,
  assigned_user_name: "Азиза",
});
const customer = lead({ stage: "customer", owner_mode: "bot", assigned_user_id: 7 });
const won = lead({ stage: "won", owner_mode: "bot", assigned_user_id: 7 });
const engaged = lead({ stage: "engaged", owner_mode: "bot" });

describe("leadActionPlan — one primary action by state", () => {
  it.each([
    ["handoff without owner → take", handoff, manager, "take"],
    ["paused lead → take", lead({}), manager, "take"],
    ["my lead in progress → close as won", mine, manager, "won"],
    ["won lead → make customer", won, manager, "makeCustomer"],
    ["customer with the bot → new deal", customer, manager, "newDeal"],
    ["bot is talking, no handoff → no primary", engaged, manager, null],
    ["someone else's lead → no primary", theirs, manager, null],
    ["admin on someone else's lead → no primary (takeover is not primary)", theirs, admin, null],
    ["viewer → nothing", handoff, viewer, null],
  ] as const)("%s", (_, item, rights, primary) => {
    expect(leadActionPlan(item, rights).primary).toBe(primary);
  });

  it("puts rare actions into «More», dangerous ones last", () => {
    expect(leadActionPlan(mine, manager).more).toEqual(["note", "assign", "returnToBot", "lost"]);
  });

  it("someone else's lead: a banner instead of disabled buttons, only a note is left", () => {
    const plan = leadActionPlan(theirs, manager);
    expect(plan.ownerBanner).toEqual({ name: "Азиза", hint: true });
    expect(plan.more).toEqual(["note"]);
  });

  it("admin can take over someone else's lead only from «More», with the owner banner", () => {
    const plan = leadActionPlan(theirs, admin);
    expect(plan.ownerBanner).toEqual({ name: "Азиза", hint: false });
    expect(plan.more).toContain("takeOver");
    expect(plan.more).not.toContain("take");
    expect(plan.more.at(-1)).toBe("takeOver");
  });

  it("reassign follows the same visibility rule as the other owner actions", () => {
    expect(availableActions(mine, manager).assign).toBe(true);
    expect(availableActions(theirs, manager).assign).toBe(false);
    expect(availableActions(theirs, admin).assign).toBe(true);
  });

  it("viewer gets no actions and no banner on an unowned lead", () => {
    expect(leadActionPlan(handoff, viewer)).toEqual({
      primary: null,
      more: [],
      ownerBanner: null,
    });
  });
});

describe("availableActions", () => {
  it("lets a returning lost lead be taken again (ADR-0015)", () => {
    const lost = lead({ stage: "lost", owner_mode: "bot", assigned_user_id: 3 });
    expect(availableActions(lost, manager)).toMatchObject({ take: true, won: false });
  });

  it("hides return to bot for a closed lead already with the bot", () => {
    expect(availableActions(won, manager).returnToBot).toBe(false);
  });

  it.each([
    ["open handoff, nobody responsible", handoff, manager, true],
    [
      "open handoff, someone else responsible",
      lead({ escalation: openEscalation, assigned_user_id: 3 }),
      manager,
      false,
    ],
    [
      "open handoff, I am responsible",
      lead({ escalation: openEscalation, assigned_user_id: 7 }),
      manager,
      true,
    ],
    [
      "admin, someone else responsible",
      lead({ escalation: openEscalation, assigned_user_id: 3 }),
      admin,
      true,
    ],
    ["no open handoff", lead({}), manager, false],
    ["viewer", handoff, viewer, false],
  ] as const)("snooze (Q-018): %s → %s", (_, item, rights, can) => {
    expect(availableActions(item, rights).snooze).toBe(can);
  });

  const info = { ...openEscalation, priority: "info" };
  const infoBot = lead({ stage: "engaged", owner_mode: "bot", escalation: info });

  it.each([
    ["info, open, lead with the bot", infoBot, manager, true],
    [
      "info, snoozed",
      lead({ owner_mode: "bot", escalation: { ...info, status: "snoozed" } }),
      manager,
      true,
    ],
    ["hot handoff", handoff, manager, false],
    [
      "info, taken",
      lead({ owner_mode: "human", assigned_user_id: 7, escalation: { ...info, status: "taken" } }),
      manager,
      false,
    ],
    ["viewer", infoBot, viewer, false],
  ] as const)("acknowledge (audit P0-1): %s → %s", (_, item, rights, can) => {
    expect(availableActions(item, rights).acknowledge).toBe(can);
  });

  it("acknowledge is the primary action for an info escalation on a bot lead", () => {
    expect(leadActionPlan(infoBot, manager).primary).toBe("acknowledge");
  });

  it("snooze extends an already snoozed handoff", () => {
    const snoozed = lead({ escalation: { ...openEscalation, status: "snoozed" } });
    expect(availableActions(snoozed, manager).snooze).toBe(true);
  });

  it.each([
    ["snoozed, nobody responsible", "snoozed", null, manager, true],
    ["snoozed, someone else responsible", "snoozed", 3, manager, false],
    ["snoozed, admin", "snoozed", 3, admin, true],
    ["open handoff — nothing to return", "open", null, manager, false],
    ["viewer", "snoozed", null, viewer, false],
  ] as const)("unsnooze mirrors snooze rights: %s → %s", (_, status, owner, rights, can) => {
    const item = lead({ assigned_user_id: owner, escalation: { ...openEscalation, status } });
    expect(availableActions(item, rights).unsnooze).toBe(can);
    if (can) expect(leadActionPlan(item, rights).more).toContain("unsnooze");
  });

  it.each([
    ["won, nobody responsible", null, manager, true],
    ["won, I am responsible", 7, manager, true],
    ["won, someone else responsible", 3, manager, false],
    ["won, admin", 3, admin, true],
  ] as const)("makeCustomer = may_make_customer: %s → %s", (_, owner, rights, can) => {
    const item = lead({ stage: "won", owner_mode: "bot", assigned_user_id: owner });
    expect(availableActions(item, rights).makeCustomer).toBe(can);
  });
});

describe("replyState", () => {
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

const renderActions = (item: LeadDetail, rights: ActionRights) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AntApp>
          <OwnerBanner banner={leadActionPlan(item, rights).ownerBanner} />
          <LeadActions lead={item} rights={rights} />
        </AntApp>
      </MemoryRouter>
    </QueryClientProvider>,
  );

describe("LeadActions", () => {
  it("shows one primary verb and «More» for my lead", () => {
    renderActions(mine, manager);
    expect(screen.getByRole("button", { name: "Закрыть сделкой" })).toHaveClass("ant-btn-primary");
    expect(screen.getByRole("button", { name: /Ещё/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Закрыть отказом" })).toBeNull();
  });

  it("shows the owner banner and no disabled buttons on someone else's lead", () => {
    renderActions(theirs, manager);
    expect(screen.getByText("Лида ведёт Азиза")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить заметку" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Забрать" })).toBeNull();
    expect(screen.queryAllByRole("button").every((b) => !b.hasAttribute("disabled"))).toBe(true);
  });
});
