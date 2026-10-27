import type { IntegrationStatus, ServiceState } from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";

/** Уровни статуса -> цвет тега; слово есть всегда (SPEC-v3 §5.2). */
export const LEVEL_TONE: Record<IntegrationStatus, StatusTone> = {
  ok: "green",
  warn: "gold",
  fail: "red",
  unknown: "blue",
  off: "default",
};

/** Состояние словом (SPEC-v3 §5.2: не только цвет). «Ожидаемо на стенде» и «Выключено намеренно» — серые. */
export const STATE_TONE: Record<ServiceState, StatusTone> = {
  ok: "green",
  broken: "red",
  unstable: "gold",
  degraded: "gold",
  not_configured: "default",
  disabled: "default",
  expected: "default",
  not_checked: "blue",
};
