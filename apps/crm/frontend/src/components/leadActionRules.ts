import type { LeadDetail } from "../api/generated/model";
import { ownerModeLabel } from "../domain/labels";
import { t } from "../i18n/ru";

export type ActionRights = {
  take: boolean;
  work: boolean;
  note: boolean;
  reply?: boolean;
  clients?: boolean;
  userId: number;
  isAdmin: boolean;
};

/** Показывать ли кнопку и почему она неактивна (аудит UI U-03: не прятать молча). */
export type ActionState = { visible: boolean; reason?: string };

export type ActionKey =
  "take" | "returnToBot" | "snooze" | "close" | "assign" | "newDeal" | "note" | "makeCustomer";

const PRE_WORK = new Set(["new", "engaged", "qualified", "handoff", "unresponsive"]);
const hidden: ActionState = { visible: false };
const shown: ActionState = { visible: true };
const blocked = (reason: string): ActionState => ({ visible: true, reason });

const ownerName = (lead: LeadDetail): string => lead.assigned_user_name ?? ownerModeLabel("human");
const otherOwner = (lead: LeadDetail): string =>
  t.why.otherOwner.replace("{name}", ownerName(lead));

/** Ведёт ли лида другой человек (а я не админ) — тогда владельческие действия заблокированы. */
function foreign(lead: LeadDetail, rights: ActionRights): boolean {
  return lead.owner_mode === "human" && lead.assigned_user_id !== rights.userId && !rights.isAdmin;
}

/** Состояние каждого действия для лида (UI; права всё равно проверит бэкенд). */
export function leadActionStates(
  lead: LeadDetail,
  rights: ActionRights,
): Record<ActionKey, ActionState> {
  const mine = lead.owner_mode === "human" && lead.assigned_user_id === rights.userId;
  const human = lead.owner_mode === "human";
  const other = foreign(lead, rights);
  const ownerOnly = (visible: boolean): ActionState =>
    !visible ? hidden : other ? blocked(otherOwner(lead)) : shown;
  return {
    // «Забрать» и из «Отказа»: вернувшегося лида снова берут в работу (ADR-0015).
    take: !rights.take || mine ? hidden : other ? blocked(otherOwner(lead)) : shown,
    returnToBot: ownerOnly(rights.work && lead.owner_mode !== "bot"),
    snooze: rights.work && lead.escalation?.status === "open" ? shown : hidden,
    close:
      rights.work && lead.stage === "in_progress"
        ? ownerOnly(true)
        : rights.work && PRE_WORK.has(lead.stage)
          ? blocked(t.why.takeFirst)
          : hidden,
    assign: ownerOnly(rights.work && human),
    newDeal: rights.work && lead.stage === "customer" && !human ? shown : hidden,
    note: rights.note ? shown : hidden,
    makeCustomer: rights.clients && lead.stage === "won" ? shown : hidden,
  };
}

/** Совместимость: «можно нажать» = видно и не заблокировано. */
export function availableActions(lead: LeadDetail, rights: ActionRights) {
  const states = leadActionStates(lead, rights);
  return Object.fromEntries(
    Object.entries(states).map(([key, s]) => [key, s.visible && !s.reason]),
  ) as Record<ActionKey, boolean>;
}

/** Может ли пользователь ответить лиду, а если нет — понятная причина под чатом. */
export function replyState(lead: LeadDetail, rights: ActionRights): { can: boolean; hint: string } {
  if (!rights.reply) return { can: false, hint: t.why.replyViewer };
  if (foreign(lead, rights)) {
    return { can: false, hint: t.why.replyOther.replace("{name}", ownerName(lead)) };
  }
  if (lead.owner_mode !== "human") return { can: false, hint: t.why.replyTake };
  return { can: true, hint: "" };
}

/** Админ забирает лида у другого менеджера — это перехват, его подтверждают. */
export const isTakeover = (lead: LeadDetail, rights: ActionRights): boolean =>
  rights.isAdmin &&
  lead.owner_mode === "human" &&
  lead.assigned_user_id !== null &&
  lead.assigned_user_id !== rights.userId;
