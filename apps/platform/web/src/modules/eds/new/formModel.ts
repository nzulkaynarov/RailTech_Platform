import type {
  EdsDealRef,
  EdsDocument,
  EdsDocumentIn,
  EdsDocumentKind,
  EdsDocumentUpdateIn,
  LetterCard,
} from "../../../shared/api/generated/model";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import { HOME_CURRENCY } from "../../../shared/lib/money";
import {
  type Body,
  type BodyLang,
  type BodyNode,
  bodyText,
  emptyDoc,
  fromBody,
  isBlank,
  paragraphOf,
  toBody,
} from "../../../shared/ui/BodyEditor/bodyModel";
import type { FieldKey } from "../documents/errors";

/** Тип из адреса `/eds/new?type=memo|statement|report|letter` (SPEC-v3 §6.3) -> тип документа EDS. */
const TYPE_PARAM: Record<string, EdsDocumentKind> = {
  memo: "memo",
  statement: "application",
  application: "application",
  report: "report",
  letter: "letter_out",
};

export function kindFromParam(value: string | null): EdsDocumentKind {
  return (value && TYPE_PARAM[value]) || "memo";
}

export interface Attachment {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "done" | "error";
  /** Id файла в EDS — есть у загруженных и у уже привязанных к документу */
  id?: string;
  /** Файл уже в документе (черновик открыт на правку): снять его нельзя */
  existing?: boolean;
  error?: string;
}

export interface DealChoice {
  erp_deal_id: number;
  /** Подпись в поле: «ЗВ-2026-104 · Поставка рельсов» */
  label: string;
}

export interface FormValues {
  kind: EdsDocumentKind;
  subject: string;
  text: string;
  amount: string;
  dueDate: string;
  recipientName: string;
  recipientInn: string;
  deal: DealChoice | null;
  attachments: Attachment[];
  /** Только письмо (P8b): «в ответ на» — номер входящего ВХ; регистрация закрывает поручение «Подготовить ответ» */
  inReplyTo: string;
  /** Письмо на бланке (P4): тело — дерево редактора, «кому», почта адресата, подписант (пусто — подписант бланка) */
  body: BodyNode;
  recipientAttention: string;
  recipientEmail: string;
  signatoryName: string;
  signatoryPosition: string;
  /** Пункт 1.6 плана: согласующие перед шагами шаблона (по порядку) и получатели копии — `crm_user_id` */
  approvers: string[];
  watchers: string[];
}

export const EMPTY_FORM: FormValues = {
  kind: "memo",
  subject: "",
  text: "",
  amount: "",
  dueDate: "",
  recipientName: "",
  recipientInn: "",
  deal: null,
  attachments: [],
  inReplyTo: "",
  body: emptyDoc(),
  recipientAttention: "",
  recipientEmail: "",
  signatoryName: "",
  signatoryPosition: "",
  approvers: [],
  watchers: [],
};

