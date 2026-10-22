import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { type DateInput, type DateStyle, formatActivityTime, formatDate } from "./dates";
import {
  type MoneyFormatOptions,
  type NumberFormatOptions,
  type NumberInput,
  formatMoney,
  formatNumber,
  formatPercent,
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
      money: (value: NumberInput, options?: MoneyFormatOptions) =>
        formatMoney(value, { language, ...options }),
      percent: (value: NumberInput, options?: NumberFormatOptions) =>
        formatPercent(value, { language, ...options }),
      date: (value: DateInput, style: DateStyle = "date") => formatDate(value, { language, style }),
      activity: (value: DateInput, now?: Date) => formatActivityTime(value, { language, now }),
    }),
    [language],
  );
}
