import type {
  EdsDealRef,
  EdsDocument,
  EdsDocumentIn,
  EdsDocumentKind,
  EdsDocumentUpdateIn,
} from "../../../shared/api/generated/model";
import { COMPANY_TIME_ZONE } from "../../../shared/lib/format";
import type { FieldKey } from "../documents/errors";
import { HOME_CURRENCY } from "../../../shared/lib/money";

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

export type FormErrors = Partial<Record<FieldKey, true>>;

export function isLetter(kind: EdsDocumentKind): boolean {
  return kind === "letter_out";
}

/** Клиентская проверка: тема и текст обязательны, сумма больше нуля, «нужно до» не в прошлом, у письма — адресат. */
export function validate(values: FormValues, today: string = todayInCompanyZone()): FormErrors {
  const errors: FormErrors = {};
  if (values.subject.trim() === "") errors.subject = true;
  if (values.text.trim() === "") errors.text = true;
  if (isLetter(values.kind)) {
    if (values.recipientName.trim() === "") errors.recipient = true;
  } else {
    if (!parseAmount(values.amount).ok) errors.amount = true;
    if (values.dueDate !== "" && values.dueDate < today) errors.due_date = true;
  }
  return errors;
}

/** Порядок полей на экране: первая ошибка получает фокус. */
export const FIELD_ORDER: readonly FieldKey[] = [
  "subject",
  "recipient",
  "text",
  "amount",
  "due_date",
  "erp_deal_id",
];

export function fieldElementId(field: FieldKey): string {
  return `doc-${field.replace("_", "-")}`;
}

interface Payload {
  subject: string;
  text: string;
  amount: { amount: string; currency: string } | null;
  due_date: string | null;
  file_ids: string[];
  erp_deal_id: number | null;
  recipient?: { name: string; inn: string | null };
  submit: boolean;
}

export function toPayload(values: FormValues, submit: boolean): Payload {
  const letter = isLetter(values.kind);
  const parsed = letter ? null : parseAmount(values.amount);
  const amount = parsed?.ok ? parsed.value : null;
  return {
    subject: values.subject.trim(),
    text: values.text.trim(),
    amount: amount ? { amount, currency: HOME_CURRENCY } : null,
    due_date: !letter && values.dueDate !== "" ? values.dueDate : null,
    file_ids: values.attachments.flatMap((a) => (a.status === "done" && a.id ? [a.id] : [])),
    erp_deal_id: values.deal?.erp_deal_id ?? null,
    ...(letter
      ? {
          recipient: {
            name: values.recipientName.trim(),
            inn: values.recipientInn.trim() === "" ? null : values.recipientInn.trim(),
          },
        }
      : {}),
    submit,
  };
}

export function toCreateBody(values: FormValues, submit: boolean): EdsDocumentIn {
  return { kind: values.kind, ...toPayload(values, submit) };
}

export function toUpdateBody(values: FormValues, submit: boolean): EdsDocumentUpdateIn {
  return toPayload(values, submit);
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
