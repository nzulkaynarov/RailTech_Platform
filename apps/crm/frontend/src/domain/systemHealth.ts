/** Итог «Состояния системы» для шапки и баннера админа — без React, с тестами. */
import type { ComponentStatusOut, SystemStatusOut } from "../api/generated/model";
import { t } from "../i18n/ru";

export type HeaderTone = "ok" | "warn" | "fail";
export type HeaderHealth = { tone: HeaderTone; label: string };

/** Компоненты, без которых клиенты не получают ответа, — баннер на всех страницах. */
const CRITICAL = new Set(["bot", "model:dialog-model"]);
const ORDER: Record<ComponentStatusOut["status"], number> = { fail: 0, warn: 1, unknown: 2, ok: 3 };

function shortName(c: ComponentStatusOut): string {
  return t.health.short[c.key] ?? c.title;
}

/** «1 предупреждение», «2 предупреждения», «5 предупреждений». */
export function warningsText(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const forms = t.health.warnings;
  let form = forms.many;
  if (mod10 === 1 && mod100 !== 11) form = forms.one;
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) form = forms.few;
  return form.replace("{n}", String(n));
}

export function headerHealth(status: SystemStatusOut): HeaderHealth {
  const fails = status.components.filter((c) => c.status === "fail");
  if (fails.length) {
    const names = fails.map(shortName).join(", ");
    return { tone: "fail", label: t.health.fail.replace("{names}", names) };
  }
  const warns = status.components.filter((c) => c.status === "warn").length;
  if (warns) return { tone: "warn", label: warningsText(warns) };
  return { tone: "ok", label: t.health.ok };
}

/** Сбои, о которых админ должен узнать сразу: бот или модель диалога. */
export function criticalFailures(status: SystemStatusOut): ComponentStatusOut[] {
  return status.components.filter((c) => c.status === "fail" && CRITICAL.has(c.key));
}

/** Сбой → внимание → нет данных → норма (бэкенд сортирует так же; порядок стабилен). */
export function bySeverity(components: ComponentStatusOut[]): ComponentStatusOut[] {
  return [...components].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
}
