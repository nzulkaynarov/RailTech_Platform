/**
 * Числа по-русски (Intl ru-RU): пробел между разрядами, запятая в дробной части.
 * Неразрывные пробелы — число не переносится по строкам. Строка, а не number: antd
 * `Statistic` форматирует number по-английски («1,073.3»), строку — выводит как есть.
 */
import { t } from "../i18n/ru";

const NBSP = " ";
const nbsp = (text: string) => text.replace(/\s/g, NBSP);

export function formatNumber(value: number, maxFraction = 0): string {
  return nbsp(new Intl.NumberFormat("ru-RU", { maximumFractionDigits: maxFraction }).format(value));
}

/** Доллары расходов на модели: «$0,13», «$1 204,50». */
export function formatUsd(value: number): string {
  return `$${nbsp(
    new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
      value,
    ),
  )}`;
}

/** Длительность из минут: «45 мин», «17 ч 53 мин», «2 дн 3 ч»; нет данных — «—». */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return t.common.none;
  const total = Math.max(0, Math.round(minutes));
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const mins = total % 60;
  const u = t.units;
  if (days)
    return [`${String(days)}${NBSP}${u.d}`, hours ? `${String(hours)}${NBSP}${u.h}` : ""]
      .filter(Boolean)
      .join(" ");
  if (hours)
    return [`${String(hours)}${NBSP}${u.h}`, mins ? `${String(mins)}${NBSP}${u.min}` : ""]
      .filter(Boolean)
      .join(" ");
  return `${String(mins)}${NBSP}${u.min}`;
}
