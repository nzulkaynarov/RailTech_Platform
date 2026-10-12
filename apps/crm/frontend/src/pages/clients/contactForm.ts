import type { ContactIn, ContactOut, ContactSuggestion } from "../../api/generated/model";
import { apiErrorField, apiErrorMessage } from "../../hooks/useApiErrorToast";

/** Значения формы контакта: строки как ввёл пользователь. */
export type ContactFormValues = {
  full_name: string;
  position?: string | null;
  phone?: string | null;
  email?: string | null;
  note?: string | null;
  is_primary?: boolean;
};

export const CONTACT_FIELDS = ["full_name", "position", "phone", "email", "note"] as const;
type ContactField = (typeof CONTACT_FIELDS)[number];

const isContactField = (field: string): field is ContactField =>
  (CONTACT_FIELDS as readonly string[]).includes(field);

const clean = (value: string | null | undefined): string | null => value?.trim() || null;

/** Форма → тело запроса: пустые строки → null, телефон в E.164 приводит сервер. */
export function toContactIn(
  values: ContactFormValues,
  telegramIdentityId?: number | null,
): ContactIn {
  return {
    full_name: values.full_name.trim(),
    position: clean(values.position),
    phone: clean(values.phone),
    email: clean(values.email),
    note: clean(values.note),
    is_primary: values.is_primary ?? false,
    telegram_identity_id: telegramIdentityId ?? null,
  };
}

/** Существующий контакт → начальные значения формы правки. */
export function toFormValues(contact: ContactOut): ContactFormValues {
  return {
    full_name: contact.full_name,
    position: contact.position,
    phone: contact.phone_e164,
    email: contact.email,
    note: contact.note,
    is_primary: contact.is_primary,
  };
}

/** Подсказка из Telegram → тело запроса «добавить в один клик». */
export function fromSuggestion(s: ContactSuggestion, makePrimary: boolean): ContactIn {
  return {
    full_name: s.full_name,
    phone: s.phone_e164,
    is_primary: makePrimary,
    telegram_identity_id: s.telegram_identity_id,
  };
}

/** Ошибка API → подсветка поля формы (`details.field`), если такое поле есть в форме. */
export function contactFieldError(error: unknown): { name: ContactField; errors: string[] } | null {
  const field = apiErrorField(error);
  if (!field || !isContactField(field)) return null;
  return { name: field, errors: [apiErrorMessage(error)] };
}
