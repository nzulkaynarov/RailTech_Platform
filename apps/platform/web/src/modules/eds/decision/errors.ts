import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "../../../shared/api/errors";

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

/** После решения сбрасываются списки и карточки КП и документов: статус и очереди меняются везде. */
const KEYS = ["/api/v1/eds/quotes", "/api/v1/eds/memo-approvals"] as const;

export function useRefreshApprovals(): () => Promise<void> {
  const client = useQueryClient();
  return useCallback(
    () =>
      client.invalidateQueries({
        predicate: (query) => {
          const head = query.queryKey[0];
          return typeof head === "string" && KEYS.some((key) => head.startsWith(key));
        },
      }),
    [client],
  );
}
