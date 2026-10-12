/**
 * Плитки дашборда: что показывать крупно, куда ведёт клик и можно ли туда роли.
 * Чистые функции (дизайн-аудит 2026-10-11: иерархия метрик, ссылки без 403).
 */
import type { Dashboard, DealsSummary, PermissionsResponse } from "../api/generated/model";
import { allowed, sectionPermission } from "../app/providers/access";
import { leadFiltersToSearch } from "../hooks/leadFilters";
import { trend, type Trend } from "./dashboardCharts";
import { formatMoney } from "./deals";
import { t } from "../i18n/ru";
import { formatDuration, formatNumber, formatUsd } from "../lib/format";

/** Куда ведёт плитка: раздел Refine (для проверки прав) и адрес. */
export type TileTarget = { resource: string; path: string };
export type Tile = {
  key: string;
  title: string;
  /** Уже отформатировано (ru-RU): antd `Statistic` форматирует number по-английски. */
  value: string;
  target: TileTarget | null;
  /** Плитка видна только с этим правом (ресурс, действие); `undefined` — всем. */
  requires?: [string, string];
  /** Тренд к прошлому периоду той же длины (`Dashboard.previous`); нет данных — `null`. */
  trend?: Trend | null;
  /** Строка под числом (сумма выигрыша, подсказка). */
  hint?: string | null;
};

export const leadsPath = (filters: { stage?: string; from?: string; to?: string }) =>
  `/leads?${leadFiltersToSearch({ ...filters, page: 1 }).toString()}`;

/**
 * Ключевые бизнес-метрики (крупно) и операционные (мельче). «Сделок» ведёт в раздел
 * «Сделки» с фильтром «Выиграна» (ADR-0019): выигранный лид сразу становится «Клиентом»,
 * поэтому список лидов для этой плитки не подходит.
 */
export function dashboardTiles(
  data: Dashboard,
  period: { from: string; to: string },
  deals?: DealsSummary,
): { primary: Tile[]; secondary: Tile[] } {
  const totals = data.totals;
  const prev = data.previous ?? null;
  return {
    primary: [
      {
        key: "leads",
        title: t.dashboard.leads,
        value: formatNumber(totals.leads_created),
        target: { resource: "leads", path: leadsPath(period) },
        trend: trend(totals.leads_created, prev?.leads_created),
      },
      {
        key: "taken",
        title: t.dashboard.taken,
        value: formatNumber(totals.taken),
        target: null,
        trend: trend(totals.taken, prev?.taken),
      },
      {
        key: "won",
        title: t.dashboard.won,
        value: formatNumber(totals.won),
        target: { resource: "deals", path: "/deals?stage=won" },
        trend: trend(totals.won, prev?.won),
        hint: deals?.won_count ? wonSum(deals).value : null,
      },
      {
        key: "takeTime",
        title: t.dashboard.takeTime,
        value: formatDuration(totals.avg_take_minutes),
        target: null,
        trend: trend(totals.avg_take_minutes, prev?.avg_take_minutes),
      },
      {
        key: "cost",
        title: t.dashboard.cost,
        value: formatUsd(totals.cost_usd),
        target: { resource: "spend", path: "/spend" },
        requires: ["spend", "read"],
        trend: trend(totals.cost_usd, prev?.cost_usd),
      },
    ],
    secondary: [
      {
        key: "openEscalations",
        title: t.dashboard.openEscalations,
        value: formatNumber(data.open_escalations),
        target: { resource: "inbox", path: "/inbox" },
      },
      {
        key: "escalations",
        title: t.dashboard.escalations,
        value: formatNumber(totals.escalations),
        target: null,
        trend: trend(totals.escalations, prev?.escalations),
      },
      {
        key: "gaps",
        title: t.dashboard.gaps,
        value: formatNumber(data.open_gaps),
        target: { resource: "gaps", path: "/gaps" },
        requires: ["kb", "write"],
      },
    ],
  };
}

/**
 * Плитки, которые роль может видеть: стоимость моделей — с правом на «Расходы»,
 * пробелы знаний — тем, кто их разбирает. Одно правило для всех ролей (аудит 2026-10-12).
 */
export function visibleTiles(tiles: Tile[], matrix: PermissionsResponse | undefined): Tile[] {
  return tiles.filter((tile) => !tile.requires || allowed(matrix, ...tile.requires));
}

/** Адрес плитки, только если у роли есть право на раздел (как в RouteGuard); иначе `null`. */
export function tileLink(target: TileTarget | null, matrix: PermissionsResponse | undefined) {
  if (!target) return null;
  const permission = sectionPermission(target.resource);
  if (!permission) return target.path;
  return allowed(matrix, permission[0], permission[1]) ? target.path : null;
}

/** Причины передач по убыванию; доля — от максимума (ширина полосы). */
export function reasonBars(
  data: Record<string, number>,
): { code: string; value: number; percent: number }[] {
  const max = Math.max(1, ...Object.values(data));
  return Object.entries(data)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([code, value]) => ({ code, value, percent: Math.round((value / max) * 100) }));
}

/**
 * Сумма выигрыша: без сумм — «—» и подсказка, сколько сделок без суммы; частичная сумма
 * помечается как неполная (аудит 2026-10-12: «$0» при неуказанных суммах вводил в заблуждение).
 */
export function wonSum(data: DealsSummary): { value: string; hint: string | null } {
  const missing = data.won_without_amount ?? 0;
  const known = data.won_count - missing;
  const n = String(missing);
  if (!data.won_count) return { value: t.common.none, hint: null };
  if (!known) return { value: t.common.none, hint: t.deals.wonSumNone.replace("{n}", n) };
  const value = data.won_amounts
    .filter((s) => Number(s.amount) > 0)
    .map((s) => formatMoney(s.amount, s.currency))
    .join(" · ");
  return {
    value: value || t.common.none,
    hint: missing ? t.deals.wonSumMissing.replace("{n}", n) : null,
  };
}
