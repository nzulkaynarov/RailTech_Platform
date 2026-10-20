/**
 * FIX-58 / D-12: служебная метка «[MANUAL_MODE]» (бэкенд пишет её для сверки ручных подписей) не
 * должна попадать на экран — ни из словаря, ни из сохранённого текста старых строк журнала.
 */
import { describe, it, expect } from 'vitest';

import { createTestI18n } from '@/test/renderWithProviders';
import ru from '@/i18n/locales/ru.json';
import en from '@/i18n/locales/en.json';
import { activityTitle, stripMarker } from '../activityText';

describe('метка [MANUAL_MODE] в журнале', () => {
  const i18n = createTestI18n();
  const t = i18n.t.bind(i18n);

  it('stripMarker снимает ведущую метку и только её', () => {
    expect(stripMarker('[MANUAL_MODE] Подписан договор')).toBe('Подписан договор');
    expect(stripMarker('Подписан договор [черновик]')).toBe('Подписан договор [черновик]');
    expect(stripMarker('Обычный текст')).toBe('Обычный текст');
  });

  it('старая строка без event_code печатается без метки', () => {
    const title = activityTitle(t, i18n, { action: '[MANUAL_MODE] Акт принят заказчиком' });
    expect(title).toBe('Акт принят заказчиком');
  });

  it('словарь событий договора и акта не содержит служебных меток', () => {
    for (const dict of [ru, en]) {
      const activity = (dict as unknown as { activity: Record<string, Record<string, { title?: string }>> }).activity;
      for (const group of Object.values(activity)) {
        for (const entry of Object.values(group)) {
          expect(entry.title ?? '').not.toMatch(/\[[A-Z_]+\]/);
        }
      }
    }
  });

  it('подпись договора по коду события — человеческая, с пометкой «вручную»', () => {
    const title = activityTitle(t, i18n, { event_code: 'contract.signed_client', event_params: { number: 'CT-1', deal_id: 5 }, action: '[MANUAL_MODE] x' });
    expect(title).toBe('Подписан договор (сторона клиента) — вручную');
  });
});
