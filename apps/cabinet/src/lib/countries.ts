/**
 * Справочник стран, масок телефонов и форматов налоговых номеров (COUNTRY-MASK-1).
 * Используется в формах онбординга (/become-partner, /new-client), в карточке компании
 * и для динамической валидации ИНН / рег. номеров.
 */

export interface CountryInfo {
  code: string;
  name: string;
  phoneCode: string;
  phoneMask: string;
  phonePlaceholder: string;
  taxLabelKey: string;
  taxLabelDefault: string;
  taxPlaceholder: string;
  taxRegex?: RegExp;
  isUzbekistan: boolean;
}

export const COUNTRIES: readonly CountryInfo[] = [
  {
    code: 'UZ',
    name: 'Узбекистан',
    phoneCode: '+998',
    phoneMask: '+998 (99) 999-99-99',
    phonePlaceholder: '+998 90 123-45-67',
    taxLabelKey: 'countryMask.innUz',
    taxLabelDefault: 'ИНН (STIR)',
    taxPlaceholder: '123456789',
    taxRegex: /^\d{9}$/,
    isUzbekistan: true,
  },
  {
    code: 'KZ',
    name: 'Казахстан',
    phoneCode: '+7',
    phoneMask: '+7 (799) 999-99-99',
    phonePlaceholder: '+7 701 123-45-67',
    taxLabelKey: 'countryMask.binKz',
    taxLabelDefault: 'БИН / ИИН',
    taxPlaceholder: '123456789012',
    taxRegex: /^\d{12}$/,
    isUzbekistan: false,
  },
  {
    code: 'RU',
    name: 'Россия',
    phoneCode: '+7',
    phoneMask: '+7 (999) 999-99-99',
    phonePlaceholder: '+7 916 123-45-67',
    taxLabelKey: 'countryMask.innRu',
    taxLabelDefault: 'ИНН',
    taxPlaceholder: '1234567890',
    taxRegex: /^\d{10}(\d{2})?$/,
    isUzbekistan: false,
  },
  {
    code: 'CN',
    name: 'Китай',
    phoneCode: '+86',
    phoneMask: '+86 999 9999 9999',
    phonePlaceholder: '+86 138 1234 5678',
    taxLabelKey: 'countryMask.usccCn',
    taxLabelDefault: 'Единый код (USCC)',
    taxPlaceholder: '91110000000000000X',
    taxRegex: /^[0-9A-Z]{18}$/,
    isUzbekistan: false,
  },
  {
    code: 'TR',
    name: 'Турция',
    phoneCode: '+90',
    phoneMask: '+90 999 999 99 99',
    phonePlaceholder: '+90 532 123 45 67',
    taxLabelKey: 'countryMask.vknTr',
    taxLabelDefault: 'VKN (Налоговый номер)',
    taxPlaceholder: '1234567890',
    taxRegex: /^\d{10}$/,
    isUzbekistan: false,
  },
  {
    code: 'BY',
    name: 'Беларусь',
    phoneCode: '+375',
    phoneMask: '+375 (99) 999-99-99',
    phonePlaceholder: '+375 29 123-45-67',
    taxLabelKey: 'countryMask.unpBy',
    taxLabelDefault: 'УНП',
    taxPlaceholder: '123456789',
    taxRegex: /^\d{9}$/,
    isUzbekistan: false,
  },
  {
    code: 'KG',
    name: 'Кыргызстан',
    phoneCode: '+996',
    phoneMask: '+996 (999) 999-999',
    phonePlaceholder: '+996 555 123-456',
    taxLabelKey: 'countryMask.innKg',
    taxLabelDefault: 'ИНН',
    taxPlaceholder: '12345678901234',
    taxRegex: /^\d{14}$/,
    isUzbekistan: false,
  },
  {
    code: 'TJ',
    name: 'Таджикистан',
    phoneCode: '+992',
    phoneMask: '+992 99 999 9999',
    phonePlaceholder: '+992 90 123 4567',
    taxLabelKey: 'countryMask.innTj',
    taxLabelDefault: 'ИНН',
    taxPlaceholder: '123456789',
    taxRegex: /^\d{9}$/,
    isUzbekistan: false,
  },
  {
    code: 'DE',
    name: 'Германия',
    phoneCode: '+49',
    phoneMask: '+49 999 9999999',
    phonePlaceholder: '+49 170 1234567',
    taxLabelKey: 'countryMask.vatDe',
    taxLabelDefault: 'USt-IdNr. / HRB',
    taxPlaceholder: 'DE123456789',
    isUzbekistan: false,
  },
  {
    code: 'AE',
    name: 'ОАЭ',
    phoneCode: '+971',
    phoneMask: '+971 99 999 9999',
    phonePlaceholder: '+971 50 123 4567',
    taxLabelKey: 'countryMask.trnAe',
    taxLabelDefault: 'TRN (Налоговый номер)',
    taxPlaceholder: '100123456700003',
    taxRegex: /^\d{15}$/,
    isUzbekistan: false,
  },
  {
    code: 'OTHER',
    name: 'Другая страна',
    phoneCode: '+',
    phoneMask: '',
    phonePlaceholder: '+...',
    taxLabelKey: 'countryMask.taxIdOther',
    taxLabelDefault: 'Рег. номер / Tax ID',
    taxPlaceholder: 'Регистрационный или налоговый номер',
    isUzbekistan: false,
  },
];

export const DEFAULT_COUNTRY: CountryInfo = COUNTRIES[0];

export function findCountry(code: string | null | undefined): CountryInfo {
  if (!code) return DEFAULT_COUNTRY;
  const upper = code.trim().toUpperCase();
  return COUNTRIES.find((c) => c.code === upper) ?? {
    code: upper,
    name: upper,
    phoneCode: '+',
    phoneMask: '',
    phonePlaceholder: '+...',
    taxLabelKey: 'countryMask.taxIdOther',
    taxLabelDefault: 'Рег. номер / Tax ID',
    taxPlaceholder: 'Регистрационный или налоговый номер',
    isUzbekistan: false,
  };
}

/** Автодополнение телефонного префикса при переключении страны. */
export function adaptPhoneForCountry(phone: string, prevCountry: CountryInfo, nextCountry: CountryInfo): string {
  const trimmed = phone.trim();
  if (!trimmed) {
    return '';
  }
  if (trimmed === prevCountry.phoneCode) {
    return nextCountry.phoneCode;
  }
  if (trimmed.startsWith(prevCountry.phoneCode)) {
    return nextCountry.phoneCode + trimmed.slice(prevCountry.phoneCode.length);
  }
  if (!trimmed.startsWith('+')) {
    return `${nextCountry.phoneCode} ${trimmed}`;
  }
  return trimmed;
}
