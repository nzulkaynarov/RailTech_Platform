import type { LeadDetail } from "../api/generated/model";

export type ActionRights = {
  take: boolean;
  work: boolean;
  note: boolean;
  clients?: boolean;
  userId: number;
  isAdmin: boolean;
};

/** Какие действия показать для лида (UI; права всё равно проверит бэкенд). */
export function availableActions(lead: LeadDetail, rights: ActionRights) {
  const owner = lead.assigned_user_id === rights.userId || rights.isAdmin;
  const mine = lead.owner_mode === "human" && lead.assigned_user_id === rights.userId;
  return {
    take: rights.take && !mine && lead.stage !== "lost",
    returnToBot:
      rights.work && lead.owner_mode !== "bot" && (owner || lead.owner_mode === "paused"),
    snooze: rights.work && lead.escalation?.status === "open",
    close: rights.work && lead.stage === "in_progress" && owner,
    note: rights.note,
    makeCustomer: Boolean(rights.clients) && lead.stage === "won",
  };
}
