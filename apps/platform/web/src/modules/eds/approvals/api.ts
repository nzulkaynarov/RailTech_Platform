const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Документ в адресе API: UUID как есть, бизнес-номер `СЗ-2026/014` — закодированным (в номере есть «/»). */
export function memoRef(idOrNumber: string): string {
  return UUID.test(idOrNumber) ? idOrNumber.toLowerCase() : encodeURIComponent(idOrNumber);
}

/** Путь карточки документа в SPA: бизнес-номер, а при его отсутствии — id документа. */
export function memoPath(row: { number: string | null; id: string }): string {
  return `/eds/approvals/${encodeURIComponent(row.number ?? row.id)}`;
}
