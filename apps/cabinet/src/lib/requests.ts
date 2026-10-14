import type { ClientRequest } from '@/api/portal';

/** Предзаполнение «Нового запроса» из карточки каталога (state маршрута `/requests/new`). */
export interface NewRequestPrefill {
  line: { text: string; unit?: string | null };
}

/** Откуда пришёл запрос — для клиента важно «я сам» или «через менеджера». */
export function requestSourceKey(source: NonNullable<ClientRequest['source']>): string {
  return source === 'cabinet' ? 'pages.requestDetail.sources.cabinet' : 'pages.requestDetail.sources.manager';
}

/**
 * Количество строки: «12», «2,5», « 2.5 » → десятичная строка контракта (`"2.5"`); не число — `null`.
 * Запятая — привычный десятичный разделитель в ru/uz.
 */
export function normalizeQuantity(value: string): string | null {
  const text = value.trim().replace(/\s/g, '').replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  if (Number(text) <= 0) return null;
  return text;
}
