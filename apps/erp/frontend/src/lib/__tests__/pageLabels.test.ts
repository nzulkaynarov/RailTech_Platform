import { describe, it, expect } from 'vitest';
import { createTestI18n } from '@/test/renderWithProviders';
import { PAGE_IDS } from '@/config/pageRegistry';
import { getPageLabel } from '../pageLabels';

// FIX-58 / D-12: хлебная крошка страницы «Клиенты» печатала сырой маршрут «clients».
// У КАЖДОЙ страницы реестра есть человеческая подпись — ни одна не равна своему id.
describe('getPageLabel', () => {
  const i18n = createTestI18n();
  const t = i18n.t.bind(i18n);

  it.each(PAGE_IDS.map((id) => [id]))('страница %s имеет подпись, не равную идентификатору маршрута', (id) => {
    const label = getPageLabel(id, t);
    expect(label).not.toBe(id);
    expect(label).not.toMatch(/^breadcrumbs\./);
    expect(label.length).toBeGreaterThan(0);
  });
});
