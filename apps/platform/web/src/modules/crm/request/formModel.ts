import type {
  ClientContactView,
  RequestFormIn,
  RequestFormInConsentMethod,
  RequestFormInUrgency,
} from "../../../shared/api/generated/model";

/** Письмо на имя директора: файл уходит в EDS сразу после выбора, в заявку — только id готового файла. */
export interface LetterFile {
  name: string;
  status: "uploading" | "done" | "error";
  id?: string;
  error?: string;
}

/** Поля формы «Создать заявку» (SPEC-v3 §3.1 шаг 2). Пустая строка — поле не заполнено. */
export interface RequestFormState {
  /** Выбранный клиент; `null` — новая компания из `companyName` и `inn` */
  clientId: number | null;
  clientName: string | null;
  companyName: string;
  inn: string;
  /** Контакт клиента; `null` — новый контакт из полей ниже */
  contactId: number | null;
  fullName: string;
  position: string;
  phone: string;
  email: string;
  /** Telegram лида — канал нового контакта */
  useLeadTelegram: boolean;
  summary: string;
  urgency: RequestFormInUrgency;
  letter: LetterFile | null;
  /** Согласие получено вне бота (телефон, письмо, бумага) — только для лида без согласия и не из Telegram */
  consentMarked: boolean;
  consentMethod: RequestFormInConsentMethod;
  consentComment: string;
}

/** Откуда открыта форма: лид (с согласием или без) и/или клиент с его контактами. */
export interface RequestContext {
  lead: string | null;
  /** Канал лида (`telegram`, `web`, …); без лида — `null` */
  leadChannel: string | null;
  /** Telegram лида (имя без @), если он пишет из Telegram */
  leadTelegram: string | null;
  /** Согласие на данные уже есть (или лида нет — форма из карточки клиента) */
  consentGiven: boolean;
  /** Контакты выбранного клиента */
  contacts: readonly ClientContactView[];
}

export type RequestField = "company" | "inn" | "contact" | "channel" | "summary" | "consent";

/** Ключ текста ошибки `request:errors.*` по полю. */
export type RequestErrors = Partial<Record<RequestField, string>>;

const INN = /^\d{9,14}$/;

export function emptyRequestForm(): RequestFormState {
  return {
    clientId: null,
    clientName: null,
    companyName: "",
    inn: "",
    contactId: null,
    fullName: "",
    position: "",
    phone: "",
    email: "",
    useLeadTelegram: false,
    summary: "",
    urgency: "normal",
    letter: null,
    consentMarked: false,
    consentMethod: "phone",
    consentComment: "",
  };
}

function consentNeeded(ctx: RequestContext): boolean {
  return ctx.lead !== null && !ctx.consentGiven;
}

/**
 * Проверка формы до отправки — те же правила, что в CRM (компания, контакт хотя бы с одним каналом, суть, согласие),
 * чтобы сотрудник видел их у поля, а не ответом сервера. Сервер всё равно проверяет сам.
 */
export function validateRequest(state: RequestFormState, ctx: RequestContext): RequestErrors {
  const errors: RequestErrors = {};
  if (state.clientId === null) {
    if (!state.companyName.trim()) errors.company = "company";
    const inn = state.inn.trim();
    if (inn && !INN.test(inn)) errors.inn = "inn";
  }
  if (state.contactId === null) {
    if (!state.fullName.trim()) errors.contact = "contact";
    const telegram = state.useLeadTelegram && ctx.leadTelegram !== null;
    if (!state.phone.trim() && !state.email.trim() && !telegram) errors.channel = "channel";
  } else {
    const contact = ctx.contacts.find((c) => c.id === state.contactId);
    if (!contact) errors.contact = "contact";
    else if (contact.channels.length === 0) errors.channel = "contact_channel_required";
  }
  if (!state.summary.trim()) errors.summary = "summary";
  if (consentNeeded(ctx)) {
    if (ctx.leadChannel === "telegram") errors.consent = "consent_via_bot";
    else if (!state.consentMarked) errors.consent = "consent";
  }
  return errors;
}

function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/** Тело `POST /crm/requests`: ключ формы один на открытие, поэтому повтор после сбоя не создаст вторую заявку. */
export function toRequestPayload(
  state: RequestFormState,
  ctx: RequestContext,
  requestKey: string,
): RequestFormIn {
  const payload: RequestFormIn = {
    request_key: requestKey,
    contact:
      state.contactId !== null
        ? { contact_id: state.contactId }
        : {
            full_name: state.fullName.trim(),
            position: text(state.position),
            phone: text(state.phone),
            email: text(state.email),
            use_lead_telegram: ctx.leadTelegram !== null && state.useLeadTelegram,
          },
    summary: state.summary.trim(),
    urgency: state.urgency,
  };
  if (ctx.lead) payload.lead = ctx.lead;
  if (state.clientId !== null) payload.client_id = state.clientId;
  else payload.company = { name: state.companyName.trim(), inn: text(state.inn) };
  if (state.letter?.status === "done" && state.letter.id) {
    payload.letter_file_id = state.letter.id;
  }
  if (consentNeeded(ctx) && state.consentMarked) {
    payload.consent = { method: state.consentMethod, comment: text(state.consentComment) };
  }
  return payload;
}
