import type { AuditItem } from "../api/generated/model";
import { stageLabel } from "./labels";

const show = (key: string, value: unknown): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "stage" && typeof value === "string") return stageLabel(value).label;
  return typeof value === "string" ? value : JSON.stringify(value);
};

/** Что изменилось в записи аудита: только отличающиеся поля, «до → после». */
export function auditDiff(item: AuditItem): string {
  const before = item.before ?? {};
  const after = item.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return keys
    .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
    .map((k) =>
      k in before
        ? `${k}: ${show(k, before[k])} → ${show(k, after[k])}`
        : `${k}: ${show(k, after[k])}`,
    )
    .join("; ");
}
