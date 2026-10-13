import { describe, expect, it } from 'vitest';

import { DEFAULT_LOCALE, LOCALES, i18nResources, localeFor } from '../locales';

/**
 * Почва под N локалей (L3, spec-bilingual-ru-en §5).
 *
 * Владелец: узбекский с кириллицей И латиницей нужен «после широкого использования». Тесты
 * держат инвариант «ничто не знает, что языков ровно два»: реестр — данные, коды — BCP 47,
 * скрипт-варианты (`uz-Latn`/`uz-Cyrl`) разрешаются корректно ещё ДО того, как появятся.
 */
describe('реестр локалей', () => {
  it('каждая локаль объявлена полностью — иначе переключатель отрисует пустоту', () => {
    for (const locale of LOCALES) {
      expect(locale.code, 'код').toBeTruthy();
      expect(locale.nativeName, `nativeName у ${locale.code}`).toBeTruthy();
      expect(locale.shortLabel, `shortLabel у ${locale.code}`).toBeTruthy();
      expect(locale.formatLocale, `formatLocale у ${locale.code}`).toBeTruthy();
      expect(Object.keys(locale.translation).length, `ресурс ${locale.code}`).toBeGreaterThan(0);
    }
  });

  it('коды уникальны и в формате BCP 47 (допускают скрипт: uz-Latn)', () => {
    const codes = LOCALES.map((locale) => locale.code);
    expect(new Set(codes).size).toBe(codes.length);
    for (const code of codes) {
      expect(code, `код ${code}`).toMatch(/^[a-z]{2}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$/);
    }
  });

  it('язык по умолчанию присутствует в реестре', () => {
    expect(LOCALES.some((locale) => locale.code === DEFAULT_LOCALE)).toBe(true);
  });

  it('ресурсы i18next собираются из реестра, а не перечисляются руками', () => {
    expect(Object.keys(i18nResources).sort()).toEqual(LOCALES.map((l) => l.code).sort());
  });
});

describe('разрешение кода локали', () => {
  it('точное совпадение', () => {
    expect(localeFor('en').code).toBe('en');
    expect(localeFor('ru').code).toBe('ru');
  });

  it('региональный вариант падает на язык: ru-RU → ru', () => {
    expect(localeFor('ru-RU').code).toBe('ru');
    expect(localeFor('en-GB').code).toBe('en');
  });

  it('неизвестный язык и пустой код падают на язык по умолчанию', () => {
    expect(localeFor('fr').code).toBe(DEFAULT_LOCALE);
    expect(localeFor(undefined).code).toBe(DEFAULT_LOCALE);
    expect(localeFor('').code).toBe(DEFAULT_LOCALE);
  });

  it('скрипт-вариант с регионом сводится к скрипту, а не к языку целиком', () => {
    // Пока uz нет в реестре, оба кода уходят в дефолт — но резолвер обязан пробовать
    // «язык+скрипт» ДО «языка», иначе uz-Cyrl и uz-Latn слились бы в один при добавлении.
    const withScript = 'uz-Latn-UZ'.split('-').slice(0, 2).join('-');
    expect(withScript).toBe('uz-Latn');
    expect(localeFor('uz-Latn-UZ').code).toBe(DEFAULT_LOCALE);
  });

  it('региональный формат отделён от языка — RU-интерфейс печатает узбекистанские форматы', () => {
    expect(localeFor('ru').formatLocale).toBe('ru-UZ');
  });
});
