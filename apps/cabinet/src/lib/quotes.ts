import type { QuoteListItem } from '@/api/portal';
import { businessToday } from './format';
import { isQuoteOpen } from './status';

/**
 * Срок действия КП по календарю Ташкента: КП в статусе «ждёт решения» с прошедшей датой `valid_until`
 * клиенту уже не принять (ERP ответит 409) — кнопки прячем заранее и объясняем почему.
 */
export function quoteExpired(quote: Pick<QuoteListItem, 'status' | 'valid_until'>, now: number): boolean {
  if (quote.status === 'expired') return true;
  return isQuoteOpen(quote.status) && Boolean(quote.valid_until) && (quote.valid_until as string) < businessToday(now);
}

/** Ждёт решения клиента: открыто и не истекло. */
export function quoteAwaitsDecision(quote: Pick<QuoteListItem, 'status' | 'valid_until'>, now: number): boolean {
  return isQuoteOpen(quote.status) && !quoteExpired(quote, now);
}

/** Код акцепта по контракту — 4…12 символов; пробелы по краям (вставка из сообщения) убираем. */
export const ACCEPT_CODE_MIN = 4;
export const ACCEPT_CODE_MAX = 12;
export function normalizeAcceptCode(value: string): string {
  return value.replace(/\s+/g, '');
}
