/**
 * Лента «Почему система так решила»: по умолчанию — только настоящие события (смена
 * стадии, передача менеджеру), предложения ИИ — свёрнуты, ошибки квалификатора — админу.
 */
import type { DecisionsResponse } from "../api/generated/model";
import { t } from "../i18n/ru";
import { rejectedReason, stageLabel, transitionReason } from "./labels";

export type DecisionItem = DecisionsResponse["items"][number];
type Transition = Extract<DecisionItem, { kind: "transition" }>;
export type QualifierRun = Extract<DecisionItem, { kind: "qualifier" }>;

export type DecisionGroups = {
  events: Transition[];
  ai: QualifierRun[];
  errors: QualifierRun[];
};

export function splitDecisions(items: readonly DecisionItem[]): DecisionGroups {
  const groups: DecisionGroups = { events: [], ai: [], errors: [] };
  for (const item of items) {
    if (item.kind === "transition") groups.events.push(item);
    else if (item.error) groups.errors.push(item);
    else groups.ai.push(item);
  }
  return groups;
}

const stage = (code: string | null | undefined): string =>
  code ? stageLabel(code).label : t.common.none;

const withWhy = (head: string, why: string): string => (why ? `${head}: ${why}` : head);

/** Событие словами: «Передан менеджеру: просит звонок», «Менеджер забрал», «Вернули боту». */
export function eventText(item: Transition): string {
  if (item.reason === "taken by manager") return t.lead.takenByManager;
  if (item.reason === "returned to bot") return t.lead.returnedToBot;
  const why = transitionReason(item.reason);
  if (item.to_stage === "handoff") return withWhy(t.lead.handedOff, why.toLowerCase());
  return withWhy(
    `${t.lead.stageChanged}: ${stage(item.from_stage)} → ${stage(item.to_stage)}`,
    why,
  );
}

/** Предложение ИИ одной строкой — без служебных слов. */
export function aiText(item: QualifierRun): string {
  const parts = [
    `${t.lead.proposed}: ${stage(item.proposed_stage)}`,
    item.rejected_reason ? rejectedReason(item.rejected_reason) : "",
    item.score_before !== item.score_after
      ? `${t.lead.score} ${String(item.score_before)} → ${String(item.score_after)}`
      : "",
  ];
  return parts.filter(Boolean).join(" · ");
}
