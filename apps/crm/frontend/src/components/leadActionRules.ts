/**
 * Какие действия доступны в карточке лида и какое из них главное (дизайн-аудит 2026-10-11,
 * отчёт 1/2): одно primary по состоянию, остальное — в меню «Ещё», чужой лид — баннер
 * вместо неактивных кнопок. Это только UI: права всё равно проверяет бэкенд.
 */
import type { LeadDetail } from "../api/generated/model";
import { ownerModeLabel } from "../domain/labels";
import { t } from "../i18n/ru";

export type ActionRights = {
  take: boolean;
  work: boolean;
  note: boolean;
  reply?: boolean;
  /** ИИ-помощь при ответе (Q-019), право `leads:assist`. */
  assist?: boolean;
  clients?: boolean;
  userId: number;
  isAdmin: boolean;
};

export type ActionKey =
  | "acknowledge"
  | "take"
  | "takeOver"
  | "won"
  | "lost"
  | "snooze"
  | "unsnooze"
  | "returnToBot"
  | "assign"
  | "newDeal"
  | "makeCustomer"
  | "note";

/** Порядок пунктов в «Ещё»: сначала работа с лидом, опасное и редкое — внизу. */
export const ACTION_ORDER: readonly ActionKey[] = [
  "acknowledge",
  "take",
  "won",
  "makeCustomer",
  "newDeal",
  "note",
  "snooze",
  "unsnooze",
  "assign",
  "returnToBot",
  "lost",
  "takeOver",
];

/** Опасные действия: красный пункт меню и подтверждение. */
export const DANGER_ACTIONS: ReadonlySet<ActionKey> = new Set(["lost", "takeOver"]);

export type ActionPlan = {
  /** Главное действие по состоянию лида (кнопка primary) или `null`. */
  primary: ActionKey | null;
  /** Остальные доступные действия — в меню «Ещё». */
  more: ActionKey[];
  /** Лида ведёт другой человек — один баннер вместо серых кнопок. */
  ownerBanner: { name: string; hint: boolean } | null;
};

const ownerName = (lead: LeadDetail): string => lead.assigned_user_name ?? ownerModeLabel("human");

/** Лида ведёт другой человек (не я) — независимо от роли. */
const ownedByOther = (lead: LeadDetail, rights: ActionRights): boolean =>
  lead.owner_mode === "human" && lead.assigned_user_id !== rights.userId;

/** Ведёт ли лида другой человек, а я не админ — тогда владельческие действия недоступны. */
function foreign(lead: LeadDetail, rights: ActionRights): boolean {
  return ownedByOther(lead, rights) && !rights.isAdmin;
}

/** Открытая или отложенная передача. */
const pending = (lead: LeadDetail): boolean =>
  lead.escalation?.status === "open" || lead.escalation?.status === "snoozed";

/** Зеркало `may_acknowledge` (domain/lead_access.py): информационная передача, открытая/отложенная. */
const infoPending = (lead: LeadDetail): boolean =>
  lead.escalation?.priority === "info" && pending(lead);

/** Зеркало `may_make_customer` (domain/lead_access.py): ответственный или админ, без него — любой. */
const mayMakeCustomer = (lead: LeadDetail, rights: ActionRights): boolean => {
  const allowed =
    lead.backoffice_mode === "erp"
      ? lead.stage === "in_progress" || lead.stage === "won" || lead.stage === "customer"
      : lead.stage === "won" || lead.stage === "customer";
  return (
    allowed &&
    (rights.isAdmin || lead.assigned_user_id === null || lead.assigned_user_id === rights.userId)
  );
};

/**
 * Передача клиента лида в бэк-офис (FIX-34b, Q-FIX34-1). Только режим `erp`, лид в стадии
 * `customer` с клиентом, которого ещё нет в ERP (стал клиентом в режиме `local`):
 * `available` — передачи нет, можно передать; `pending` — идёт; `failed` — не удалась (повтор
 * в карточке состояния); `none` — показывать нечего.
 */
export type ClientHandoff = "none" | "available" | "pending" | "failed";

export function clientHandoff(lead: LeadDetail): ClientHandoff {
  const applies =
    lead.backoffice_mode === "erp" &&
    lead.stage === "customer" &&
    lead.client_id != null &&
    !lead.client_in_erp;
  if (!applies) return "none";
  if (lead.client_handoff_status === "pending") return "pending";
  if (lead.client_handoff_status === "failed") return "failed";
  return "available";
}

