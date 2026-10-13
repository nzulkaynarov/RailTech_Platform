/**
 * Русский интерфейс говорит по-русски.
 *
 * Проход глазами 03-08 нашёл в РУССКОМ словаре: «Deal #17» рядом со строкой «Сделка #17» на
 * одном экране, обрубленные «2 позиц.» / «1 продавц.» и сырые коды `READY_TO_SEND`,
 * `CLOSED_WON`, `APPROVED` в тексте для пользователя. Отдельная деталь: БАЗА хранила
 * правильные «2 позиции» и «1 продавцу» — шаблон витрины был ХУЖЕ текста, который сервер уже
 * записал.
 *
 * Эталоны: CLDR/ICU (в русском ЧЕТЫРЕ формы множественного числа — i18next выражает их
 * суффиксами `_one/_few/_many`), эвристика Нильсена №2 «язык пользователя, а не системы» и
 * №4 «одно понятие — одно слово» (канон волны D3).
 */

import { describe, it, expect } from 'vitest';

import ru from '../locales/ru.json';

function flatten(node: unknown, path = ''): Array<[string, string]> {
  if (typeof node === 'string') return [[path, node]];
  if (!node || typeof node !== 'object') return [];
  return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) =>
    flatten(value, path ? `${path}.${key}` : key),
  );
}

const ENTRIES = flatten(ru);

/** Ключи, где латиница законна: коды валют, форматы, служебные идентификаторы. */
const ALLOWED = /currencies\.|deliveryBases\.|uoms\.|countries\.|\.code$|Placeholder|placeholder/;

describe('русские строки', () => {
  it('не содержат англоязычных названий сущностей', () => {
    const offenders = ENTRIES.filter(
      ([key, value]) => !ALLOWED.test(key) && /\b(Deal|Quote|Lead|Contract|Invoice) #/.test(value),
    ).map(([key, value]) => `${key}: ${value}`);

    expect(offenders).toEqual([]);
  });

  it('не содержат обрубленных форм множественного числа', () => {
    // «2 позиц.» и «1 продавц.» — не русский язык ни в одной форме.
    // Требуем ЧИСЛО перед обрубком: «привязать товар.» в конце предложения — нормальный русский,
    // а «2 позиц.» — нет. Без этого условия проверка ловила обычные точки (поймано на себе).
    const offenders = ENTRIES.filter(([, value]) => /(\d+|\{\{count\}\})\s*(позиц|продавц|штук|товар)\.(?!\w)/.test(value)).map(
      ([key]) => key,
    );

    expect(offenders).toEqual([]);
  });

  it('не показывают пользователю сырые коды состояний', () => {
    const offenders = ENTRIES.filter(
      ([key, value]) =>
        !ALLOWED.test(key) &&
        !/^errors\.|^apiErrors\.\w*_CODE$/.test(key) &&
        /\b(READY_TO_SEND|CLOSED_WON|CLOSED_LOST|PENDING_APPROVAL|QUOTE_SENT|RFQ_OPEN)\b/.test(value),
    ).map(([key, value]) => `${key}: ${value}`);

    expect(offenders).toEqual([]);
  });

  it('множественное число заведено ФОРМАМИ, а не одной строкой', () => {
    // Русский требует три формы; одна строка с «{{count}}» их не выражает.
    const forms = (key: string) => ENTRIES.filter(([path]) => path.startsWith(`activity.deal.routed.${key}`));

    expect(forms('detail_one')).toHaveLength(1);
    expect(forms('detail_few')).toHaveLength(1);
    expect(forms('detail_many')).toHaveLength(1);
    // Единственной строки «detail» быть не должно — она и печатала «1 продавц.».
    expect(ENTRIES.filter(([path]) => path === 'activity.deal.routed.detail')).toEqual([]);
  });
});
