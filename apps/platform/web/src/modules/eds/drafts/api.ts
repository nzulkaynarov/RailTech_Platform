const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** КП в адресе API: UUID маршрута как есть, бизнес-номер `КП-2026/115` — закодированным (в номере есть «/»). */
export function quoteRef(idOrNumber: string): string {
  return UUID.test(idOrNumber) ? idOrNumber.toLowerCase() : encodeURIComponent(idOrNumber);
}

/** Путь карточки КП в SPA: бизнес-номер, а не внутренний id (SPEC-v3 §2.2). */
export function quotePath(number: string): string {
  return `/eds/drafts/${encodeURIComponent(number)}`;
}

export type Scope = "mine" | "all";

export function scopeOf(value: string | null, fallback: Scope): Scope {
  return value === "mine" || value === "all" ? value : fallback;
}
