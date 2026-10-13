/**
 * Журнал локализуется и при РЕГИОНАЛЬНОМ коде языка.
 *
 * Браузер присылает `en-US` / `ru-RU`, а ресурсы лежат под `en` / `ru`. Прежняя защита
 * спрашивала шаблон по «сырому» тегу — и каждая строка журнала БЕЗ параметров падала на текст,
 * записанный в базу при событии (он всегда русский). В русском интерфейсе это было незаметно,
 * потому что запасной текст тоже русский; в английском половина ленты оператора осталась
 * русской (ux-review 03-08).
 */

import { describe, it, expect, beforeAll } from 'vitest';
import i18next, { type i18n as I18nType } from 'i18next';

import { activityTitle, activityDetail } from '../activityText';

let i18n: I18nType;

beforeAll(async () => {
  i18n = i18next.createInstance();
  await i18n.init({
    // Именно региональный тег — воспроизводим то, что присылает браузер.
    lng: 'en-US',
    fallbackLng: 'ru',
    supportedLngs: ['ru', 'en'],
    nonExplicitSupportedLngs: true,
    resources: {
      en: { translation: { activity: {
        quote: { approval_auto: { title: 'Approved automatically', detail: 'Chain passed automatically' } },
        invoice: { created: { title: 'Invoice created', detail: 'Invoice {{number}}' } },
      } } },
      ru: { translation: { activity: {
        quote: { approval_auto: { title: 'Согласовано автоматически', detail: 'Цепочка пройдена' } },
      } } },
    },
    interpolation: { escapeValue: false },
  });
});

describe('локализация журнала при региональном коде языка', () => {
  it('строка БЕЗ параметров всё равно переводится', () => {
    const entry = { event_code: 'quote.approval_auto', event_params: {}, action: 'Согласовано автоматически' };

    expect(activityTitle(i18n.t.bind(i18n), i18n, entry)).toBe('Approved automatically');
  });

  it('строка С параметрами переводится, как и раньше', () => {
    const entry = {
      event_code: 'invoice.created',
      event_params: { number: 'INV-1' },
      action: 'Счёт создан',
      detail: 'Счёт INV-1',
    };

    expect(activityTitle(i18n.t.bind(i18n), i18n, entry)).toBe('Invoice created');
    expect(activityDetail(i18n.t.bind(i18n), i18n, entry)).toBe('Invoice INV-1');
  });

  it('шаблон с плейсхолдером без параметров по-прежнему НЕ рендерится дырами', () => {
    // Смысл исходной защиты сохраняется: «Invoice {{number}}» без number дал бы «Invoice ».
    const entry = { event_code: 'invoice.created', event_params: {}, action: 'Счёт создан', detail: 'Счёт INV-9' };

    expect(activityDetail(i18n.t.bind(i18n), i18n, entry)).toBe('Счёт INV-9');
  });

  it('неизвестный код падает на сохранённый текст', () => {
    const entry = { event_code: 'nope.unknown', event_params: {}, action: 'Ручное действие' };

    expect(activityTitle(i18n.t.bind(i18n), i18n, entry)).toBe('Ручное действие');
  });
});
