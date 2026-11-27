import { parse } from 'yaml';
import { describe, expect, it } from 'vitest';

import { LOCALES } from '@/i18n/locales';

/**
 * ПРАВДА-2: слово статуса заявки в списке «Заявки» — из `packages/contracts/client-request-statuses.yaml`, то же, что
 * Платформа пишет в карточке компании («В кабинете клиента: …»). Сверка по всем языкам и всем статусам.
 */
describe('статусы заявки — как в контракте', () => {
  it.each(LOCALES.map((locale) => locale.code))('%s: status.request совпадает с client-request-statuses.yaml', async (code) => {
    // Типов node в Cabinet нет (tsconfig.app): модуль берётся динамически, строкой
    const fs = (await import('node:fs' as string)) as { readFileSync: (path: string, encoding: string) => string };
    // vitest идёт из apps/cabinet
    const contract = parse(fs.readFileSync('../../packages/contracts/client-request-statuses.yaml', 'utf8')) as {
      statuses: Record<string, { text: Record<string, string> }>;
    };
    const locale = LOCALES.find((item) => item.code === code);
    const request = (locale?.translation as { status: { request: Record<string, string> } }).status.request;
    for (const [key, value] of Object.entries(contract.statuses)) {
      expect(request[key], `${code}.status.request.${key}`).toBe(value.text[code]);
    }
  });
});