/** Сегодня в часовом поясе компании (`YYYY-MM-DD`): «нужно до» не раньше этой даты. */
export function todayInCompanyZone(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/**
 * Сумма из поля ввода в строку EDS с двумя знаками: «1 500 000» -> `1500000.00`, «2500,5» -> `2500.50`.
 * Пусто — суммы нет (`value: null`), нуль и мусор — `ok: false`.
 */
export function parseAmount(text: string): { ok: true; value: string | null } | { ok: false } {
  const compact = text.replace(/[\s\u00a0\u202f]/g, "");
  if (compact === "") return { ok: true, value: null };
  const match = /^(\d{1,15})(?:[.,](\d{1,2}))?$/.exec(compact);
  if (!match) return { ok: false };
  const whole = (match[1] ?? "0").replace(/^0+(?=\d)/, "");
  const fraction = (match[2] ?? "").padEnd(2, "0");
  if (/^0+$/.test(whole) && /^0+$/.test(fraction)) return { ok: false };
  return { ok: true, value: `${whole}.${fraction}` };
}

/** Почта в строке «контактное лицо» входящего (`a@b.uz` или `Имя <a@b.uz>`); нет — пусто. */
export function emailIn(text: string | null | undefined): string {
  const found = /[^\s@<>,;()]+@[^\s@<>,;()]+\.[^\s@<>,;()]+/.exec(text ?? "");
  return found ? found[0] : "";
}

/**
 * Заготовка ответа на входящее (EDS-REPLY-1): корреспондент, ИНН, почта адресата — только то, что уже есть в письме, и тема
 * «На ВХ-… от …: тема письма» (не длиннее 300 знаков). Остальное — пусто.
 */
export function replyPrefill(
  letter: Pick<LetterCard, "subject" | "sender">,
  subjectPrefix: string,
): Pick<FormValues, "subject" | "recipientName" | "recipientInn" | "recipientEmail"> {
  return {
    subject: `${subjectPrefix}: ${letter.subject}`.slice(0, 300),
    recipientName: letter.sender.name ?? "",
    recipientInn: letter.sender.inn ?? "",
    recipientEmail: emailIn(letter.sender.contact),
  };
}

export type FormErrors = Partial<Record<FieldKey, true>>;

export function isLetter(kind: EdsDocumentKind): boolean {
  return kind === "letter_out";
}

/** Почта адресата: одна, без пробелов, с «@» и точкой в домене (точную проверку делает сервер). */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmail(value: string): boolean {
  return EMAIL.test(value.trim());
}

/**
 * Клиентская проверка: тема и текст обязательны, сумма больше нуля, «нужно до» не в прошлом; у письма — адресат, тело на
 * бланке (хотя бы один непустой блок) и почта адресата, если указана, — похожая на адрес.
 */
export function validate(values: FormValues, today: string = todayInCompanyZone()): FormErrors {
  const errors: FormErrors = {};
  if (values.subject.trim() === "") errors.subject = true;
  if (isLetter(values.kind)) {
    if (isBlank(values.body)) errors.text = true;
    if (values.recipientName.trim() === "") errors.recipient = true;
    if (values.recipientEmail.trim() !== "" && !isEmail(values.recipientEmail)) {
      errors.recipient_email = true;
    }
  } else {
    if (values.text.trim() === "") errors.text = true;
    if (!parseAmount(values.amount).ok) errors.amount = true;
    if (values.dueDate !== "" && values.dueDate < today) errors.due_date = true;
  }
  return errors;
}

/** Порядок полей на экране: первая ошибка получает фокус. */
export const FIELD_ORDER: readonly FieldKey[] = [
  "subject",
  "recipient",
  "recipient_email",
  "text",
  "amount",
  "due_date",
  "erp_deal_id",
  "in_reply_to_number",
];

export function fieldElementId(field: FieldKey): string {
  return `doc-${field.replaceAll("_", "-")}`;
}

interface Payload {
  subject: string;
  text: string;
  amount: { amount: string; currency: string } | null;
  due_date: string | null;
  file_ids: string[];
  erp_deal_id: number | null;
  recipient?: { name: string; inn: string | null };
  letter?: {
    body: Body;
    recipient_attention: string | null;
    recipient_email: string | null;
    signatory_name: string | null;
    signatory_position: string | null;
  };
  submit: boolean;
  send?: boolean;
  approvers?: string[];
  watchers?: string[];
}

const orNull = (value: string): string | null => (value.trim() === "" ? null : value.trim());

/** Что сделать с документом: сохранить черновик, отправить (письмо — зарегистрировать) и, у письма, отправить адресату. */
export interface SubmitMode {
  submit: boolean;
  /** Только письмо: после регистрации отправить адресату почтой (нужна почта) */
  send?: boolean;
}

export function toPayload(
  values: FormValues,
  mode: SubmitMode | boolean,
  lang: BodyLang = "ru",
): Payload {
  const { submit, send = false } = typeof mode === "boolean" ? { submit: mode } : mode;
  const letter = isLetter(values.kind);
  const parsed = letter ? null : parseAmount(values.amount);
  const amount = parsed?.ok ? parsed.value : null;
  const body = letter ? toBody(values.body, lang) : null;
  // У письма `text` — производный от тела (поиск и показ без PDF); поле обязательно, поэтому запасной — тема.
  const text = body ? bodyText(body).trim() || values.subject.trim() : values.text.trim();
  return {
    subject: values.subject.trim(),
    text,
    amount: amount ? { amount, currency: HOME_CURRENCY } : null,
    due_date: !letter && values.dueDate !== "" ? values.dueDate : null,
    file_ids: values.attachments.flatMap((a) => (a.status === "done" && a.id ? [a.id] : [])),
    erp_deal_id: values.deal?.erp_deal_id ?? null,
    ...(letter && body
      ? {
          recipient: {
            name: values.recipientName.trim(),
            inn: values.recipientInn.trim() === "" ? null : values.recipientInn.trim(),
          },
          letter: {
            body,
            recipient_attention: orNull(values.recipientAttention),
            recipient_email: orNull(values.recipientEmail),
            signatory_name: orNull(values.signatoryName),
            signatory_position: orNull(values.signatoryPosition),
          },
          ...(submit && send ? { send: true } : {}),
        }
      : {}),
    // Пункт 1.6: маршрут от автора уходит при отправке внутреннего документа (письму не нужен)
    ...(!letter && submit ? { approvers: values.approvers, watchers: values.watchers } : {}),
    submit,
  };
}

export function toCreateBody(
  values: FormValues,
  mode: SubmitMode | boolean,
  lang: BodyLang = "ru",
): EdsDocumentIn {
  const reply = values.inReplyTo.trim();
  return {
    kind: values.kind,
    ...toPayload(values, mode, lang),
    ...(isLetter(values.kind) && reply ? { in_reply_to_number: reply } : {}),
  };
}

export function toUpdateBody(
  values: FormValues,
  mode: SubmitMode | boolean,
  lang: BodyLang = "ru",
): EdsDocumentUpdateIn {
  return toPayload(values, mode, lang);
}

function dealChoice(deal: EdsDealRef | null): DealChoice | null {
  if (!deal) return null;
  return { erp_deal_id: deal.erp_deal_id, label: deal.number ?? String(deal.erp_deal_id) };
}

/** Форма из сохранённого документа: «Продолжить» открывает черновик с теми же данными. */
export function fromDocument(doc: EdsDocument): FormValues {
  return {
    kind: doc.kind,
    subject: doc.subject,
    text: doc.text,
    amount: doc.amount ? doc.amount.amount.replace(/\.00$/, "") : "",
    dueDate: doc.due_date ?? "",
    recipientName: doc.recipient?.name ?? "",
    recipientInn: doc.recipient?.inn ?? "",
    deal: dealChoice(doc.deal),
    attachments: doc.files.map((file) => ({
      key: file.id,
      name: file.name,
      size: file.size,
      status: "done" as const,
      id: file.id,
      existing: true,
    })),
    inReplyTo: "",
    // Письмо без тела (до P4) открывается с его текстом в одном абзаце.
    body: doc.letter?.body
      ? fromBody(doc.letter.body)
      : doc.kind === "letter_out" && doc.text
        ? { type: "doc", content: [paragraphOf(doc.text)] }
        : emptyDoc(),
    approvers: (doc.approvers ?? []).map((p) => String(p.crm_user_id)),
    watchers: (doc.watchers ?? []).map((p) => String(p.crm_user_id)),
    recipientAttention: doc.letter?.recipient_attention ?? "",
    recipientEmail: doc.letter?.recipient_email ?? "",
    signatoryName: doc.letter?.signatory_name ?? "",
    signatoryPosition: doc.letter?.signatory_position ?? "",
  };
}

/** Маршрут для блока «Что произойдёт»: служебная записка с суммой идёт ещё и бухгалтеру; письмо маршрута не имеет. */
export function routeKind(values: FormValues): "plain" | "withAmount" | "letter" {
  if (isLetter(values.kind)) return "letter";
  const amount = parseAmount(values.amount);
  return values.kind === "memo" && amount.ok && amount.value !== null ? "withAmount" : "plain";
}

export function consequenceKey(values: FormValues): string {
  if (values.kind === "memo") return routeKind(values) === "withAmount" ? "memoAmount" : "memo";
  return values.kind === "letter_out" ? "letter" : values.kind;
}
