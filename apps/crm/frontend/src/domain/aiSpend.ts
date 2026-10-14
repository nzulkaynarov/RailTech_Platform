/** «Расходы» по ансамблю (M3-CRM-09): подписи, период, строки таблиц — без React, с тестами. */
import type {
  AiBudgetOverrun,
  AiSpendReport,
  AiSpendRow,
  AiSystemBudget,
  GetAiSpendGroup,
} from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatNumber, formatUsd } from "../lib/format";
import { formatDate, tashkent } from "../lib/time";
import { roleLabel } from "./spend";

const A = t.aiSpend;

export type SliceGroup = Exclude<GetAiSpendGroup, "day">;
export const SLICE_GROUPS: SliceGroup[] = ["system", "feature", "model"];

/** Последние `days` суток по Ташкенту, включая сегодня (`from`/`to` для API). */
export function periodRange(days: number, now: Date = new Date()): { from: string; to: string } {
  const today = tashkent(now).startOf("day");
  return {
    from: today.subtract(days - 1, "day").format("YYYY-MM-DD"),
    to: today.format("YYYY-MM-DD"),
  };
}

export const systemLabel = (key: string): string => A.systems[key] ?? key.toUpperCase();
export const featureLabel = (key: string): string => A.features[key] ?? key;

/** Подпись строки разреза: система, функция или алиас модели («Диалог (dialog-model)»). */
export function sliceLabel(group: SliceGroup, key: string): string {
  if (group === "system") return systemLabel(key);
  if (group === "feature") return featureLabel(key);
  const role = roleLabel(key);
  return role === key ? key : `${role} (${key})`;
}

/** Доллары; меньше цента — до миллионных: журнал шлюза считает доли цента за вызов. */
export function usdPrecise(value: number): string {
  if (value > 0 && value < 0.01) return `$${formatNumber(value, 6)}`;
  return formatUsd(value);
}

/** «$0,42 из $2,00» или «$0,42, без лимита». */
export function budgetText(s: Pick<AiSystemBudget, "today_usd" | "daily_usd">): string {
  if (s.daily_usd <= 0) return A.noLimit.replace("{spent}", usdPrecise(s.today_usd));
  return A.of
    .replace("{spent}", usdPrecise(s.today_usd))
    .replace("{limit}", formatUsd(s.daily_usd));
}

/** Плитки систем: CRM и ERP всегда; «без тега» — только если такие вызовы были. */
export function systemTiles(report: AiSpendReport): AiSystemBudget[] {
  return report.systems.filter((s) => s.system !== "other" || s.period_calls > 0);
}

/** ERP не ходит в шлюз — вместо нулей показываем, что её ещё не подключили (M1-ERP-06). */
export const erpNotConnected = (report: AiSpendReport): boolean => !report.erp_connected;

export function overrunText(o: AiBudgetOverrun): string {
  return A.overrun
    .replace("{system}", systemLabel(o.system))
    .replace("{day}", formatDate(o.day))
    .replace("{spent}", usdPrecise(o.cost_usd))
    .replace("{limit}", formatUsd(o.daily_usd));
}

/** Системы в колонках таблицы «По дням»: CRM, ERP и прочие, если встречались. */
export function dayColumnsSystems(rows: AiSpendRow[]): string[] {
  const seen = new Set(rows.flatMap((r) => r.by_system.map((s) => s.system)));
  return ["crm", "erp", ...[...seen].filter((s) => s !== "crm" && s !== "erp").sort()];
}

export function systemCost(row: AiSpendRow, system: string): number {
  return row.by_system.find((s) => s.system === system)?.cost_usd ?? 0;
}

/** Сначала свежие дни — как в журнале; пустые дни остаются (видно, что ИИ не работал). */
export const daysNewestFirst = (rows: AiSpendRow[]): AiSpendRow[] => [...rows].reverse();

export const isEmptyReport = (report: AiSpendReport): boolean => report.totals.calls === 0;
