import type { ManualLeadIn, ManualLeadInLanguage } from "../../api/generated/model";
import { ApiError } from "../../api/http";
import { apiErrorField, apiErrorMessage } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";

/** Значения формы «Новый лид» (M3-CRM-05): строки как ввёл менеджер. */
export type NewLeadFormValues = {
  source: ManualLeadIn["source"];
  name: string;
  company?: string | null;
  phone?: string | null;
  email?: string | null;
  need?: string | null;
  language?: ManualLeadInLanguage;
};

export const MANUAL_SOURCES = ["phone", "email", "referral"] as const;
export const NEW_LEAD_FIELDS = ["name", "company", "phone", "email", "need"] as const;
type NewLeadField = (typeof NEW_LEAD_FIELDS)[number];

const isNewLeadField = (field: string): field is NewLeadField =>
  (NEW_LEAD_FIELDS as readonly string[]).includes(field);

const clean = (value: string | null | undefined): string | null => value?.trim() || null;
const text = (value: unknown): string => (typeof value === "string" ? value : "");

/** Форма → тело запроса: пустые строки → null, телефон в E.164 приводит сервер. */
export function toLeadIn(values: NewLeadFormValues): ManualLeadIn {
  return {
    source: values.source,
    name: values.name.trim(),
    company: clean(values.company),
    phone: clean(values.phone),
    email: clean(values.email),
    need: clean(values.need),
    language: values.language ?? "ru",
  };
}

/** Какой контакт обязателен по источнику: звонок — телефон, письмо — email, иначе любой. */
export function requiredContact(source: ManualLeadIn["source"]): "phone" | "email" | "any" {
  if (source === "phone") return "phone";
  if (source === "email") return "email";
  return "any";
}

/** Ошибка API → подсветка поля формы (`details.field`), если такое поле есть в форме. */
export function leadFieldError(error: unknown): { name: NewLeadField; errors: string[] } | null {
  const field = apiErrorField(error);
  if (!field || !isNewLeadField(field)) return null;
  return { name: field, errors: [apiErrorMessage(error)] };
}

export type Duplicate = { kind: "lead" | "client"; id: number; name: string; text: string };

/**
 * 409 с `lead_exists` / `client_exists`: вместо второй карточки — ссылка на найденную
 * (ARCHITECTURE §17: ручное создание предлагает существующего, не дублирует).
 */
export function duplicateOf(error: unknown): Duplicate | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const { reason } = error.details;
  if (reason === "lead_exists" && typeof error.details["lead_id"] === "number") {
    const name = text(error.details["display_name"]);
    return {
      kind: "lead",
      id: error.details["lead_id"],
      name,
      text: t.newLead.duplicateLead.replace("{name}", name || t.common.none),
    };
  }
  if (reason === "client_exists" && typeof error.details["client_id"] === "number") {
    const name = text(error.details["client_name"]);
    return {
      kind: "client",
      id: error.details["client_id"],
      name,
      text: t.newLead.duplicateClient.replace("{name}", name || t.common.none),
    };
  }
  return null;
}

export const duplicatePath = (d: Duplicate): string =>
  d.kind === "lead" ? `/leads/${String(d.id)}` : `/clients/${String(d.id)}`;
