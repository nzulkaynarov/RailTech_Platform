/** «Внешние сервисы» (M3-CRM-12): группы, порядок, подписи метрик — без React, с тестами. */
import type {
  ExternalServiceOut,
  ExternalServiceOutMetrics,
  ExternalServicesSummary,
} from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatNumber, formatUsd } from "../lib/format";
import { formatDateTime } from "../lib/time";

export type ServiceStatus = ExternalServiceOut["status"];
export type GroupKey = "attention" | "disabled" | "working" | "idle" | "erp";
export type ServiceGroup = { key: GroupKey; services: ExternalServiceOut[] };
export type MetricRow = { key: string; label: string; value: string };

const ORDER: Record<ServiceStatus, number> = { fail: 0, warn: 1, unknown: 2, off: 3, ok: 4 };
const GROUPS: GroupKey[] = ["attention", "disabled", "working", "idle", "erp"];

export function groupOf(service: ExternalServiceOut): GroupKey {
  if (service.source === "erp") return "erp";
  if (service.switch?.disabled) return "disabled";
  if (service.status === "fail" || service.status === "warn" || service.stale) return "attention";
  if (service.status === "ok") return "working";
  return "idle";
}

/** Группы для экрана: сначала то, что требует внимания; порядок внутри — сбой → внимание → … */
export function groupServices(services: ExternalServiceOut[]): ServiceGroup[] {
  return GROUPS.map((key) => ({
    key,
    services: services
      .filter((s) => groupOf(s) === key)
      .sort((a, b) => ORDER[a.status] - ORDER[b.status]),
  })).filter((g) => g.services.length > 0);
}

/** Сервисы, выключенные вручную, — для баннера над списком. */
export const manuallyDisabled = (services: ExternalServiceOut[]): ExternalServiceOut[] =>
  services.filter((s) => s.switch?.disabled);

/** Счётчики сводки в порядке важности; нулевые не показываются (кроме «В норме»). */
export function summaryItems(
  summary: ExternalServicesSummary,
): { key: keyof ExternalServicesSummary; count: number }[] {
  const keys: (keyof ExternalServicesSummary)[] = [
    "fail",
    "warn",
    "ok",
    "unknown",
    "off",
    "disabled",
  ];
  return keys
    .map((key) => ({ key, count: summary[key] }))
    .filter((item) => item.count > 0 || item.key === "ok");
}

/** Доля 0..1 → «99,5 %»; нет данных — «—». */
export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return t.common.none;
  return `${formatNumber(value * 100, 1)} %`;
}

/** Байты → «12 МБ», «1,5 ГБ». */
export function formatBytes(bytes: number): string {
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${formatNumber(value, unit === 0 ? 0 : 1)} ${units[unit] ?? ""}`;
}

function metricValue(key: string, value: number | string): string {
  if (typeof value === "string") return key === "not_after" ? formatDateTime(value) : value;
  if (key.endsWith("_usd")) return formatUsd(value);
  if (key === "error_rate_24h") return percent(value);
  if (key.endsWith(".bytes")) return formatBytes(value);
  if (key.startsWith("p95_ms")) return `${formatNumber(value)} мс`;
  return formatNumber(value, 1);
}

function metricLabel(key: string): string | null {
  const bucket = /^bucket\.(.+)\.(bytes|objects)$/.exec(key);
  if (bucket) {
    const template =
      bucket[2] === "bytes"
        ? t.externalServices.metrics["bucketBytes"]
        : t.externalServices.metrics["bucketObjects"];
    return template ? template.replace("{name}", bucket[1] ?? "") : null;
  }
  return t.externalServices.metrics[key] ?? null;
}

/** Метрики сервиса с подписями по-русски; неизвестные ключи и пустые значения пропускаются. */
export function metricRows(metrics: ExternalServiceOutMetrics): MetricRow[] {
  const rows: MetricRow[] = [];
  for (const [key, raw] of Object.entries(metrics)) {
    if (raw === null || raw === "") continue;
    const label = metricLabel(key);
    if (!label) continue;
    rows.push({ key, label, value: metricValue(key, raw) });
  }
  return rows;
}

/** Длительность из секунд → «12 мин», «2 ч 5 мин». */
export function durationFromSeconds(seconds: number | null | undefined): number | null {
  return seconds === null || seconds === undefined ? null : seconds / 60;
}
