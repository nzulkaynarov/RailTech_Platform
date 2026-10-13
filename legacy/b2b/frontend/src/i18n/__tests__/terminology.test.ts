/**
 * Одно слово для одной вещи.
 *
 * Проход глазами 2026-07-31 показал то, чего не видел ни один тест: меню называет документ
 * «Контракты», подпись под заголовком — «Договоры…», а сам напечатанный PDF — «Договор». То же
 * с «Инвойсами» и «Счетами». Пользователь читает на экране одно слово, а на бумаге, которую
 * печатает, другое — ровно то, из-за чего «непонятно, чего ожидать».
 *
 * Эталон — эвристика Нильсена №4 «Consistency and standards»: одно и то же понятие называется
 * одним и тем же словом; и №2 «Match between system and the real world»: язык пользователя, а
 * не внутренний жаргон. Юридически и в бухгалтерской практике Узбекистана документы называются
 * «договор» и «счёт» — так они и напечатаны в самих PDF, поэтому интерфейс подстроен под них,
 * а не наоборот.
 *
 * Тест держит именно это: англицизмы не возвращаются в пользовательские строки.
 */

import { describe, it, expect } from 'vitest';

import ru from '../locales/ru.json';

/** Все строковые значения словаря с их путями — чтобы падение называло виновный ключ. */
function flatten(node: unknown, path = ''): Array<[string, string]> {
  if (typeof node === 'string') return [[path, node]];
  if (!node || typeof node !== 'object') return [];
  return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) =>
    flatten(value, path ? `${path}.${key}` : key),
  );
}

const ENTRIES = flatten(ru);

describe('терминология документов', () => {
  it('в интерфейсе нет «контракта» — документ называется договором', () => {
    const offenders = ENTRIES.filter(([, value]) => /[Кк]онтракт/.test(value)).map(([key]) => key);

    expect(offenders).toEqual([]);
  });

  it('в интерфейсе нет «инвойса» — документ называется счётом', () => {
    const offenders = ENTRIES.filter(([, value]) => /[Ии]нвойс/.test(value)).map(([key]) => key);

    expect(offenders).toEqual([]);
  });

  it('меню, заголовок страницы и подпись говорят одним словом', () => {
    // Раньше меню говорило «Контракты», а подпись под заголовком — «Договоры между клиентом и
    // продавцом»: два слова про один документ на одном экране.
    expect(ru.shell.contracts).toBe('Договоры');
    expect(ru.contractsPage.title).toBe('Договоры');
    expect(ru.contractsPage.description).toContain('Договоры');

    expect(ru.shell.invoices).toBe('Счета');
    expect(ru.invoicesPage.title).toBe('Счета');
    expect(ru.invoicesPage.description).toContain('Счета');
  });

  it('склонения не поломаны заменой', () => {
    // Механическая замена подстроки дала бы «оплаты по счёт» — формы переведены пофомно.
    expect(ru.recordPayment.description).toContain('по счёту');
    expect(ru.paymentsPage.description).toContain('по счетам');
  });
});
