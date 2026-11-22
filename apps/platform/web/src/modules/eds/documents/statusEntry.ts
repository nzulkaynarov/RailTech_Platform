import type { EdsRegistryKind } from "../../../shared/api/generated/model";
import type { StatusKind } from "../../../shared/lib/statuses";

/**
 * Статус документа EDS словами SPEC-v3 §2.4: вид карты цвета (`STATUS_TONE`, UX-2b) и ключ слова. Цвет здесь не задаётся —
 * его даёт общая карта по виду и коду.
 */
const DOCUMENT: Record<string, string> = {
  draft: "documents:status.draft",
  on_approval: "dictionary:status.memo.pending",
  returned: "dictionary:status.memo.returned",
  rejected: "dictionary:status.memo.rejected",
  approved: "dictionary:status.memo.approved",
  to_accountant: "dictionary:status.memo.passed_to_accountant",
  paid: "dictionary:status.memo.paid",
  sent: "documents:status.sent",
};

const LETTER_IN: Record<string, string> = {
  awaiting_resolution: "dictionary:status.incoming.awaiting_resolution",
  resolved: "dictionary:status.incoming.resolved",
  returned: "dictionary:status.incoming.returned",
  rejected: "dictionary:status.incoming.rejected",
  in_execution: "dictionary:status.incoming.in_execution",
  executed: "dictionary:status.incoming.executed",
  noted: "dictionary:status.incoming.noted",
  duplicate: "dictionary:status.incoming.duplicate",
  closed: "dictionary:status.incoming.closed",
};

const QUOTE: Record<string, string> = {
  open: "documents:status.quote.open",
  approved: "documents:status.quote.approved",
  returned: "documents:status.quote.returned",
  rejected: "documents:status.quote.rejected",
};

/**
 * `awaitingSignature` (СЦ-8) — факт EDS: письмо передано на подпись и не подписано. Статус при этом `draft`, а слово
 * «На подписи»; `code` — код цвета в общей карте (как у служебки «ждёт действия»), по умолчанию — сам статус.
 */
export function statusEntry(
  kind: EdsRegistryKind,
  status: string,
  awaitingSignature = false,
): { kind: StatusKind; key: string | undefined; code: string } {
  if (kind === "letter_out" && status === "draft" && awaitingSignature) {
    return { kind: "memo", key: "documents:status.signing", code: "signing" };
  }
  if (kind === "letter_in") return { kind: "incoming", key: LETTER_IN[status], code: status };
  if (kind === "quote") return { kind: "quote", key: QUOTE[status], code: status };
  return { kind: "memo", key: DOCUMENT[status], code: status };
}