/** Может ли пользователь передавать клиента лида (те же права, что у «Сделать клиентом»). */
export const mayHandoffClient = (lead: LeadDetail, rights: ActionRights): boolean =>
  Boolean(rights.clients) && mayMakeCustomer(lead, rights);

/** Зеркало `may_snooze` (Q-018): общая очередь; у лида есть ответственный — только он или админ. */
const maySnooze = (lead: LeadDetail, rights: ActionRights): boolean =>
  lead.assigned_user_id === null || lead.assigned_user_id === rights.userId || rights.isAdmin;

/** Ждёт ли лид менеджера: открытая передача или бот на паузе. */
const waitsForManager = (lead: LeadDetail): boolean =>
  lead.escalation?.status === "open" || lead.owner_mode === "paused";

/** Доступность каждого действия (UI; права всё равно проверит бэкенд). */
export function availableActions(
  lead: LeadDetail,
  rights: ActionRights,
): Record<ActionKey, boolean> {
  const mine = lead.owner_mode === "human" && lead.assigned_user_id === rights.userId;
  const human = lead.owner_mode === "human";
  const other = ownedByOther(lead, rights);
  const canOwn = !foreign(lead, rights);
  const responsible = lead.assigned_user_id;
  const isErp = lead.backoffice_mode === "erp";
  return {
    // Аудит P0-1: информационную передачу лида у бота закрывают без «Забрать» → «Вернуть боту».
    acknowledge: rights.take && infoPending(lead) && lead.owner_mode !== "human",
    // «Забрать» и из «Отказа»: вернувшегося лида снова берут в работу (ADR-0015).
    take: rights.take && !mine && !other,
    takeOver: rights.take && rights.isAdmin && other && responsible !== null,
    // В режиме ERP «Сделка заключена» решает бэк-офис (deal.won)
    won: rights.work && lead.stage === "in_progress" && canOwn && !isErp,
    lost: rights.work && lead.stage === "in_progress" && canOwn,
    // Q-018: общая очередь; у лида есть ответственный — только он или админ.
    snooze: rights.take && pending(lead) && maySnooze(lead, rights),
    // «Вернуть из отложенных»: те же права, что у «Отложить» (POST …/actions/unsnooze).
    unsnooze: rights.take && lead.escalation?.status === "snoozed" && maySnooze(lead, rights),
    returnToBot: rights.work && lead.owner_mode !== "bot" && canOwn,
    assign: rights.work && human && canOwn,
    newDeal: rights.work && lead.stage === "customer" && !human,
    makeCustomer:
      mayHandoffClient(lead, rights) &&
      (clientHandoff(lead) === "available" ||
        (isErp ? lead.stage === "in_progress" || lead.stage === "won" : lead.stage === "won")),
    note: rights.note,
  };
}

/** Главное действие: свой лид в работе → «Закрыть сделкой», ждёт менеджера → «Забрать». */
function primaryAction(
  lead: LeadDetail,
  rights: ActionRights,
  can: Record<ActionKey, boolean>,
): ActionKey | null {
  if (ownedByOther(lead, rights)) return null;
  if (can.acknowledge) return "acknowledge";
  if (can.makeCustomer) return "makeCustomer";
  if (can.won) return "won";
  if (can.take && waitsForManager(lead)) return "take";
  if (can.newDeal) return "newDeal";
  return null;
}

/** План панели действий: primary, «Ещё» и баннер «Лида ведёт …». */
export function leadActionPlan(lead: LeadDetail, rights: ActionRights): ActionPlan {
  const can = availableActions(lead, rights);
  const primary = primaryAction(lead, rights, can);
  const more = ACTION_ORDER.filter((key) => can[key] && key !== primary);
  const other = ownedByOther(lead, rights);
  return {
    primary,
    more,
    ownerBanner: other ? { name: ownerName(lead), hint: !rights.isAdmin } : null,
  };
}

/** Может ли пользователь ответить лиду, а если нет — понятная причина под чатом. */
export function replyState(lead: LeadDetail, rights: ActionRights): { can: boolean; hint: string } {
  if (!rights.reply) return { can: false, hint: t.why.replyViewer };
  if (foreign(lead, rights)) {
    return { can: false, hint: t.why.replyOther.replace("{name}", ownerName(lead)) };
  }
  if (lead.owner_mode !== "human") {
    const can = availableActions(lead, rights);
    return { can: false, hint: can.take ? t.why.replyTake : t.why.replyBot };
  }
  return { can: true, hint: "" };
}
