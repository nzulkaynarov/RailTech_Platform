import type { Employee, EmployeeStatus } from "../../shared/api/generated/model";

/** Хоть у кого-то доступ в ERP ещё выдаётся: список перечитывается, пока ERP не ответит. */
export function anyErpPending(items: readonly Employee[] | undefined): boolean {
  return (items ?? []).some((employee) => erpAttention(employee) === "pending");
}

export const EMPLOYEE_STATUSES: readonly EmployeeStatus[] = ["active", "invited", "disabled"];

/** Итог провижининга ERP, о котором стоит сказать словом: «ок» и «не требуется» отдельной метки не получают.
 *  У отключённого про выдачу доступа — ничего: отзыв сессий не «выдаётся» (СЦ-8). */
export function erpAttention(
  employee: Pick<Employee, "access" | "erp_sync" | "status">,
): "pending" | "error" | null {
  if (!employee.access.erp || employee.status === "disabled") return null;
  return employee.erp_sync === "pending" || employee.erp_sync === "error"
    ? employee.erp_sync
    : null;
}

export type ErpSyncReason = "not_connected" | "unavailable" | "queue" | "rejected";

/** CRM codes (`Reason.*`) that only an administrator fixes in Connections: no address, wrong token or URL. */
const NOT_CONNECTED_CODES = new Set(["erp_not_configured", "erp_unauthorized", "erp_invalid_url"]);
/** CRM codes of a failure that goes away on its own: ERP down, rate limit, HTTP-client exception names. */
const TRANSIENT_CODES = new Set(["erp_unavailable", "erp_rate_limited"]);
/** Python/httpx exception names CRM writes as the code when the failure carries no reason (`ConnectError`, …). */
const EXCEPTION_NAME = /^[A-Z][A-Za-z]*(Error|Exception|Timeout)$/;
/** `enqueue_sync` writes `<action>: задача не поставлена в очередь` — no code, nothing retries it. */
const QUEUE_FAILURE = "задача не поставлена в очередь";

/**
 * Human reason of a failed ERP provisioning from `erp_sync_error` (CRM writes `task: code: detail`, 500 chars max).
 * The text itself is never shown: the code decides the sentence. `null` — CRM has no error text ("не выдан", no job).
 * `erp_bad_response` is ambiguous (422 refusal vs 5xx): the `HTTP 5xx` in the detail tells a server failure.
 */
export function erpSyncReason(error: string | undefined | null): ErpSyncReason | null {
  if (!error) return null;
  const [, code = "", ...rest] = error.split(": ");
  const trimmed = code.trim();
  if (trimmed === QUEUE_FAILURE) return "queue";
  if (NOT_CONNECTED_CODES.has(trimmed)) return "not_connected";
  if (TRANSIENT_CODES.has(trimmed) || EXCEPTION_NAME.test(trimmed)) return "unavailable";
  if (trimmed === "erp_bad_response" && /HTTP 5\d\d/.test(rest.join(": "))) return "unavailable";
  return "rejected";
}
