/**
 * Плитки дашборда: что показывать крупно, куда ведёт клик и можно ли туда роли.
 * Чистые функции (дизайн-аудит 2026-10-11: иерархия метрик, ссылки без 403).
 */
import type { Dashboard, PermissionsResponse } from "../api/generated/model";
import { allowed, sectionPermission } from "../app/providers/access";
import { leadFiltersToSearch } from "../hooks/leadFilters";
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
};

export const leadsPath = (filters: { stage?: string; from?: string; to?: string }) =>
  `/leads?${leadFiltersToSearch({ ...filters, page: 1 }).toString()}`;

const percent = (share: number | null) =>
  share === null ? t.common.none : `${String(Math.round(share * 100))}%`;

/**
 * Ключевые бизнес-метрики (крупно) и операционные (мельче). «Сделок» ведёт в раздел
 * «Сделки» с фильтром «Выиграна» (ADR-0019): выигранный лид сразу становится «Клиентом»,
 * поэтому список лидов для этой плитки не подходит.
 */
export function dashboardTiles(
  data: Dashboard,
  period: { from: string; to: string },
): { primary: Tile[]; secondary: Tile[] } {
  const totals = data.totals;
  return {
    primary: [
      {
        key: "leads",
        title: t.dashboard.leads,
        value: formatNumber(totals.leads_created),
        target: { resource: "leads", path: leadsPath(period) },
      },
      { key: "taken", title: t.dashboard.taken, value: formatNumber(totals.taken), target: null },
      {
        key: "won",
        title: t.dashboard.won,
        value: formatNumber(totals.won),
        target: { resource: "deals", path: "/deals?stage=won" },
      },
      {
        key: "takeTime",
        title: t.dashboard.takeTime,
        value: formatDuration(totals.avg_take_minutes),
        target: null,
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
      },
      {
        key: "gaps",
        title: t.dashboard.gaps,
        value: formatNumber(data.open_gaps),
        target: { resource: "gaps", path: "/gaps" },
        requires: ["kb", "write"],
      },
      {
        key: "fallback",
        title: t.dashboard.fallback,
        value: percent(data.fallback_share),
        target: null,
      },
      {
        key: "cost",
        title: t.dashboard.cost,
        value: formatUsd(totals.cost_usd),
        target: null,
        requires: ["spend", "read"],
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
