import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";

const NS = "documents:form.error.reasons.";

/** Поле формы документа, которое назвал сервер (`details.fields`), и текст «что исправить» на языке сотрудника. */
export const FIELD_KEYS = [
  "subject",
  "text",
  "amount",
  "due_date",
  "recipient",
  "recipient_email",
  "erp_deal_id",
  "in_reply_to_number",
] as const;
export type FieldKey = (typeof FIELD_KEYS)[number];

const FIELD_TEXT: Record<FieldKey, string> = {
  subject: "documents:form.validation.subject",
  text: "documents:form.validation.text",
  amount: "documents:form.validation.amount",
  due_date: "documents:form.validation.due",
  recipient: "documents:form.validation.recipient",
  recipient_email: "documents:form.validation.recipientEmail",
  erp_deal_id: "documents:form.validation.deal",
  in_reply_to_number: "documents:form.validation.replyTo",
};

function stringDetail(error: ApiError, key: string): string | undefined {
  const value = error.details[key];
  return typeof value === "string" ? value : undefined;
}

/** Поля формы, отклонённые сервером: `details.fields` (BFF или EDS); незнакомые имена отбрасываются. */
export function serverFields(error: unknown): FieldKey[] {
  if (!(error instanceof ApiError)) return [];
  const raw = error.details["fields"];
  if (!Array.isArray(raw)) return [];
  const found: FieldKey[] = [];
  for (const item of raw) {
    if (typeof item !== "string") continue;
    // BFF называет поле по пути запроса (`body.amount.amount`, `body.letter.recipient_email`), EDS — по имени (`amount`,
    // `body` — тело письма на бланке, его поле на экране — «Текст»).
    const parts = item.split(".");
    if (parts[0] === "body" && parts.length > 1) parts.shift();
    if (parts[0] === "letter" && parts.length > 1) parts.shift();
    const raw = parts[0];
    const name = raw === "body" ? "text" : raw;
    const key = FIELD_KEYS.find((k) => k === name);
    if (key && !found.includes(key)) found.push(key);
  }
  return found;
}

export function fieldText(t: TFunction, field: FieldKey): string {
  return t(FIELD_TEXT[field]);
}

/**
 * Причина отказа для «Не отправлено: {причина}». Сначала подкод (`details.reason`: документ уже отправлен), затем поле
 * (текст «что исправить» на языке сотрудника), затем код BFF, затем общий текст. Тексты сервера на русском не
 * подставляются: язык интерфейса может быть другим.
 */
export function reasonText(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) return t(`${NS}DEFAULT`);
  const reason = stringDetail(error, "reason");
  if (reason) {
    const text = t(`${NS}${reason}`, { defaultValue: "" });
    if (text) return text;
  }
  const fields = serverFields(error);
  const first = fields[0];
  if (first && error.code === "VALIDATION_FAILED") return fieldText(t, first).replace(/\.$/, "");
  const text = t(`${NS}${error.code}`, { defaultValue: "" });
  return text || t(`${NS}DEFAULT`);
}

/** Id документа, который сервер уже сохранил, пока следующий шаг (отправка) отклонён: форма продолжает с ним. */
export function savedDocumentId(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const id = error.details["document_id"];
  return typeof id === "string" ? id : null;
}
