import type { IntegrationStatus } from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";

/** Уровни статуса -> цвет тега; слово есть всегда (SPEC-v3 §5.2). */
export const LEVEL_TONE: Record<IntegrationStatus, StatusTone> = {
  ok: "green",
  warn: "gold",
  fail: "red",
  unknown: "blue",
  off: "default",
};
