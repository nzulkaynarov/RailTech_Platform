import { electronicFormatIBAN, isValidBIC, isValidIBAN } from "ibantools";

/**
 * Банковский счёт по международным стандартам (ADR-0029): в Узбекистане — 20 цифр с кодом валюты в цифрах 6–8 и МФО;
 * за рубежом — IBAN (ISO 13616) или номер счёта, SWIFT/BIC (ISO 9362) обязателен, страна банка — из BIC. Здесь —
 * подсказка при вводе; окончательная проверка и подстановка кодов — в ERP (`parties/banking.py`).
 */
export type BankPlace = "uz" | "abroad";

/** Код валюты в номере счёта Узбекистана: 000 — сум, иначе цифровой код ISO 4217. */
export const CURRENCY_DIGITS: Record<string, string> = {
  UZS: "000",
  USD: "840",
  EUR: "978",
  RUB: "643",
  CNY: "156",
  KZT: "398",
  TRY: "949",
  GBP: "826",
  AED: "784",
  CHF: "756",
  JPY: "392",
};

const SWIFT_CHARS = /^[A-Za-z0-9/\-?:().,'+ ]*$/;

export const compact = (value: string | undefined | null): string =>
  (value ?? "").replace(/[\s.-]/g, "").toUpperCase();

/** Номер группами по 4 знака — как в документах. */
export const grouped = (value: string): string => compact(value).replace(/(.{4})(?=.)/g, "$1 ");

export const placeOf = (country: string | undefined | null): BankPlace =>
  country && country !== "UZ" ? "abroad" : "uz";

/** Страна банка: Узбекистан — UZ, за рубежом — из SWIFT/BIC (буквы 5–6). */
export const countryOf = (place: BankPlace, swift: string): string =>
  place === "uz" ? "UZ" : compact(swift).slice(4, 6);

/** Причина ошибки номера счёта (те же коды, что у ERP) или `null`. */
export function accountProblem(place: BankPlace, account: string, currency: string): string | null {
  const value = compact(account);
  if (!value) return "required";
  if (place === "uz") {
    if (!/^\d{20}$/.test(value)) return "uz_format";
    const digits = CURRENCY_DIGITS[currency];
    if (digits && value.slice(5, 8) !== digits) return "currency_mismatch";
    return null;
  }
  if (/^[A-Z]{2}\d{2}/.test(value) && !isValidIBAN(electronicFormatIBAN(value) ?? ""))
    return "iban_invalid";
  if (!/^[A-Z0-9]{1,34}$/.test(value)) return "format";
  return null;
}

export function mfoProblem(place: BankPlace, mfo: string): string | null {
  if (place !== "uz") return null;
  const value = compact(mfo);
  if (!value) return "required";
  return /^\d{5}$/.test(value) ? null : "uz_format";
}

export function swiftProblem(swift: string, required: boolean): string | null {
  const value = compact(swift);
  if (!value) return required ? "required" : null;
  return isValidBIC(value) ? null : "invalid";
}

export const latinProblem = (value: string): string | null =>
  SWIFT_CHARS.test(value) ? null : "latin_charset";
