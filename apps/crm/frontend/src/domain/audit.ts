/**
 * «Что изменилось» в записи аудита — словами, без служебных ключей и кодов
 * (аудит UI U-07, дизайн-аудит 2026-10-11). Значения переводятся по смыслу поля.
 */
import type { AuditItem } from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatDate, formatDateTime } from "../lib/time";
import { entityLabel, languageLabel, ownerModeLabel, roleLabel, stageLabel } from "./labels";
import { roleLabel as modelRoleLabel, usd } from "./spend";

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
  const base =
    F[key] ??
    t.auditUi.fields[key] ??
    t.settings.fields[key] ??
    t.settings.botTexts[key]?.label ??
    key;
  return isLang ? `${base} (${languageLabel(last)})` : base;
}

function shorten(text: string): string {
  return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** Скаляр как текст; объект — JSON (не «[object Object]»). */
const asText = (value: unknown): string =>
  typeof value === "string" ? value : JSON.stringify(value);

const ID_FIELDS = new Set(["note_id", "contact_id", "telegram_identity_id"]);
const DATE_FIELDS = new Set(["doc_date", "expected_close_date"]);

/** Код или ссылка по смыслу поля; `null` — показать как есть. */
function codeValue(field: string, text: string, ctx: AuditContext, entity?: string): string | null {
  const known = t.auditUi.values[field]?.[text];
  if (known) return known;
  if (USER_FIELDS.has(field)) return ctx.userName(Number(text)) ?? `#${text}`;
  if (field === "client_id") return `${t.labels.entity["client"] ?? ""} #${text}`;
  if (field === "document_id") return `${t.audit.fields["document_id"] ?? ""} #${text}`;
  if (field === "lead_id") return `${entityLabel("lead")} #${text}`;
  if (ID_FIELDS.has(field)) return `#${text}`;
  if (field === "cost_usd" && !Number.isNaN(Number(text))) return usd(Number(text));
  if (field === "alias") return modelRoleLabel(text);
  if (field === "requested_at") return formatDateTime(text);
  if (field === "stage" && entity === "deal") return t.deals.stages[text] ?? text;
  if (field === "stage") return stageLabel(text).label;
  if (field === "decision") return t.sandbox.decisions[text] ?? text;
  if (field === "owner_mode") return ownerModeLabel(text);
  if (field === "language") return languageLabel(text);
  if (field === "type") return t.clients.types[text] ?? text;
  if (field === "product" || field === "product_key") return ctx.productName(text) ?? text;
  if (field === "roles") return roleLabel(text);
  if (field === "weekdays") return t.settings.weekdays[Number(text)] ?? text;
  if (DATE_FIELDS.has(field) && /^\d{4}-\d{2}-\d{2}/.test(text)) {
    return formatDate(text.slice(0, 10));
  }
  return null;
}

/** Значение поля по-человечески. */
export function fieldValue(
  key: string,
  value: unknown,
  ctx: AuditContext,
  entity?: string,
): string {
  if (isEmpty(value)) return t.common.none;
  const field = key.split(".").at(-1) ?? key;
  if (typeof value === "boolean") return value ? t.common.yes : t.common.no;
  if (Array.isArray(value)) {
    const items = value.map((v) => fieldValue(field, v, ctx, entity));
    return items.length ? items.join(", ") : t.common.none;
  }
  const text = asText(value);
  if (text in BOOLEAN_TEXT) return BOOLEAN_TEXT[text] ? t.common.yes : t.common.no;
  return codeValue(field, text, ctx, entity) ?? shorten(text);
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
      const value = (v: unknown) => fieldValue(k, v, ctx, item.entity_type);
      const change: AuditChange = { field: fieldName(k), after: value(after[k]) };
      if (k in before) change.before = value(before[k]);
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

/** Объект записи словами: «Модель ИИ «Диалог»», имя пользователя; иначе — «Тип #id». */
export function entityText(
  type: string,
  id: string | null | undefined,
  ctx: AuditContext,
): string | undefined {
  if (!id) return undefined;
  const known = t.auditUi.objects[`${type}:${id}`];
  if (known) return known;
  if (type === "sandbox") return t.auditUi.sandbox;
  if (type === "model") return t.auditUi.modelEntity.replace("{role}", modelRoleLabel(id));
  if (type === "user") {
    const name = ctx.userName(Number(id));
    return name ? `${entityLabel(type)}: ${name}` : undefined;
  }
  return undefined;
}
