/**
 * Срок реакции на передачу (SLA) во «Входящих»: сколько лид ждёт и насколько это близко
 * к сроку. Срок считает бэкенд (`escalation.sla_due_at` — рабочие минуты из настроек
 * эскалации, Asia/Tashkent); здесь только сравнение с текущим временем и порядок очереди.
 */
import type { EscalationOut, InboxResponse, LeadOut } from "../api/generated/model";
import { t } from "../i18n/ru";

/** Срок по умолчанию, если бэкенд не прислал `sla_due_at` (= `EscalationSettings.sla_minutes`). */
export const DEFAULT_SLA_MINUTES = 15;
/** С какой доли срока передача считается «скоро просрочится» (оранжевый). */
export const SLA_WARNING_SHARE = 0.8;
/**
 * Окно, от которого берётся доля, не длиннее часа: передача вне рабочих часов получает
 * срок «утром», и без ограничения она краснела бы с ночи. Итог — предупреждение не раньше
 * чем за 12 минут до срока; при SLA 15 мин — ровно с 80 % срока.
 */
export const SLA_WARNING_WINDOW_CAP_MINUTES = 60;

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export type SlaLevel = "ok" | "warning" | "overdue" | "snoozed";

export type SlaState = {
  level: SlaLevel;
  /** Сколько ждёт с момента передачи, мс. */
  waitingMs: number;
  since: Date;
  dueAt: Date;
  snoozedUntil: Date | null;
};

type SlaEscalation = Pick<EscalationOut, "created_at" | "sla_due_at" | "status" | "snoozed_until">;

/** Передача ещё ждёт реакции (открыта или отложена) — для неё показывают таймер. */
export const isWaiting = (escalation: Pick<EscalationOut, "status"> | null | undefined): boolean =>
  escalation?.status === "open" || escalation?.status === "snoozed";

/** Состояние срока реакции на момент `now`. */
export function slaState(escalation: SlaEscalation, now: Date): SlaState {
  const since = new Date(escalation.created_at);
  const dueAt = escalation.sla_due_at
    ? new Date(escalation.sla_due_at)
    : new Date(since.getTime() + DEFAULT_SLA_MINUTES * MINUTE);
  const snoozedUntil = escalation.snoozed_until ? new Date(escalation.snoozed_until) : null;
  const waitingMs = Math.max(0, now.getTime() - since.getTime());
  const window = Math.min(
    Math.max(1, dueAt.getTime() - since.getTime()),
    SLA_WARNING_WINDOW_CAP_MINUTES * MINUTE,
  );
  const remaining = dueAt.getTime() - now.getTime();
  let level: SlaLevel = "ok";
  if (escalation.status === "snoozed" && snoozedUntil && snoozedUntil > now) level = "snoozed";
  else if (remaining <= 0) level = "overdue";
  else if (remaining <= Math.round(window * (1 - SLA_WARNING_SHARE))) level = "warning";
  return { level, waitingMs, since, dueAt, snoozedUntil };
}

/** Длительность ожидания коротко: «< 1 мин», «12 мин», «1 ч 5 мин», «2 д 3 ч». */
export function formatWait(ms: number): string {
  const d = t.inbox.duration;
  if (ms < MINUTE) return d.lessMinute;
  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  const part = (template: string, key: string, n: number) => template.replace(key, String(n));
  if (days) {
    const head = part(d.days, "{d}", days);
    return hours ? `${head} ${part(d.hours, "{h}", hours)}` : head;
  }
  if (hours) {
    const head = part(d.hours, "{h}", hours);
    return minutes ? `${head} ${part(d.minutes, "{m}", minutes)}` : head;
  }
  return part(d.minutes, "{m}", minutes);
}

const PRIORITY_RANK: Record<string, number> = { hot: 0, warm: 1, info: 2 };
const rank = (lead: LeadOut): number => {
  const e = lead.escalation;
  if (!e) return 9;
  const snoozed = e.status === "snoozed" ? 5 : 0;
  return snoozed + (PRIORITY_RANK[e.priority] ?? 3);
};

/** Очередь передач: приоритет (горячие первыми), отложенные — в конце, дольше ждущие — выше. */
export function sortHandoffs(leads: readonly LeadOut[]): LeadOut[] {
  const since = (lead: LeadOut) =>
    lead.escalation ? new Date(lead.escalation.created_at).getTime() : Number.MAX_SAFE_INTEGER;
  return [...leads].sort((a, b) => rank(a) - rank(b) || since(a) - since(b) || a.id - b.id);
}

/** Сколько передач ждут реакции (для счётчика в меню): открытые, без отложенных. */
export function openHandoffCount(inbox: Pick<InboxResponse, "escalations"> | undefined): number {
  return (inbox?.escalations ?? []).filter((lead) => lead.escalation?.status === "open").length;
}
