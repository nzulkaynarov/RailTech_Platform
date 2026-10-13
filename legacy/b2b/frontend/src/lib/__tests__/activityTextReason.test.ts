/**
 * Причина отказа ДОХОДИТ до ленты.
 *
 * Прогон глазами 17-08: клиент отклонил КП с причиной, продавец видел в истории только
 * «Quote rejected by client — Quote v2» и нигде не находил, почему. Причина лежала в
 * event_params, но шаблон её не печатал. Теперь непустая причина включает i18next-контекст
 * `reason` → вариант `detail_reason`; без причины печатается базовый `detail` (без висящего «—»).
 */

import { describe, it, expect, beforeAll } from 'vitest';
import i18next, { type i18n as I18nType } from 'i18next';

import { activityDetail } from '../activityText';
import en from '@/i18n/locales/en.json';
import ru from '@/i18n/locales/ru.json';

let i18n: I18nType;

beforeAll(async () => {
  i18n = i18next.createInstance();
  await i18n.init({
    lng: 'en',
    fallbackLng: 'ru',
    resources: { en: { translation: en }, ru: { translation: ru } },
    interpolation: { escapeValue: false },
  });
});

describe('причина отказа по КП в ленте', () => {
  it('с причиной печатается вариант detail_reason', () => {
    const text = activityDetail(i18n.t.bind(i18n), i18n, {
      action: 'КП отклонено клиентом',
      detail: 'КП v2 — дорого',
      event_code: 'quote.rejected',
      event_params: { version: 2, reason: 'дорого' },
    });
    expect(text).toBe('Quote v2 — дорого');
  });

  it('без причины — базовый detail, без висящего тире', () => {
    const text = activityDetail(i18n.t.bind(i18n), i18n, {
      action: 'КП отклонено клиентом',
      detail: 'КП v2',
      event_code: 'quote.rejected',
      event_params: { version: 2, reason: '' },
    });
    expect(text).toBe('Quote v2');
  });
});
