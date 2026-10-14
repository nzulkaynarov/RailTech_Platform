import { describe, it, expect } from 'vitest';

import ru from '@/i18n/locales/ru.json';
import en from '@/i18n/locales/en.json';
import { COMPANY_TYPE_LABEL_KEY, companyTypeLabelKey } from '@/lib/codes';

/** Walk a dotted i18n key ("companyTypes.client") into a locale object. */
function resolve(locale: Record<string, unknown>, dottedKey: string): unknown {
  return dottedKey.split('.').reduce<unknown>(
    (node, segment) =>
      node && typeof node === 'object' ? (node as Record<string, unknown>)[segment] : undefined,
    locale,
  );
}

/**
 * DT5b: the backend renders Django `choices` as `*_display` strings that are baked in
 * Russian at the source. The SPA must map the CODE to a localized key instead. These
 * maps are the contract — every key they promise has to exist in BOTH locales, or an
 * English user silently gets the raw key rendered back at them.
 */
const LABEL_MAPS: Array<[string, Record<string, string>]> = [
  ['COMPANY_TYPE_LABEL_KEY', COMPANY_TYPE_LABEL_KEY],
];

describe('display-code label maps', () => {
  it.each(LABEL_MAPS)('%s resolves every key in ru.json and en.json', (_name, map) => {
    const codes = Object.keys(map);
    expect(codes.length).toBeGreaterThan(0);

    for (const code of codes) {
      const key = map[code];
      expect(typeof resolve(ru as Record<string, unknown>, key), `ru.json missing ${key}`).toBe(
        'string',
      );
      expect(typeof resolve(en as Record<string, unknown>, key), `en.json missing ${key}`).toBe(
        'string',
      );
    }
  });

  it.each(LABEL_MAPS)('%s translations differ between ru and en (not copy-pasted)', (_name, map) => {
    // A real localization, not the Russian string duplicated into en.json.
    for (const key of Object.values(map)) {
      expect(resolve(ru as Record<string, unknown>, key)).not.toBe(
        resolve(en as Record<string, unknown>, key),
      );
    }
  });
});

describe('display-code label-key resolvers', () => {
  const RESOLVERS: Array<[string, (code?: string | null) => string, string, string]> = [
    ['companyTypeLabelKey', companyTypeLabelKey, 'MANUFACTURER', 'companyTypes.manufacturer'],
  ];

  it.each(RESOLVERS)('%s maps a known code to its i18n key', (_name, resolver, code, expected) => {
    expect(resolver(code)).toBe(expected);
  });

  it.each(RESOLVERS)(
    '%s returns "" for unknown/empty codes so callers fall back to the DB display',
    (_name, resolver) => {
      // Operators can add lookup rows and the backend can gain new choices;
      // an empty key is the documented signal to render the server-provided string.
      expect(resolver('NOT_A_REAL_CODE')).toBe('');
      expect(resolver(undefined)).toBe('');
      expect(resolver(null)).toBe('');
      expect(resolver('')).toBe('');
    },
  );

  it('never matches on a translated name (IRON RULE 2)', () => {
    // The Russian display strings the backend sends must not be accepted as codes.
    expect(companyTypeLabelKey('Производитель')).toBe('');
  });
});
