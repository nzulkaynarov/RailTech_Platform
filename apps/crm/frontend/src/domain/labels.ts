/**
 * Единый источник меток для кодов с бэкенда: стадии, режимы, приоритеты, статусы,
 * действия аудита, ключи квалификации, причины переходов. Компоненты не показывают
 * сырые коды — только через эти функции (аудит UI U-01, U-07).
 */
import { t } from "../i18n/ru";

export type Label = { label: string; color: string };

const L = t.labels;

export const STAGE_ORDER = [
  "new",
  "engaged",
  "qualified",
  "handoff",
  "in_progress",
  "won",
  "customer",
  "lost",
  "unresponsive",
] as const;

const STAGE_COLOR: Record<string, string> = {
  new: "default",
  engaged: "blue",
  qualified: "geekblue",
  handoff: "orange",
  in_progress: "purple",
  won: "green",
  customer: "cyan",
  lost: "red",
  unresponsive: "default",
};
const PRIORITY_COLOR: Record<string, string> = { hot: "red", warm: "orange", info: "blue" };
const INGEST_COLOR: Record<string, string> = {
  pending: "default",
  processing: "processing",
  done: "success",
  failed: "error",
};
const REQUEST_COLOR: Record<string, string> = { open: "orange", closed: "default" };

const pick = (dict: Record<string, string>, code: string): string => dict[code] ?? code;

export const stageLabel = (code: string): Label => ({
  label: pick(L.stage, code),
  color: STAGE_COLOR[code] ?? "default",
});
export const stageOptions = () => STAGE_ORDER.map((v) => ({ value: v, label: pick(L.stage, v) }));
export const priorityLabel = (code: string): Label => ({
  label: pick(t.priority, code),
  color: PRIORITY_COLOR[code] ?? "default",
});
export const reasonLabel = (code: string): string => pick(t.reasons, code);
export const ownerModeLabel = (code: string): string => pick(t.owner, code);
export const ingestLabel = (code: string): Label => ({
  label: pick(L.ingest, code),
  color: INGEST_COLOR[code] ?? "default",
});
export const serviceRequestLabel = (code: string): Label => ({
  label: pick(L.serviceRequest, code),
  color: REQUEST_COLOR[code] ?? "default",
});
export const roleLabel = (code: string): string => pick(t.roles, code);

export const LANGUAGES = ["ru", "uz", "en"] as const;
export const languageLabel = (code: string): string => pick(L.language, code.toLowerCase());
export const languageOptions = () =>
  LANGUAGES.map((v) => ({
    value: v,
    label: `${pick(L.language, v)} · ${pick(L.languageName, v)}`,
  }));

export const auditActionLabel = (code: string): string => pick(L.auditAction, code);
export const entityLabel = (code: string): string => pick(L.entity, code);
export const ENTITY_TYPES = Object.keys(L.entity);
export const actorLabel = (code: string): string => pick(L.actor, code);

export const QUALIFICATION_KEYS = [
  "company",
  "company_size",
  "region",
  "timeline",
  "decision_role",
  "budget_hint",
] as const;
export const qualificationText = (key: string, value: unknown): string =>
  `${pick(L.qualification, key)}: ${pick(L.qualificationValue, String(value))}`;

export const sourceLabel = (code: string): string => pick(L.source, code);

/** Причина перехода стадии — бэкенд пишет её по-английски или текстом сотрудника. */
export function transitionReason(reason: string | null | undefined): string {
  if (!reason) return "";
  const known = L.transition[reason];
  if (known) return known;
  const days = /^no reply for (\d+) days$/.exec(reason);
  if (days) return (L.transition["noReply"] ?? "").replace("{days}", days[1] ?? "");
  if (reason.startsWith("qualifier: ")) {
    return (L.transition["qualifier"] ?? "").replace("{text}", reason.slice("qualifier: ".length));
  }
  return reason;
}

/** Отказ квалификатору (служебный текст бэкенда) — человеку достаточно сути. */
export function rejectedReason(reason: string | null | undefined): string {
  if (!reason) return "";
  return /not allowed|may only|may not/.test(reason)
    ? (L.transition["ruleRejected"] ?? reason)
    : reason;
}
