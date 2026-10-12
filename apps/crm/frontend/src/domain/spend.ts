/** Подписи и расчёты экранов «Расходы» и «Модели ИИ» — без React, с тестами. */
import { t } from "../i18n/ru";

/** Доллары: мелкие суммы — до десятых цента, чтобы не показывать «$0.00» при реальном расходе. */
export function usd(value: number): string {
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

/** Доля лимита для полосы: 0–100; лимит 0 — «без лимита» (null). */
export function limitPercent(spent: number, limit: number): number | null {
  if (limit <= 0) return null;
  return Math.min(100, Math.round((spent / limit) * 100));
}

export type BarStatus = "normal" | "active" | "exception";

/** > 80 % — предупреждение (как алерт бюджета), ≥ 100 % — превышение. */
export function barStatus(percent: number | null): BarStatus {
  if (percent === null || percent <= 80) return "normal";
  return percent >= 100 ? "exception" : "active";
}

export const purposeLabel = (key: string): string => t.spend.purposes[key] ?? key;
export const kindLabel = (key: string): string => t.spend.kinds[key] ?? key;
export const roleLabel = (alias: string): string => t.models.roles[alias] ?? alias;
export const healthLabel = (health: string): string => t.models.health[health] ?? health;

/** Ссылки на страницы расходов в консолях провайдеров (фактические счета). */
export const PROVIDER_CONSOLES: { label: string; href: string }[] = [
  { label: t.spend.consoleAnthropic, href: "https://console.anthropic.com/settings/usage" },
  { label: t.spend.consoleGemini, href: "https://aistudio.google.com/usage" },
];
