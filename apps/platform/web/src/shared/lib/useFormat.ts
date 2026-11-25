import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type DateInput,
  type DateStyle,
  formatActivityTime,
  formatDate,
  formatListDate,
  formatRowTime,
} from "./dates";
import {
  type MoneyFormatOptions,
  type NumberFormatOptions,
  type NumberInput,
  currencyLabel,
  formatMoney,
  formatNumber,
  formatPercent,
  formatQuantity,
} from "./money";

/** Форматирование чисел, сумм и дат с языком интерфейса (ru, uz, en) и часовым поясом компании. */
export function useFormat() {
  const { i18n } = useTranslation();
  const language = i18n.language;
  return useMemo(
    () => ({
      language,
      number: (value: NumberInput, options?: NumberFormatOptions) =>
        formatNumber(value, { language, ...options }),
      /** Количество: до трёх знаков, без хвостовых нулей («12,5 т»). */
      qty: (value: NumberInput) => formatQuantity(value, { language }),
      money: (value: NumberInput, options?: MoneyFormatOptions) =>
        formatMoney(value, { language, ...options }),
      /** Подпись валюты для поля и заголовка: `UZS` → «сум» / «so‘m», другая — код. */
      currency: (code?: string | null) => currencyLabel(code, language),
      percent: (value: NumberInput, options?: NumberFormatOptions) =>
        formatPercent(value, { language, ...options }),
      date: (value: DateInput, style: DateStyle = "date") => formatDate(value, { language, style }),
      activity: (value: DateInput, now?: Date) => formatActivityTime(value, { language, now }),
      /** Время в колонке таблицы: «сегодня 10:12», «вчера 09:24», «24.10.2026 11:50». */
      rowTime: (value: DateInput, now?: Date) => formatRowTime(value, { language, now }),
      /** Дата в строке списка без времени: «сегодня», «вчера» или «24.10.2026». */
      listDate: (value: DateInput, now?: Date) => formatListDate(value, { language, now }),
    }),
    [language],
  );
}
