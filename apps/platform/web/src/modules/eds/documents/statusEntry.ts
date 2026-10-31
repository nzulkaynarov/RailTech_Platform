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
};

const QUOTE: Record<string, string> = {
  open: "documents:status.quote.open",
  approved: "documents:status.quote.approved",
  returned: "documents:status.quote.returned",
  rejected: "documents:status.quote.rejected",
};

export function statusEntry(
  kind: EdsRegistryKind,
  status: string,
): { kind: StatusKind; key: string | undefined } {
  if (kind === "letter_in") return { kind: "incoming", key: LETTER_IN[status] };
  if (kind === "quote") return { kind: "quote", key: QUOTE[status] };
  return { kind: "memo", key: DOCUMENT[status] };
}
