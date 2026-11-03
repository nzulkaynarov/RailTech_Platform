/**
 * Раскладка настроек бота: где какой раздел (SET-IA), группы текстов бота, выбор виджета поля. Чистые функции — без React
 * и сети. Ключи разделов и текстов приходят из CRM; неизвестные (новые в CRM) попадают в «Другое» и не теряются.
 */
import { type JsonSchema, kindOf } from "./schemaForm";

/**
 * Где живёт каждый раздел настроек бота после SET-IA (ресёрч «Настройки» §4.1): не вкладками внутри «Telegram-бота», а на
 * странице своей группы Настроек. Ключ страницы — ключ раздела модуля admin (`telegram.<вкладка>` — вкладка страницы
 * Telegram). Раздел, которого здесь нет (новый в CRM), попадает в «Telegram · Поведение» и не теряется.
 */
export const BOT_PLACEMENT: Readonly<Record<string, string>> = {
  texts: "telegram.texts",
  kb: "telegram.kb",
  bot: "telegram.behavior",
  qualification: "telegram.behavior",
  stop_words: "telegram.behavior",
  competitors: "telegram.behavior",
  company: "company",
  business_hours: "timing",
  escalation: "timing",
  web_form: "forms",
  notifications: "notifications",
  service_alerts: "notifications",
  deals: "dictionaries",
  budget: "spend",
};

/** Порядок разделов внутри страницы — порядок `BOT_PLACEMENT`; неизвестные — в конце «Поведения». */
export function botSectionsFor(page: string, available: readonly string[]): string[] {
  const order = Object.keys(BOT_PLACEMENT);
  const placed = order.filter((key) => BOT_PLACEMENT[key] === page && available.includes(key));
  if (page !== "telegram.behavior") return placed;
  return [...placed, ...available.filter((key) => BOT_PLACEMENT[key] === undefined)];
}

const TEXT_GROUPS: Record<string, readonly string[]> = {
  welcome: [
    "greeting",
    "consent",
    "consent_button",
    "consent_decline_button",
    "consent_accepted",
    "consent_accepted_pending",
    "consent_declined",
    "consent_required",
    "language_first",
    "language_prompt",
    "language_set",
    "help",
    "help_with_manager",
    "help_client",
    "contacts",
    "contact_labels",
    "contacts_missing",
  ],
  handoff: [
    "handoff",
    "sla_promise",
    "off_hours",
    "waiting_for_manager",
    "manager_joined",
    "returned_to_bot",
    "handoff_offer_yes",
    "handoff_offer_no",
    "handoff_offer_declined",
    "attachment_received",
    "attachment_too_large",
  ],
  fallback: [
    "fallback",
    "service_unavailable",
    "maintenance",
    "rate_limited",
    "unsupported_message",
    "smalltalk_ack",
  ],
  clients: [
    "document_sent",
    "document_failed",
    "service_request_closed",
    "client_only",
    "client_access_granted",
    "request_text_only",
    "docs_list",
    "docs_choose",
    "docs_empty",
    "request_prompt",
    "request_created",
    "request_status_open",
    "request_status_none",
  ],
  menu: [
    "menu_start",
    "menu_human",
    "menu_lang",
    "menu_help",
    "menu_delete",
    "menu_docs",
    "menu_request",
    "menu_status",
  ],
  phone: [
    "phone_request",
    "phone_share_button",
    "phone_skip_button",
    "phone_saved",
    "phone_skipped",
    "phone_not_own",
    "phone_before_manager",
    "phone_declined_manager",
  ],
  erp: [
    "erp_quote_sent",
    "erp_quote_acceptance_code",
    "erp_invoice_issued",
    "erp_invoice_paid",
    "erp_delivery_status",
    "erp_delivery_statuses",
    "erp_delivery_eta_changed",
    "erp_act_issued",
    "erp_btn_quote",
    "erp_btn_invoice",
    "erp_btn_cabinet",
    "erp_staff_quote_accepted",
    "erp_staff_act_returned",
    "erp_note_delivery_line_accepted",
    "erp_note_delivery_line_disputed",
    "erp_staff_delivery_line_disputed",
  ],
  erase: ["erase_confirm", "erase_button", "cancel_button", "erase_cancelled", "erased"],
};

