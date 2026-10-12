/** Сделки: формат суммы и цвет стадии (чистые функции, ADR-0019). */
import { t } from "../i18n/ru";

const NBSP = " ";

/** «1 250 000 UZS»; дробная часть — только если она не нулевая. */
export function formatMoney(amount: string | number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === "") return t.deals.noAmount;
  const value = Number(amount);
  if (!Number.isFinite(value)) return t.deals.noAmount;
  const text = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
    .format(value)
    .replace(/\s/g, NBSP);
  return `${text}${NBSP}${currency}`;
}

export const STAGE_COLORS: Record<string, string> = {
  open: "processing",
  won: "success",
  lost: "default",
};

export const stageLabel = (stage: string): string => t.deals.stages[stage] ?? stage;

/** Стадия из адреса (`/deals?stage=won`): только известные значения. */
export function stageFromSearch(value: string | null): "open" | "won" | "lost" | undefined {
  return value === "open" || value === "won" || value === "lost" ? value : undefined;
}

/** Валюты формы: из настройки `deals.currency` и UZS/USD (без ручного ввода кода). */
export const currencyOptions = (fromSettings: string): string[] =>
  Array.from(new Set([fromSettings, "UZS", "USD"]));

/** «1500000» → «1 500 000» (узкий неразрывный пробел не нужен — обычный пробел читаем). */
export const groupThousands = (value: number | string | undefined): string =>
  value === undefined || value === "" ? "" : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

export const parseAmount = (text: string | undefined): number =>
  Number((text ?? "").replace(/[^\d.]/g, "")) || 0;
