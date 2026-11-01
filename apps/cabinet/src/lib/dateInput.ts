/** Ввод даты `ДД.ММ.ГГГГ` для `components/DateField` (B-CABFIX-1): маска и перевод в ключ `YYYY-MM-DD` и обратно. */
const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** `2026-10-14` → `14.10.2026`; пусто или не ключ — пустая строка. */
export function isoToText(value: string | null | undefined): string {
  const match = value ? ISO_DAY.exec(value) : null;
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

/** Маска ввода: только цифры, точки после дня и месяца ставятся сами (`14102026` → `14.10.2026`). */
export function maskDate(text: string): string {
  const digits = text.replace(/\D/g, '').slice(0, 8);
  const parts = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean);
  return parts.join('.');
}

/** `ДД.ММ.ГГГГ` → ключ `YYYY-MM-DD`; пусто — `''`; неполная или несуществующая дата (31.02) — `null`. */
export function textToIso(text: string): string | null {
  if (!text) return '';
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text);
  if (!match) return null;
  const [, day, month, year] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  const ok = date.getUTCFullYear() === Number(year) && date.getUTCMonth() === Number(month) - 1 && date.getUTCDate() === Number(day);
  return ok ? `${year}-${month}-${day}` : null;
}
