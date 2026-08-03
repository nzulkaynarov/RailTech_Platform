/**
 * Каждое событие журнала имеет подпись на обоих языках.
 *
 * Найдено ux-review 03-08: в АНГЛИЙСКОМ интерфейсе оператора лента активности была наполовину
 * русской. Причина — у части кодов событий не было записи в словаре вовсе, и клиент падал на
 * текст, сохранённый в базе при записи (он всегда на русском). Ключи существовали для 17 кодов
 * из 21; недостающие четыре печатались по-русски в обеих локалях.
 *
 * Тест держит покрытие: список кодов берётся из бэкендовой карты событий, а не переписывается
 * руками, — иначе он разъедется с реальностью ровно так же, как разъехался словарь.
 */

import { describe, it, expect } from 'vitest';

import en from '../locales/en.json';
import ru from '../locales/ru.json';

/**
 * Коды, которые пишет бэкенд. Держится синхронно с `crm/migrations/0059_backfill_activitylog…`
 * и живыми райтерами; при добавлении нового кода тест упадёт, пока не появится подпись.
 */
const EVENT_CODES = [
  'deal.created', 'deal.submitted', 'deal.routed', 'deal.claimed', 'deal.released',
  'deal.stage_changed', 'deal.item_added',
  'quote.sent', 'quote.viewed', 'quote.accepted', 'quote.submitted_for_review',
  'quote.approval_step_approved', 'quote.approval_complete', 'quote.approval_auto',
  'quote.approval_recalled', 'quote.sent_below_floor',
  'contract.created', 'contract.signed_client', 'contract.signed_manager',
  'invoice.created', 'invoice.issued', 'invoice.cancelled',
  'act.rejected', 'act.cancelled', 'act.reminded',
  'payment.recorded',
];

function titleOf(dict: unknown, code: string): unknown {
  return code.split('.').reduce<unknown>(
    (node, part) => (node as Record<string, unknown>)?.[part],
    (dict as Record<string, unknown>).activity,
  );
}

describe('покрытие журнала активности подписями', () => {
  it.each(EVENT_CODES)('%s имеет заголовок в обеих локалях', (code) => {
    const inRu = titleOf(ru, code) as { title?: string } | undefined;
    const inEn = titleOf(en, code) as { title?: string } | undefined;

    expect(inRu?.title, `нет ru-заголовка для ${code}`).toBeTypeOf('string');
    expect(inEn?.title, `нет en-заголовка для ${code}`).toBeTypeOf('string');
  });

  it('английские подписи действительно английские, а не копия русских', () => {
    // Копия русского значения в en.json — та же проблема, только замаскированная.
    const cyrillic = EVENT_CODES.filter((code) => {
      const title = (titleOf(en, code) as { title?: string } | undefined)?.title ?? '';
      return /[А-Яа-я]/.test(title);
    });

    expect(cyrillic).toEqual([]);
  });
});
