import type { TFunction } from "i18next";

const TRANSFER_ERRORS = new Set([
  "erp_unavailable",
  "erp_request_conflict",
  "handoff_no_consent",
  "erp_inn_conflict",
  "enqueue_failed",
]);

/** Причина ошибки передачи в бэк-офис словами; неизвестный код CRM — «причина не определена», без сырого кода. */
export function transferReason(t: TFunction, code: string | null): string {
  return t(`clients:transferErrors.${code && TRANSFER_ERRORS.has(code) ? code : "other"}`);
}
