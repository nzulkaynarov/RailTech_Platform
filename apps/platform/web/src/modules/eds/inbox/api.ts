import { ApiError } from "../../../shared/api/errors";
import type { LetterStatus } from "../../../shared/api/generated/model";
import { missingSectionName } from "../../../shared/lib/permissionSection";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import { LETTER_KEYS, useInvalidatePrefixes } from "../refreshKeys";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Письмо в адресе API: UUID как есть, бизнес-номер `ВХ-104/26` — закодированным (в номере есть «/»). */
export function letterRef(idOrNumber: string): string {
  return UUID.test(idOrNumber) ? idOrNumber.toLowerCase() : encodeURIComponent(idOrNumber);
}

/** Путь карточки письма в SPA: бизнес-номер, а не внутренний id (SPEC-v3 §2.2). */
export function letterPath(number: string): string {
  return `/eds/inbox/${encodeURIComponent(number)}`;
}

/**
 * Рабочий экран поручения по письму (P8b): исполнитель, «ознакомить», автор резолюции — по UUID письма
 * (`/eds/tasks/<uuid>`): по номеру BFF ищет письмо через реестр, которого у исполнителя может не быть.
 */
export function tasksPath(letterId: string): string {
  return `/eds/tasks/${encodeURIComponent(letterId)}`;
}

export const STATUS_FILTERS: readonly LetterStatus[] = [
  "awaiting_resolution",
  "resolved",
  "returned",
  "rejected",
];

/** После действия сбрасываются письма, документы (ответ-ИСХ), очередь и счётчики (`LETTER_KEYS`). */
export function useRefreshLetters(): () => Promise<void> {
  return useInvalidatePrefixes(LETTER_KEYS);
}

export type Reason =
  | "due_in_past"
  | "not_active_employee"
  | "duplicate"
  | "invalid_state"
  | "eds_not_granted"
  | "track_mismatch"
  | "not_allowed_for_info"
  | "urgent_not_extendable"
  | "extension_pending"
  | "not_executor"
  | "not_resolution_author"
  | "no_pending_extension"
  | "report_required"
  | "outgoing_linked_elsewhere"
  | "not_found"
  | "forbidden"
  | "unavailable"
  | "validation"
  | "unknown";

const KNOWN: ReadonlySet<string> = new Set<Reason>([
  "due_in_past",
  "not_active_employee",
  "duplicate",
  "invalid_state",
  "eds_not_granted",
  // P8b: поручения по входящим
  "track_mismatch",
  "not_allowed_for_info",
  "urgent_not_extendable",
  "extension_pending",
  "not_executor",
  "not_resolution_author",
  "no_pending_extension",
  "report_required",
  "outgoing_linked_elsewhere",
  "not_found",
]);

/** Причина отказа словарным ключом: подкод EDS (`details.reason`), иначе по статусу ответа. */
export function reasonOf(error: unknown): Reason {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && KNOWN.has(reason)) return reason as Reason;
    if (error.status === 403) return "forbidden";
    if (error.status === 409) return "invalid_state";
    if (error.status === 422) return "validation";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  // Сеть оборвалась до ответа (`fetch` бросает TypeError).
  return error instanceof TypeError ? "unavailable" : "unknown";
}

/**
 * Причина отказа текстом для `…: {{reason}}`: у 403 с правом — «нет доступа к разделу «…»» (раздел из каталога
 * `platform-rbac.yaml`), иначе слово из словаря `form.reasons`.
 */
export function reasonText(
  t: (key: string, options?: Record<string, unknown>) => string,
  error: unknown,
): string {
  const reason = reasonOf(error);
  const section = reason === "forbidden" ? missingSectionName(error) : null;
  return section ? t("form.reasons.forbiddenSection", { section }) : t(`form.reasons.${reason}`);
}

/** Поля формы, которые EDS назвал в `details.fields` (`due`, `assignees`, …). */
export function fieldsOf(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const fields = error.details["fields"];
  return Array.isArray(fields) ? fields.filter((f): f is string => typeof f === "string") : [];
}

/** Параметры адреса с правками: `null` удаляет параметр, остальные (`status`, `panel`) сохраняются. */
export function withParams(
  current: URLSearchParams,
  changes: Record<string, string | null>,
): string {
  const next = new URLSearchParams(current);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key);
    else next.set(key, value);
  }
  const text = next.toString();
  return text ? `?${text}` : "";
}

/** Календарная дата в поясе компании (`2026-10-27`), со сдвигом в днях. */
export function companyDate(offsetDays = 0, now: number = Date.now()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(now + offsetDays * 86_400_000));
}
