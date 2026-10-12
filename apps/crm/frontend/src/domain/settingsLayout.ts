/**
 * Раскладка экрана «Настройки»: группы разделов, группы текстов бота, выбор виджета поля.
 * Чистые функции — без React и сети (дизайн-аудит 2026-10-11, отчёт 1: «Настройки»).
 */
import { t } from "../i18n/ru";
import type { JsonSchema } from "./schemaForm";

export type SectionGroup = { key: string; sections: string[] };

/** Порядок групп и разделов в навигации; неизвестные ключи с бэка — в «Другое». */
const SECTION_GROUPS: SectionGroup[] = [
  { key: "company", sections: ["company", "business_hours"] },
  { key: "bot", sections: ["texts", "bot", "kb", "stop_words", "competitors"] },
  { key: "handoff", sections: ["escalation", "qualification"] },
  { key: "team", sections: ["notifications", "deals"] },
  { key: "spend", sections: ["budget"] },
];

export function sectionGroups(available: string[]): SectionGroup[] {
  const known = new Set(SECTION_GROUPS.flatMap((g) => g.sections));
  const groups = SECTION_GROUPS.map((g) => ({
    key: g.key,
    sections: g.sections.filter((s) => available.includes(s)),
  }));
  groups.push({ key: "other", sections: available.filter((s) => !known.has(s)) });
  return groups.filter((g) => g.sections.length > 0);
}

/** Раздел из `?section=`: известный — он, иначе первый по порядку навигации. */
export function resolveSection(requested: string | null, available: string[]): string | null {
  if (requested && available.includes(requested)) return requested;
  return sectionGroups(available)[0]?.sections[0] ?? null;
}

const TEXT_GROUPS: Record<string, string[]> = {
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
  ],
  fallback: [
    "fallback",
    "service_unavailable",
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
  ],
  erase: ["erase_confirm", "erase_button", "cancel_button", "erase_cancelled", "erased"],
};

/** Служебные поля (версия согласия) — в свёрнутой группе «Дополнительно», последней. */
const ADVANCED_TEXTS = ["consent_version"];

/** Ключи `texts.*` по смысловым группам; новые ключи с бэка — в «other», не теряются. */
export function textGroups(keys: string[]): { key: string; fields: string[] }[] {
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

/** «09:00:00» / «09:00» → «09:00» для TimePicker; пусто → null. */
export function timeToPicker(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{2}):(\d{2})/.exec(value);
  return match ? `${match[1] ?? "00"}:${match[2] ?? "00"}` : null;
}

/** «HH:mm» из TimePicker → «HH:mm:00» (формат `time` pydantic, как хранится). */
export const pickerToTime = (value: string): string => `${value}:00`;

/** Предпросмотр нужен, только если в тексте есть плейсхолдеры `{…}`. */
export const hasPlaceholders = (text: string): boolean => /\{[a-z_]+\}/.test(text);

/** Подстановка примеров вместо `{company}`, `{hours}` и т. п. */
export function fillPlaceholders(text: string, samples: Record<string, string>): string {
  return text.replace(/\{([a-z_]+)\}/g, (whole, name: string) => samples[name] ?? whole);
}

/** Есть ли пустые переводы в локализованном тексте (индикатор на вкладке языка). */
export function emptyLanguages(value: unknown): string[] {
  const record = (value ?? {}) as Record<string, unknown>;
  return ["ru", "uz", "en"].filter((lang) => {
    const text = record[lang];
    return typeof text !== "string" || text.trim() === "";
  });
}

/** Подпись поля; сырой ключ — только крайний случай (тест-сторож i18n/settingsLabels.test). */
export function fieldLabel(key: string, schema: JsonSchema): string {
  return t.settings.fields[key] ?? t.settings.botTexts[key]?.label ?? schema.title ?? key;
}
