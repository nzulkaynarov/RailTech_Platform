const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** КП в адресе API: UUID маршрута как есть, бизнес-номер `КП-2026/115` — закодированным (в номере есть «/»). */
export function quoteRef(idOrNumber: string): string {
  return UUID.test(idOrNumber) ? idOrNumber.toLowerCase() : encodeURIComponent(idOrNumber);
}

/**
 * Путь карточки КП в SPA из строки списка и окна: по id маршрута — он однозначен (у номера несколько версий). Адрес по номеру
 * `КП-2026/115` тоже открывает карточку (ссылки из писем и очереди).
 */
export function quotePath(ref: string): string {
  return `/eds/drafts/${encodeURIComponent(ref)}`;
}

export type Scope = "mine" | "all";

export function scopeOf(value: string | null, fallback: Scope): Scope {
  return value === "mine" || value === "all" ? value : fallback;
}
