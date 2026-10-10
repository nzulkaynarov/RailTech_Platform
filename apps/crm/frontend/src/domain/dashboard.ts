/**
 * Плитки дашборда: что показывать крупно, куда ведёт клик и можно ли туда роли.
 * Чистые функции (дизайн-аудит 2026-10-11: иерархия метрик, ссылки без 403).
 */
import type { Dashboard, PermissionsResponse } from "../api/generated/model";
import { allowed, sectionPermission } from "../app/providers/access";
import { leadFiltersToSearch } from "../hooks/leadFilters";
import { t } from "../i18n/ru";

/** Куда ведёт плитка: раздел Refine (для проверки прав) и адрес. */
export type TileTarget = { resource: string; path: string };
export type Tile = {
  key: string;
  title: string;
  value: string | number;
  target: TileTarget | null;
};

export const leadsPath = (filters: { stage?: string; from?: string; to?: string }) =>
  `/leads?${leadFiltersToSearch({ ...filters, page: 1 }).toString()}`;

const percent = (share: number | null) =>
  share === null ? t.common.none : `${String(Math.round(share * 100))}%`;

/**
 * Ключевые бизнес-метрики (крупно) и операционные (мельче). «Сделок» без ссылки:
 * выигранные сделки сразу переходят в стадию «Клиент», а фильтра «закрыта в периоде»
 * у списка лидов нет — клик открыл бы пустой или неверный список.
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
        value: totals.leads_created,
        target: { resource: "leads", path: leadsPath(period) },
      },
      { key: "taken", title: t.dashboard.taken, value: totals.taken, target: null },
      { key: "won", title: t.dashboard.won, value: totals.won, target: null },
      {
        key: "takeTime",
        title: t.dashboard.takeTime,
        value: totals.avg_take_minutes ?? t.common.none,
        target: null,
      },
    ],
    secondary: [
      {
        key: "openEscalations",
        title: t.dashboard.openEscalations,
        value: data.open_escalations,
        target: { resource: "inbox", path: "/inbox" },
      },
      {
        key: "escalations",
        title: t.dashboard.escalations,
        value: totals.escalations,
        target: null,
      },
      {
        key: "gaps",
        title: t.dashboard.gaps,
        value: data.open_gaps,
        target: { resource: "gaps", path: "/gaps" },
      },
      {
        key: "fallback",
        title: t.dashboard.fallback,
        value: percent(data.fallback_share),
        target: null,
      },
      { key: "cost", title: t.dashboard.cost, value: totals.cost_usd.toFixed(2), target: null },
    ],
  };
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
