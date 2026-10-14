import { isCrmFormError, type WebFormToken, type WebLeadAccepted, type WebLeadIn } from '@/api/crm';
import { localeFor } from '@/i18n/locales';

/**
 * Форма «Я новый клиент» (ARCHITECTURE §17, M2-CAB-03): значения, проверка до отправки, тело
 * `POST /api/v1/leads/web` и повтор с новым токеном. Без React — проверяется юнит-тестами.
 */
export interface LeadFormValues {
  name: string;
  company: string;
  phone: string;
  email: string;
  text: string;
  consent: boolean;
  /** Honeypot: человек поле не видит; заполнено — CRM отвечает 202 без лида. */
  website: string;
}

export const EMPTY_LEAD_FORM: LeadFormValues = {
  name: '',
  company: '',
  phone: '',
  email: '',
  text: '',
  consent: false,
  website: '',
};

/** Пределы полей — как в схеме CRM (`WebLeadIn`); текст — как `settings.web_form.max_text_chars`. */
export const LEAD_FORM_LIMITS = { name: 255, company: 255, phone: 32, email: 255, text: 4000 } as const;

export type LeadFormField = 'name' | 'company' | 'phone' | 'email' | 'text' | 'consent';

export interface LeadFormProblem {
  /** Ключ `newClient.errors.<code>` (те же коды, что `details.reason` CRM, плюс проверки формы). */
  code: string;
  field: LeadFormField | null;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Проверка до отправки: то же, что потом проверит CRM, — без лишнего запроса и расхода лимита по IP. */
export function validateLeadForm(values: LeadFormValues): LeadFormProblem | null {
  if (!values.name.trim()) return { code: 'name_required', field: 'name' };
  const phone = values.phone.trim();
  const email = values.email.trim();
  if (!phone && !email) return { code: 'contact_required', field: 'phone' };
  if (email && !EMAIL_RE.test(email)) return { code: 'invalid_email', field: 'email' };
  if (!values.text.trim()) return { code: 'text_required', field: 'text' };
  if (!values.consent) return { code: 'consent_required', field: 'consent' };
  return null;
}

function optional(value: string): string | null {
  const text = value.trim();
  return text ? text : null;
}

/** Тело формы для CRM; язык — текущий язык интерфейса (`ru | uz | en`). */
export function toWebLead(values: LeadFormValues, language: string | undefined, formToken: string): WebLeadIn {
  return {
    name: values.name.trim(),
    company: optional(values.company),
    phone: optional(values.phone),
    email: optional(values.email),
    text: values.text.trim(),
    language: localeFor(language).code,
    consent: values.consent,
    form_token: formToken,
    website: optional(values.website),
  };
}

/** Ошибка токена, после которой форма тихо берёт новый токен и отправляет ещё раз (один раз). */
const TOKEN_RETRY_CODES = new Set(['form_token_expired', 'form_token_invalid']);

/** Запас сверх `min_fill_seconds` нового токена, чтобы повтор не упал в `form_too_fast`. */
const MIN_FILL_MARGIN_MS = 250;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * Отправка с одним тихим повтором: токен истёк (форму открыли давно) или не принят (сменился ключ
 * CRM) — берём новый, ждём его `min_fill_seconds` (иначе CRM ответит `form_too_fast`) и отправляем
 * снова. Вторая ошибка уходит пользователю как есть.
 */
export async function submitWithFreshToken({
  build,
  token,
  refreshToken,
  submit,
  wait = sleep,
}: {
  build: (formToken: string) => WebLeadIn;
  token: WebFormToken;
  refreshToken: () => Promise<WebFormToken>;
  submit: (body: WebLeadIn) => Promise<WebLeadAccepted>;
  wait?: (ms: number) => Promise<void>;
}): Promise<WebLeadAccepted> {
  try {
    return await submit(build(token.token));
  } catch (error) {
    if (!isCrmFormError(error) || !TOKEN_RETRY_CODES.has(error.code)) throw error;
    const fresh = await refreshToken();
    await wait(fresh.min_fill_seconds * 1000 + MIN_FILL_MARGIN_MS);
    return submit(build(fresh.token));
  }
}
