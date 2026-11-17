import { electronicFormatIBAN, isValidBIC, isValidIBAN } from 'ibantools';
import type { Company, Schemas } from '@/api/portal';

/**
 * Банковский счёт по международным стандартам (ADR-0029): счёт в Узбекистане — 20 цифр с кодом валюты в цифрах 6–8 и
 * МФО; счёт за рубежом — IBAN (ISO 13616) или номер, SWIFT/BIC (ISO 9362) обязателен, страна банка — из BIC. Проверка
 * здесь — подсказка при вводе; окончательная — в ERP (`parties/banking.py`).
 */
export type BankPlace = 'uz' | 'abroad';

export interface BankDraft {
  place: BankPlace;
  currency: string;
  holder_name_latin: string;
  account: string;
  mfo: string;
  swift: string;
  bank_name: string;
  bank_address: string;
  intermediary_swift: string;
  intermediary_account: string;
}

export type BankField = keyof Omit<BankDraft, 'place'>;
export type BankErrors = Partial<Record<BankField, string>>;

/** Валюты счёта (ISO 4217) и их код в номере счёта Узбекистана: 000 — сум. */
export const CURRENCY_DIGITS: Record<string, string> = {
  UZS: '000',
  USD: '840',
  EUR: '978',
  RUB: '643',
  CNY: '156',
  KZT: '398',
  TRY: '949',
  GBP: '826',
  AED: '784',
  CHF: '756',
  JPY: '392',
};
export const CURRENCIES = Object.keys(CURRENCY_DIGITS);

const SWIFT_CHARS = /^[A-Za-z0-9/\-?:().,'+ ]*$/;

export const compact = (value: string) => value.replace(/[\s.-]/g, '').toUpperCase();

/** Номер группами по 4 знака — как в документах. */
export const grouped = (value: string) => compact(value).replace(/(.{4})(?=.)/g, '$1 ');

export function defaultAccount(company: Company): Schemas['BankAccount'] | undefined {
  const accounts = company.bank_accounts ?? [];
  return accounts.find((a) => a.is_default && a.currency === 'UZS') ?? accounts.find((a) => a.is_default) ?? accounts[0];
}

export function bankDraft(account?: Schemas['BankAccount']): BankDraft {
  return {
    place: account && account.bank_country && account.bank_country !== 'UZ' ? 'abroad' : 'uz',
    currency: account?.currency ?? 'UZS',
    holder_name_latin: account?.holder_name_latin ?? '',
    account: account?.account ?? '',
    mfo: account?.mfo ?? '',
    swift: account?.swift ?? '',
    bank_name: account?.bank_name ?? '',
    bank_address: account?.bank_address ?? '',
    intermediary_swift: account?.intermediary_swift ?? '',
    intermediary_account: account?.intermediary_account ?? '',
  };
}

const FIELDS: BankField[] = [
  'currency',
  'holder_name_latin',
  'account',
  'mfo',
  'swift',
  'bank_name',
  'bank_address',
  'intermediary_swift',
  'intermediary_account',
];
const CODES = new Set<BankField>(['account', 'mfo', 'swift', 'intermediary_swift', 'intermediary_account']);

const norm = (field: BankField, value: string) => (CODES.has(field) ? compact(value) : value.trim());

export function bankChanged(before: BankDraft, after: BankDraft): boolean {
  if (!compact(after.account)) return false; // пустой номер — смены нет
  return before.place !== after.place || FIELDS.some((f) => norm(f, before[f]) !== norm(f, after[f]));
}

/** Страна банка: Узбекистан — UZ, за рубежом — из SWIFT/BIC (буквы 5–6). */
export function bankCountry(draft: BankDraft): string {
  if (draft.place === 'uz') return 'UZ';
  return compact(draft.swift).slice(4, 6);
}

export function validateBank(draft: BankDraft): BankErrors {
  const errors: BankErrors = {};
  const account = compact(draft.account);
  const swift = compact(draft.swift);
  if (!account) errors.account = 'required';
  if (draft.place === 'uz') {
    if (account && !/^\d{20}$/.test(account)) errors.account = 'uzFormat';
    else if (account && CURRENCY_DIGITS[draft.currency] && account.slice(5, 8) !== CURRENCY_DIGITS[draft.currency])
      errors.account = 'currencyMismatch';
    const mfo = compact(draft.mfo);
    if (!/^\d{5}$/.test(mfo)) errors.mfo = mfo ? 'uzFormat' : 'required';
    else if (!draft.bank_name.trim()) errors.bank_name = 'required'; // МФО из справочника подставит банк сам
  } else {
    if (!swift) errors.swift = 'required';
    else if (!isValidBIC(swift)) errors.swift = 'invalid';
    const iban = electronicFormatIBAN(account) ?? '';
    if (account && /^[A-Z]{2}\d{2}/.test(account) && !isValidIBAN(iban)) errors.account = 'iban';
    else if (account && !/^[A-Z0-9]{1,34}$/.test(account)) errors.account = 'format';
    if (!SWIFT_CHARS.test(draft.holder_name_latin)) errors.holder_name_latin = 'latin';
  }
  if (draft.swift && draft.place === 'uz' && !isValidBIC(swift)) errors.swift = 'invalid';
  const intermediary = compact(draft.intermediary_swift);
  if (intermediary && !isValidBIC(intermediary)) errors.intermediary_swift = 'invalid';
  if (compact(draft.intermediary_account) && !intermediary) errors.intermediary_swift = 'required';
  return errors;
}

export function bankInput(draft: BankDraft): Schemas['BankAccountInput'] {
  const input: Schemas['BankAccountInput'] = {
    bank_country: bankCountry(draft),
    currency: draft.currency,
    account: compact(draft.account),
  };
  for (const field of FIELDS) {
    if (field === 'currency' || field === 'account') continue;
    const value = norm(field, draft[field]);
    if (value) input[field] = value;
  }
  return input;
}

/** Ошибка ERP по полю счёта (422) → поле формы. */
export const BANK_ERROR_FIELD: Record<string, BankField> = {
  BANK_CURRENCY_INVALID: 'currency',
  BANK_ACCOUNT_INVALID: 'account',
  BANK_CODE_INVALID: 'mfo',
  BANK_SWIFT_INVALID: 'swift',
  BANK_COUNTRY_INVALID: 'swift',
  BANK_HOLDER_LATIN_INVALID: 'holder_name_latin',
  BANK_INTERMEDIARY_INVALID: 'intermediary_swift',
};
