/**
 * Раскладка экрана «Настройки бота»: группы разделов, группы текстов бота, выбор виджета поля. Чистые функции — без React
 * и сети. Ключи разделов и текстов приходят из CRM; неизвестные (новые в CRM) попадают в «Другое» и не теряются.
 */
import { type JsonSchema, kindOf } from "./schemaForm";

export interface SectionGroup {
  key: string;
  sections: string[];
}

/** Порядок групп и разделов в навигации. */
const SECTION_GROUPS: readonly SectionGroup[] = [
  { key: "company", sections: ["company", "business_hours"] },
  { key: "bot", sections: ["texts", "bot", "kb", "stop_words", "competitors"] },
  { key: "handoff", sections: ["escalation", "qualification", "web_form"] },
  { key: "team", sections: ["notifications", "service_alerts", "deals"] },
  { key: "spend", sections: ["budget"] },
];

export function sectionGroups(available: readonly string[]): SectionGroup[] {
  const known = new Set(SECTION_GROUPS.flatMap((g) => g.sections));
  const groups = SECTION_GROUPS.map((g) => ({
    key: g.key,
    sections: g.sections.filter((s) => available.includes(s)),
  }));
  groups.push({ key: "other", sections: available.filter((s) => !known.has(s)) });
  return groups.filter((g) => g.sections.length > 0);
}

/**
 * Вкладки экрана «Telegram-бот» (W15-H4, UX-оценка §5 P1-6): бот настраивается в одном месте. «Тексты» и «База знаний» —
 * свои разделы настроек CRM (`texts`, `kb`), «Поведение и передача» — остальные разделы, «Подключение» — токен, канал и
 * профиль (раньше — в «Подключениях»).
 */
export const BOT_PARTS = ["connection", "texts", "behavior", "kb", "templates", "exports"] as const;
export type BotPart = (typeof BOT_PARTS)[number];

/** Разделы настроек, у которых своя вкладка, а не место в «Поведении и передаче». */
const OWN_PART: Record<string, BotPart> = { texts: "texts", kb: "kb" };

/** Разделы «Поведения и передачи»: всё, кроме текстов и базы знаний. */
export function behaviorKeys(available: readonly string[]): string[] {
  return available.filter((key) => OWN_PART[key] === undefined);
}

/**
 * Вкладка и раздел из адреса: `?part=` — вкладка; старый `?section=` (ссылки до W15-H4) ведёт на вкладку своего раздела.
 */
export function resolvePart(part: string | null, section: string | null): BotPart {
  const found = BOT_PARTS.find((p) => p === part);
  if (found) return found;
  if (section === "templates" || section === "exports") return section;
  if (section && OWN_PART[section]) return OWN_PART[section];
  if (section) return "behavior";
  return "connection";
}

/** Не разделы настроек, а соседние части экрана: шаблоны ответов и выгрузки. */
export const EXTRA_SECTIONS = ["templates", "exports"] as const;
export type ExtraSection = (typeof EXTRA_SECTIONS)[number];

export function isExtra(value: string | null): value is ExtraSection {
  return value !== null && (EXTRA_SECTIONS as readonly string[]).includes(value);
}

/** Раздел из `?section=`: шаблоны, выгрузки или известный раздел настроек, иначе первый по порядку навигации. */
export function resolveSection(
  requested: string | null,
  available: readonly string[],
): string | null {
  if (isExtra(requested)) return requested;
  if (requested && available.includes(requested)) return requested;
  return sectionGroups(available)[0]?.sections[0] ?? null;
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