/** Служебные поля (версия согласия) — в свёрнутой группе «Дополнительно», последней. */
const ADVANCED_TEXTS = ["consent_version"];

/** Ключи `texts.*` по смысловым группам; новые ключи CRM — в «other», не теряются. */
export function textGroups(keys: readonly string[]): { key: string; fields: string[] }[] {
  const known = new Set([...Object.values(TEXT_GROUPS).flat(), ...ADVANCED_TEXTS]);
  const groups = Object.entries(TEXT_GROUPS).map(([key, fields]) => ({
    key,
    fields: fields.filter((f) => keys.includes(f)),
  }));
  groups.push({ key: "other", fields: keys.filter((k) => !known.has(k)) });
  groups.push({ key: "advanced", fields: ADVANCED_TEXTS.filter((k) => keys.includes(k)) });
  return groups.filter((g) => g.fields.length > 0);
}

export type Widget = "time" | "weekdays" | "dates" | "timezone" | "users" | "triggers";

/** Специальный виджет по имени поля и формату схемы; `null` — обычный по типу. */
export function widgetFor(key: string, schema: { format?: string }): Widget | null {
  if (schema.format === "time") return "time";
  if (key === "weekdays") return "weekdays";
  if (key === "holidays") return "dates";
  if (key === "timezone") return "timezone";
  if (key.endsWith("_user_ids")) return "users";
  if (key === "disabled_triggers") return "triggers";
  return null;
}

/** «09:00:00» / «09:00» -> «09:00» для выбора времени; пусто -> null. */
export function timeToPicker(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{2}):(\d{2})/.exec(value);
  return match ? `${match[1] ?? "00"}:${match[2] ?? "00"}` : null;
}

/** «HH:mm» -> «HH:mm:00» (формат `time` Pydantic, как хранится). */
export const pickerToTime = (value: string): string => `${value}:00`;

/** Предпросмотр нужен, только если в тексте есть плейсхолдеры `{…}`. */
export const hasPlaceholders = (text: string): boolean => /\{[a-z_]+\}/.test(text);

/** Подстановка примеров вместо `{company}`, `{hours}` и т. п. */
export function fillPlaceholders(text: string, samples: Record<string, string>): string {
  return text.replace(/\{([a-z_]+)\}/g, (whole, name: string) => samples[name] ?? whole);
}

/** Языки, где перевод пуст (индикатор на тексте). */
export function emptyLanguages(value: unknown): string[] {
  const record = (value ?? {}) as Record<string, unknown>;
  return ["ru", "uz", "en"].filter((lang) => {
    const text = record[lang];
    return typeof text !== "string" || text.trim() === "";
  });
}

/**
 * Короткое поле (число, переключатель, выбор из списка, время) — половина ширины на широком экране; длинные (списки,
 * тексты, вложенные группы, особые виджеты) — во всю ширину.
 */
export function isShortField(key: string, schema: JsonSchema): boolean {
  const format = schema.type === "array" ? schema.items?.format : schema.format;
  const widget = widgetFor(key, format ? { format } : {});
  if (widget) return widget === "time" || widget === "timezone";
  const kind = kindOf(schema);
  if (kind === "string") return !(schema.description && schema.description.length > 80);
  return ["integer", "number", "boolean", "enum"].includes(kind);
}

/** Поиск по названиям текстов бота: без учёта регистра, по подписи, «когда» и ключу. */
export function matchesText(key: string, query: string, label: string, when: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [key, label, when].some((s) => s.toLowerCase().includes(q));
}

/** Пути невалидных полей из ответа PUT (`details.paths`: «greeting.uz») -> имена полей формы. */
export function errorPaths(details: Record<string, unknown>): string[][] {
  const paths = details["paths"];
  if (!Array.isArray(paths)) return [];
  return paths
    .filter((p): p is string => typeof p === "string" && p !== "")
    .map((p) => p.split("."));
}

/** Обрезка текста для ячейки таблицы: одна строка, без переводов строк. */
export const oneLine = (text: unknown): string =>
  typeof text === "string" ? text.replace(/\s+/g, " ").trim() : "";
