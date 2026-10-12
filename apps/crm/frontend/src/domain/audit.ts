/**
 * «Что изменилось» в записи аудита — словами, без служебных ключей и кодов
 * (аудит UI U-07, дизайн-аудит 2026-10-11). Значения переводятся по смыслу поля.
 */
import type { AuditItem } from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatDate } from "../lib/time";
import { languageLabel, ownerModeLabel, roleLabel, stageLabel } from "./labels";

/** Справочники для подстановки имён вместо ID. */
export type AuditContext = {
  userName: (id: number) => string | undefined;
  productName: (key: string) => string | undefined;
};

export type AuditChange = { field: string; before?: string; after: string };

const F = t.audit.fields;
const USER_FIELDS = new Set(["assigned_user_id", "owner_user_id", "to_user_id", "actor_user_id"]);
const BOOLEAN_TEXT: Record<string, boolean> = {
  true: true,
  false: false,
  True: true,
  False: false,
};

const LANGS = new Set(["ru", "uz", "en"]);

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

/** Название поля: аудит → настройки → тексты бота; ключ — только крайний случай. */
export function fieldName(path: string): string {
  const parts = path.split(".");
  const last = parts.at(-1) ?? path;
  const isLang = parts.length > 1 && LANGS.has(last);
  const key = isLang ? (parts.at(-2) ?? last) : last;
  const base = F[key] ?? t.settings.fields[key] ?? t.settings.botTexts[key]?.label ?? key;
  return isLang ? `${base} (${languageLabel(last)})` : base;
}

function shorten(text: string): string {
  return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** Скаляр как текст; объект — JSON (не «[object Object]»). */
const asText = (value: unknown): string =>
  typeof value === "string" ? value : JSON.stringify(value);

/** Код или ссылка по смыслу поля; `null` — показать как есть. */
function codeValue(field: string, text: string, ctx: AuditContext): string | null {
  if (USER_FIELDS.has(field)) return ctx.userName(Number(text)) ?? `#${text}`;
  if (field === "client_id") return `${t.labels.entity["client"] ?? ""} #${text}`;
  if (field === "document_id") return `${t.audit.fields["document_id"] ?? ""} #${text}`;
  if (field === "note_id") return `#${text}`;
  if (field === "stage") return stageLabel(text).label;
  if (field === "owner_mode") return ownerModeLabel(text);
  if (field === "language") return languageLabel(text);
  if (field === "type") return t.clients.types[text] ?? text;
  if (field === "product" || field === "product_key") return ctx.productName(text) ?? text;
  if (field === "roles") return roleLabel(text);
  if (field === "weekdays") return t.settings.weekdays[Number(text)] ?? text;
  if (field === "doc_date" && /^\d{4}-\d{2}-\d{2}/.test(text)) return formatDate(text.slice(0, 10));
  return null;
}

/** Значение поля по-человечески. */
export function fieldValue(key: string, value: unknown, ctx: AuditContext): string {
  if (isEmpty(value)) return t.common.none;
  const field = key.split(".").at(-1) ?? key;
  if (typeof value === "boolean") return value ? t.common.yes : t.common.no;
  if (Array.isArray(value)) {
    const items = value.map((v) => fieldValue(field, v, ctx));
    return items.length ? items.join(", ") : t.common.none;
  }
  const text = asText(value);
  if (text in BOOLEAN_TEXT) return BOOLEAN_TEXT[text] ? t.common.yes : t.common.no;
  return codeValue(field, text, ctx) ?? shorten(text);
}

/** Вложенные объекты (настройки) — плоско: `greeting.ru`. */
function flatten(record: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(record).flatMap(([key, value]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      return value && typeof value === "object" && !Array.isArray(value)
        ? Object.entries(flatten(value as Record<string, unknown>, path))
        : [[path, value]];
    }),
  );
}

/** Только отличающиеся поля: «до → после» (или только «после» при создании). */
export function auditChanges(item: AuditItem, ctx: AuditContext): AuditChange[] {
  const before = flatten(item.before ?? {});
  const after = flatten(item.after ?? {});
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return keys
    .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
    .map((k) => {
      const change: AuditChange = { field: fieldName(k), after: fieldValue(k, after[k], ctx) };
      if (k in before) change.before = fieldValue(k, before[k], ctx);
      return change;
    });
}

/** Одной строкой: «Стадия: Новый → В работе; Ответственный: — → Анна». */
export function auditDiff(item: AuditItem, ctx: AuditContext): string {
  return auditChanges(item, ctx)
    .map((c) =>
      c.before === undefined ? `${c.field}: ${c.after}` : `${c.field}: ${c.before} → ${c.after}`,
    )
    .join("; ");
}
