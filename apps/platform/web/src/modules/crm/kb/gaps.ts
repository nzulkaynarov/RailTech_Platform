import type { KbGapStatus } from "../../../shared/api/generated/model";

import { parseId } from "./refresh";

export const PAGE_SIZE = 50;
export const GAP_STATUSES: readonly KbGapStatus[] = ["open", "resolved", "ignored"];

/** Номер лида L-NNNN (SPEC-v3 §2.2): id лида CRM с нулями слева до четырёх знаков. */
export function leadNumber(id: number): string {
  return `L-${String(id).padStart(4, "0")}`;
}

/** Номер страницы списка пробелов из `?page=`; по умолчанию первая. */
export function gapPageParam(value: string | null): number {
  const page = parseId(value);
  return page === null ? 1 : Math.min(page, 10_000);
}

export function gapStatusParam(value: string | null): KbGapStatus {
  return (GAP_STATUSES as readonly string[]).includes(value ?? "")
    ? (value as KbGapStatus)
    : "open";
}
