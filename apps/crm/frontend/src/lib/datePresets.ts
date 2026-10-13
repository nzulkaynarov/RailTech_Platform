/**
 * Быстрый выбор периода для `DatePicker.RangePicker presets` (antd): «Сегодня · Вчера · 7 дней ·
 * 30 дней · Этот месяц · Прошлый месяц». «Сегодня» — по Ташкенту (CLAUDE.md §11), значения —
 * дни без времени, как и у ручного выбора в фильтрах.
 */
import dayjs, { type Dayjs } from "dayjs";

import { t } from "../i18n/ru";
import { tashkent } from "./time";

export type RangePreset = { label: string; value: [Dayjs, Dayjs] };

export function rangePresets(now: Date | string = new Date()): RangePreset[] {
  const today = dayjs(tashkent(now).format("YYYY-MM-DD"));
  const yesterday = today.subtract(1, "day");
  const lastMonth = today.subtract(1, "month");
  const L = t.datePresets;
  return [
    { label: L.today, value: [today, today] },
    { label: L.yesterday, value: [yesterday, yesterday] },
    { label: L.last7, value: [today.subtract(6, "day"), today] },
    { label: L.last30, value: [today.subtract(29, "day"), today] },
    { label: L.thisMonth, value: [today.startOf("month"), today] },
    { label: L.lastMonth, value: [lastMonth.startOf("month"), lastMonth.endOf("month")] },
  ];
}
