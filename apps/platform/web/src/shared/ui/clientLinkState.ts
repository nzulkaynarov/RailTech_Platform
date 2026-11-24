export type ClientLinkKind =
  "quote" | "contract" | "invoice" | "act" | "price_request" | "supplier_order";
export type ClientLinkState = "none" | "active" | "revoked" | "expired" | "superseded";

/** Одна ссылка получателя: адрес замаскирован ERP, «открыто» — факт, а не статус. */
export interface ClientLinkRow {
  key: string;
  hint: string | null;
  sentAt?: string | null;
  openedAt: string | null;
  state?: ClientLinkState;
}

/** Общее состояние по ссылкам документа: живая есть — «действует», иначе причина самой свежей (замена, срок, отзыв). */
export function summarizeLinks(
  rows: readonly ClientLinkRow[],
  expiries: readonly (string | null | undefined)[],
): { state: ClientLinkState; expiresAt: string | null } {
  if (rows.length === 0) return { state: "none", expiresAt: null };
  const live = rows.some((row) => row.state === "active");
  if (live) {
    const dates = expiries.filter((value): value is string => Boolean(value)).sort();
    return { state: "active", expiresAt: dates.length ? (dates[dates.length - 1] ?? null) : null };
  }
  const states = rows.map((row) => row.state);
  const state = states.includes("superseded")
    ? "superseded"
    : states.includes("expired")
      ? "expired"
      : "revoked";
  return { state, expiresAt: null };
}
