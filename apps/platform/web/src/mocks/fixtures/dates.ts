import { companyToday } from "../../shared/lib/dates";

/**
 * Даты фикстур, которые проходят проверку «срок не в прошлом» (форма документа, резолюция): считаются от «сегодня
 * компании» (`Asia/Tashkent`), а не зашиты календарём — иначе сценарий «Доработать» краснеет, когда зашитый срок
 * остаётся позади (main красный с 2026-11-01).
 */

/** День через `days` суток от «сегодня компании», `YYYY-MM-DD`. */
export function companyDayIn(days: number, now: Date = new Date()): string {
  const [y, m, d] = companyToday(now).split("-").map(Number);
  const shifted = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
  return shifted.toISOString().slice(0, 10);
}
