/**
 * Статус документа пишется одинаково везде, где документ показан.
 *
 * Виджет «Недавние документы» и поиск ⌘K печатали статус СЫРЫМ КОДОМ (`ISSUED`,
 * `PENDING_CLIENT`), тогда как в реестре тот же статус переведён. Одно состояние — два разных
 * написания на соседних экранах; поймано проходом глазами 2026-07-31, ни один тест этого не
 * видел, потому что `defaultValue` прятал отсутствующий перевод.
 *
 * Эталон тот же, что у терминологии: эвристика Нильсена «одно понятие — одно слово».
 */

import { describe, it, expect } from 'vitest';

import ru from '@/i18n/locales/ru.json';
import { documentStatusLabelKey } from '../codes';

/** Значение по ключу вида `actsPage.status.ISSUED`. */
function lookup(key: string): string | undefined {
  return key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], ru) as
    | string
    | undefined;
}

describe('подпись статуса документа', () => {
  it.each([
    ['act', 'ISSUED'],
    ['contract', 'PENDING_CLIENT'],
    ['invoice', 'PARTIAL'],
    ['generated', 'CANCELLED'],
    ['quote', 'SENT'],
  ])('%s/%s разрешается в существующий перевод', (type, code) => {
    const key = documentStatusLabelKey(type, code);

    expect(key).not.toBe('');
    expect(lookup(key)).toBeTypeOf('string');
  });

  it('берёт подпись из словаря ТОГО реестра, где документ живёт', () => {
    // Не заводим третий словарь: дублирование подписей — второе место, где они разъедутся.
    expect(documentStatusLabelKey('act', 'ISSUED')).toBe('actsPage.status.ISSUED');
    expect(documentStatusLabelKey('invoice', 'PAID')).toBe('invoicesPage.status.PAID');
  });

  it('неизвестный тип не притворяется переведённым', () => {
    // Пустой ключ — сигнал вызывающему показать сырой код, а не выдумать подпись.
    expect(documentStatusLabelKey('unknown', 'ISSUED')).toBe('');
    expect(documentStatusLabelKey('act', undefined)).toBe('');
  });
});
