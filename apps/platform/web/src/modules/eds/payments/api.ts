import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "../../../shared/api/errors";

/** Все запросы разделов: счета и служебки начинаются с этих префиксов ключа (orval). */
const KEYS = ["/api/v1/eds/payments", "/api/v1/eds/payment-memos"] as const;

/** После подтверждения, платёжки или «Оплачено» сбрасываются списки и карточки: статус и счётчики меняются везде. */
export function useRefreshPayments(): () => Promise<void> {
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

export function errorReason(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  const reason = error.details["reason"];
  return typeof reason === "string" ? reason : undefined;
}

/** Первая причина по полю из `details.messages` EDS (`exceeds_approved`, `in_future`) — ключом словаря. */
export function fieldMessage(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  const messages = error.details["messages"];
  if (messages && typeof messages === "object") {
    const first = Object.entries(messages as Record<string, unknown>)[0];
    if (first && typeof first[1] === "string") return `${first[0]}_${first[1]}`;
  }
  return undefined;
}

export type InvoiceReason =
  | "exceeds_balance"
  | "already_paid"
  | "not_issued"
  | "not_open"
  | "cancelled"
  | "reference_conflict"
  | "forbidden"
  | "unavailable"
  | "validation"
  | "not_found"
  | "unknown";

const INVOICE_KNOWN: ReadonlySet<string> = new Set([
  "exceeds_balance",
  "already_paid",
  "not_issued",
  "not_open",
  "cancelled",
  "reference_conflict",
]);

/** Причина отказа ERP словарным ключом: подкод `details.reason`, иначе — по статусу ответа. */
export function invoiceReason(error: unknown): InvoiceReason {
  if (error instanceof ApiError) {
    const reason = errorReason(error);
    if (reason && INVOICE_KNOWN.has(reason)) return reason as InvoiceReason;
    if (error.status === 403) return "forbidden";
    if (error.status === 404) return "not_found";
    if (error.status === 422) return "validation";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  return error instanceof TypeError ? "unavailable" : "unknown";
}

/** Отказ означает «карточка устарела»: введённое бесполезно, нужно обновить данные. */
export function isStale(reason: InvoiceReason): boolean {
  return ["already_paid", "not_open", "not_issued", "cancelled", "not_found"].includes(reason);
}

export type MemoReason =
  | "amount_exceeds_approved"
  | "amount_currency_mismatch"
  | "amount_must_be_positive"
  | "paid_on_in_future"
  | "already_paid"
  | "invalid_state"
  | "route_closed"
  | "not_your_step"
  | "forbidden"
  | "unavailable"
  | "validation"
  | "unknown";

const MEMO_KNOWN: ReadonlySet<string> = new Set([
  "already_paid",
  "invalid_state",
  "route_closed",
  "not_your_step",
]);

export function memoReason(error: unknown): MemoReason {
  if (error instanceof ApiError) {
    const field = fieldMessage(error);
    if (
      field &&
      [
        "amount_exceeds_approved",
        "amount_currency_mismatch",
        "amount_must_be_positive",
        "paid_on_in_future",
      ].includes(field)
    ) {
      return field as MemoReason;
    }
    const reason = errorReason(error);
    if (reason && MEMO_KNOWN.has(reason)) return reason as MemoReason;
    if (error.status === 403) return "forbidden";
    if (error.status === 422) return "validation";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  return error instanceof TypeError ? "unavailable" : "unknown";
}

export function isMemoStale(reason: MemoReason): boolean {
  return ["already_paid", "invalid_state", "route_closed", "not_your_step"].includes(reason);
}
