import { ApiError } from "../../../shared/api/errors";
import { APPROVAL_KEYS, useInvalidatePrefixes } from "../refreshKeys";

/** Причина отказа решения словарным ключом (`<ns>:form.reasons.<ключ>`). */
export type DecisionReason =
  | "route_closed"
  | "checklist_not_green"
  | "not_your_step"
  | "eds_not_granted"
  | "forbidden"
  | "unavailable"
  | "validation"
  | "unknown";

const KNOWN: ReadonlySet<string> = new Set<DecisionReason>([
  "route_closed",
  "checklist_not_green",
  "not_your_step",
  "eds_not_granted",
]);

/** Подкод EDS (`details.reason`), иначе причина по статусу ответа; сеть оборвалась до ответа — «недоступно». */
export function decisionReason(error: unknown): DecisionReason {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && KNOWN.has(reason)) return reason as DecisionReason;
    if (error.status === 403) return "forbidden";
    if (error.status === 409) return "route_closed";
    if (error.status === 422) return "validation";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  return error instanceof TypeError ? "unavailable" : "unknown";
}

/** Коды красных блокирующих строк чек-листа из 409 `checklist_not_green` (`details.failed`). */
export function failedCodes(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const failed = error.details["failed"];
  return Array.isArray(failed) ? failed.filter((c): c is string => typeof c === "string") : [];
}

/** Решение уже принято или не принимается (409, 403 «не ваш шаг»): введённое больше не нужно, карточку надо обновить. */
export function isTerminal(error: unknown): boolean {
  const reason = decisionReason(error);
  return reason === "route_closed" || reason === "not_your_step";
}

/** После решения сбрасываются списки и карточки КП и служебок, реестр документов, очередь и счётчики (`APPROVAL_KEYS`). */
export function useRefreshApprovals(): () => Promise<void> {
  return useInvalidatePrefixes(APPROVAL_KEYS);
}
