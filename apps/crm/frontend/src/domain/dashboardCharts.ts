/**
 * Данные графиков дашборда и «Расходов» (`@ant-design/plots`, UX волна 4): ряды в длинном
 * формате (день · серия · значение), тренд к прошлому периоду, пустые состояния и текстовые
 * сводки для экранных дикторов. Чистые функции — без React и без библиотеки графиков.
 */
import type {
  DailyStat,
  DealDay,
  ReasonCount,
  SpendDay,
  SpendReport,
  SpendSlice,
} from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatNumber } from "../lib/format";
import { reasonLabel, STAGE_ORDER, stageLabel } from "./labels";
import { purposeLabel } from "./spend";

export type Point = { day: string; series: string; value: number };
export type Slice = { label: string; value: number };

/** «2026-10-12» → «12.10»: короткая подпись оси без зависимости от часового пояса браузера. */
export function shortDay(day: string): string {
  const [, month, date] = day.split("-");
  return `${date ?? ""}.${month ?? ""}`;
}

function long<T extends { day: string }>(rows: T[], fields: [keyof T, string][]): Point[] {
  return rows.flatMap((row) =>
    fields.map(([field, series]) => ({
      day: shortDay(row.day),
      series,
      value: Number(row[field] ?? 0),
    })),
  );
}

const F = t.charts.flowSeries;
const B = t.charts.botSeries;

export const flowPoints = (daily: DailyStat[]): Point[] =>
  long(daily, [
    ["leads_created", F.leads ?? ""],
    ["escalations", F.escalations ?? ""],
    ["taken", F.taken ?? ""],
    ["won", F.won ?? ""],
  ]);

export const botPoints = (daily: DailyStat[]): Point[] =>
  long(daily, [
    ["bot_answers", B.answers ?? ""],
    ["escalations", B.escalations ?? ""],
  ]);

export const dealPoints = (daily: DealDay[]): Point[] =>
  long(daily, [
    ["won", t.charts.dealSeries.won ?? ""],
    ["lost", t.charts.dealSeries.lost ?? ""],
  ]);

/** Стек «работа/тесты»; серия тестов — только если тесты были (как в таблице). */
export function spendPoints(series: SpendDay[], withTests: boolean): Point[] {
  const S = t.charts.spendSeries;
  return long(series, [
    ["work_usd", S.work ?? ""],
    ...(withTests ? [["test_usd", S.test ?? ""] as [keyof SpendDay, string]] : []),
  ]);
}

/** Все стадии по порядку, включая нулевые: пустая стадия — тоже сигнал. */
export const funnelSlices = (funnel: Record<string, number>): Slice[] =>
  STAGE_ORDER.map((stage) => ({ label: stageLabel(stage).label, value: funnel[stage] ?? 0 }));

export const reasonSlices = (reasons: Record<string, number>): Slice[] =>
  Object.entries(reasons)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([code, n]) => ({ label: reasonLabel(code), value: n }));

export const lostSlices = (rows: ReasonCount[]): Slice[] =>
  rows.filter((r) => r.count > 0).map((r) => ({ label: r.reason, value: r.count }));

export const purposeSlices = (rows: SpendSlice[]): Slice[] =>
  rows
    .filter((r) => r.cost_usd > 0)
    .map((r) => ({ label: purposeLabel(r.key), value: Number(r.cost_usd.toFixed(4)) }));

/** Пусто, если нет ни одного ненулевого значения: график из нулей ничего не говорит. */
export const isEmpty = (rows: { value: number }[]): boolean => !rows.some((r) => r.value > 0);

export type Trend = { direction: "up" | "down" | "flat"; text: string };

/**
 * Тренд к прошлому периоду той же длины. Нет прошлого периода — нет тренда; был 0 —
 * процент не считается (деление на ноль), пишем «в прошлом периоде — 0».
 */
export function trend(
  current: number | null | undefined,
  previous: number | null | undefined,
): Trend | null {
  if (current === null || current === undefined) return null;
  if (previous === null || previous === undefined) return null;
  if (previous === 0) {
    return current === 0
      ? { direction: "flat", text: t.charts.trendFlat }
      : { direction: "up", text: t.charts.trendNew };
  }
  const pct = Math.round(((current - previous) / previous) * 100);
  if (pct === 0) return { direction: "flat", text: t.charts.trendFlat };
  const text = (pct > 0 ? t.charts.trendUp : t.charts.trendDown).replace(
    "{n}",
    String(Math.abs(pct)),
  );
  return { direction: pct > 0 ? "up" : "down", text };
}

/** Текстовая альтернатива графику (aria-label): заголовок и до 8 пар «подпись — число». */
export function summarize(title: string, slices: Slice[], format = formatNumber): string {
  const items = slices
    .slice(0, 8)
    .map((s) => `${s.label} — ${format(s.value)}`)
    .join("; ");
  return t.charts.summary.replace("{title}", title).replace("{items}", items || t.charts.empty);
}

/** Сумма ряда по сериям — для сводки линейного графика и столбцов. */
export function seriesTotals(points: Point[]): Slice[] {
  const totals = new Map<string, number>();
  for (const p of points) totals.set(p.series, (totals.get(p.series) ?? 0) + p.value);
  return [...totals].map(([label, value]) => ({ label, value }));
}

export type LimitRow = {
  title: string;
  ranges: number[];
  measures: number[];
  targets: number[];
};

/**
 * Провайдеры и мягкий бюджет «сегодня» в процентах от своего лимита: у провайдеров разные
 * лимиты, общая ось в долларах сплющила бы маленькие. Без лимита — строки нет.
 */
export function limitRows(report: SpendReport): LimitRow[] {
  const rows = [
    ...report.providers.map((p) => ({ title: p.provider, spent: p.spent_usd, limit: p.limit_usd })),
    { title: t.spend.softBudget, spent: report.today_usd, limit: report.daily_usd },
  ];
  return rows
    .filter((r) => r.limit > 0)
    .map((r) => ({
      title: r.title,
      ranges: [100, 80],
      measures: [Math.round((r.spent / r.limit) * 100)],
      targets: [100],
    }));
}

/** Тёмный ли фон (`#rrggbb`/`#rgb`): тема графиков следует теме antd (classic / classicDark). */
export function isDarkColor(color: string): boolean {
  const hex = color.replace("#", "");
  const full = hex.length === 3 ? hex.replace(/./g, (c) => c + c) : hex.slice(0, 6);
  const n = Number.parseInt(full, 16);
  if (Number.isNaN(n) || full.length !== 6) return false;
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;
}
