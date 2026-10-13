import { describe, expect, it } from "vitest";

import { aiText, eventText, splitDecisions, type DecisionItem } from "./decisions";

const tr = (from: string, to: string, reason: string): DecisionItem => ({
  kind: "transition",
  id: 1,
  at: "2026-10-12T09:00:00Z",
  from_stage: from,
  to_stage: to,
  source: "trigger",
  actor_user_id: null,
  reason,
});

const run = (over: Partial<Extract<DecisionItem, { kind: "qualifier" }>> = {}) =>
  ({
    kind: "qualifier",
    id: 2,
    at: "2026-10-12T09:00:00Z",
    intent: null,
    sentiment: null,
    proposed_stage: "qualified",
    applied_stage: null,
    rejected_reason: null,
    score_before: 10,
    score_after: 10,
    triggers_fired: [],
    escalated: false,
    next_best_action: null,
    error: null,
    model: null,
    cost_usd: null,
    trace_id: null,
    ...over,
  }) as Extract<DecisionItem, { kind: "qualifier" }>;

describe("eventText", () => {
  it.each([
    [tr("engaged", "handoff", "callback_requested"), "Передан менеджеру: просит звонок"],
    [tr("handoff", "in_progress", "taken by manager"), "Менеджер забрал"],
    [tr("in_progress", "engaged", "returned to bot"), "Вернули боту"],
  ])("%#", (item, expected) => {
    expect(eventText(item as Extract<DecisionItem, { kind: "transition" }>)).toBe(expected);
  });
});

describe("aiText", () => {
  it("never shows internal rule words", () => {
    const text = aiText(run({ rejected_reason: "transition won -> engaged is not allowed" }));
    expect(text).not.toMatch(/правил|отклон|not allowed/);
    expect(text).toContain("ИИ предложил");
  });

  it("shows score only when it changed", () => {
    expect(aiText(run())).not.toMatch(/оценка/);
    expect(aiText(run({ score_after: 40 }))).toContain("оценка 10 → 40");
  });
});

describe("splitDecisions", () => {
  it("separates events, AI proposals and errors", () => {
    const groups = splitDecisions([
      tr("new", "engaged", "lead wrote again"),
      run(),
      run({ error: "LlmUnavailableError: x" }),
    ]);
    expect(groups.events).toHaveLength(1);
    expect(groups.ai).toHaveLength(1);
    expect(groups.errors).toHaveLength(1);
  });
});
