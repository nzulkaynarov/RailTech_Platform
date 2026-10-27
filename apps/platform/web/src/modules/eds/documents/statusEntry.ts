import type { EdsRegistryKind } from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";

/** Статус документа EDS словами SPEC-v3 §2.4 (слова — словарь `dictionary:status.memo.*`) и цветом. */
const DOCUMENT: Record<string, { tone: StatusTone; key: string }> = {
  draft: { tone: "default", key: "documents:status.draft" },
  on_approval: { tone: "gold", key: "dictionary:status.memo.pending" },
  returned: { tone: "gold", key: "dictionary:status.memo.returned" },
  rejected: { tone: "red", key: "dictionary:status.memo.rejected" },
  approved: { tone: "green", key: "dictionary:status.memo.approved" },
  to_accountant: { tone: "blue", key: "dictionary:status.memo.passed_to_accountant" },
  paid: { tone: "green", key: "dictionary:status.memo.paid" },
  sent: { tone: "blue", key: "documents:status.sent" },
};

const LETTER_IN: Record<string, { tone: StatusTone; key: string }> = {
  awaiting_resolution: { tone: "gold", key: "dictionary:status.incoming.awaiting_resolution" },
  resolved: { tone: "green", key: "dictionary:status.incoming.resolved" },
  returned: { tone: "gold", key: "dictionary:status.incoming.returned" },
  rejected: { tone: "red", key: "dictionary:status.incoming.rejected" },
};

const QUOTE: Record<string, { tone: StatusTone; key: string }> = {
  open: { tone: "gold", key: "documents:status.quote.open" },
  approved: { tone: "green", key: "documents:status.quote.approved" },
  returned: { tone: "gold", key: "documents:status.quote.returned" },
  rejected: { tone: "red", key: "documents:status.quote.rejected" },
};

export function statusEntry(
  kind: EdsRegistryKind,
  status: string,
): { tone: StatusTone; key: string } | undefined {
  const table = kind === "letter_in" ? LETTER_IN : kind === "quote" ? QUOTE : DOCUMENT;
  return table[status];
}
