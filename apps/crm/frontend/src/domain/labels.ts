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
const OWNER_COLOR: Record<string, string> = { paused: "orange" };

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
export const ownerModeTag = (code: string): Label => ({
  label: ownerModeLabel(code),
  color: OWNER_COLOR[code] ?? "default",
});
/** Флаг «Новое сообщение» во «Входящих». */
export const unreadLabel = (): Label => ({ label: t.inbox.unread, color: "orange" });
/** Цвет таймера ожидания передачи по уровню срока реакции (`domain/sla.ts`). */
const SLA_COLOR: Record<string, string> = {
  ok: "green",
  warning: "orange",
  overdue: "red",
  snoozed: "default",
};
export const slaColor = (level: string): string => SLA_COLOR[level] ?? "default";
/** Цвет точки на ленте «Почему система так решила»: переход, передача, обычный прогон. */
export const decisionColor = (kind: string, escalated: boolean): string =>
  kind === "transition" ? "blue" : escalated ? "red" : "gray";
/**
 * Ошибка прогона квалификатора словами. API отдаёт `Класс: текст` исключения — менеджеру
 * это не нужно; сырой текст остаётся в `title` для админа.
 */
export const decisionErrorLabel = (error: string): string =>
  error.startsWith("LlmUnavailableError") ? t.lead.modelUnavailable : t.lead.decisionFailed;
/** Продукт, которым интересуется лид (ключ каталога KB). */
export const productLabel = (key: string): Label => ({ label: key, color: "blue" });
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

/** Похоже на служебный код (`price_or_contract_asked`), а не на текст для человека. */
export const looksLikeCode = (text: string): boolean => /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/.test(text);

const isReasonCode = (part: string): boolean => part in t.reasons || looksLikeCode(part);

/** Список кодов причин передачи через запятую («price_or_contract_asked, high_score»). */
function reasonCodes(reason: string): string | null {
  const codes = reason.split(",").map((part) => part.trim());
  if (!codes.every(isReasonCode)) return null;
  const unknown = L.transition["unknownCode"] ?? "";
  return codes.map((code) => (code in t.reasons ? reasonLabel(code) : unknown)).join("; ");
}

/** Причина перехода стадии — бэкенд пишет её по-английски, кодами триггеров или текстом сотрудника. */
export function transitionReason(reason: string | null | undefined): string {
  if (!reason) return "";
  const known = L.transition[reason];
  if (known) return known;
  const days = /^no reply for (\d+) days$/.exec(reason);
  if (days) return (L.transition["noReply"] ?? "").replace("{days}", days[1] ?? "");
  if (reason.startsWith("qualifier: ")) {
    const text = reason.slice("qualifier: ".length).trim();
    if (!text || looksLikeCode(text)) return L.transition["qualifierOnly"] ?? "";
    return (L.transition["qualifier"] ?? "").replace("{text}", text);
  }
  return reasonCodes(reason) ?? reason;
}

/** Отказ квалификатору (служебный текст бэкенда) — человеку достаточно сути. */
export function rejectedReason(reason: string | null | undefined): string {
  if (!reason) return "";
  return /not allowed|may only|may not/.test(reason)
    ? (L.transition["ruleRejected"] ?? reason)
    : reason;
}
