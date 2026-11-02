import type {
  LetterReceiptMethod,
  LetterRegisterIn,
  LetterResolutionKind,
} from "../../../shared/api/generated/model";
import type { Attachment, DealChoice } from "../new/formModel";

/** Способы получения (SPEC-v3 §3.2a п. 1) в порядке показа. */
export const RECEIPT_METHODS: readonly LetterReceiptMethod[] = [
  "paper",
  "post",
  "taxpayer_cabinet",
  "courier",
  "email",
];

export interface RegisterValues {
  kind: string;
  receiptMethod: LetterReceiptMethod | "";
  senderName: string;
  senderInn: string;
  refNumber: string;
  refDate: string;
  signedBy: string;
  receivedAt: string;
  subject: string;
  summary: string;
  documentDue: string;
  urgent: boolean;
  deal: DealChoice | null;
  relatedNumber: string;
  attachments: Attachment[];
  /** Адресат (P8b): `crm_user_id`; пусто — директор по умолчанию (решает EDS) */
  addresseeId: string;
  /** Проект резолюции делопроизводителя (P8b): тип пуст — проекта нет */
  draftKind: LetterResolutionKind | "";
  draftResponsibleId: string;
  draftDue: string;
  draftText: string;
  /** «Ознакомить» проекта резолюции (W18A-P2-3): сотрудники из копии письма, `crm_user_id` */
  draftAcquaintIds: string[];
  /** Письмо общего ящика (W18A-P2): ВХ из очереди «Входящая почта»; без вложений — можно */
  sourceMailId: number | null;
}

export type RegisterField =
  | "kind"
  | "receipt_method"
  | "sender_name"
  | "sender_inn"
  | "received_at"
  | "subject"
  | "file_ids"
  | "related_number";

/** Порядок полей формы: фокус уходит на первое с ошибкой. */
export const REGISTER_ORDER: readonly RegisterField[] = [
  "kind",
  "receipt_method",
  "sender_name",
  "sender_inn",
  "received_at",
  "subject",
  "file_ids",
  "related_number",
];

export type RegisterErrors = Partial<Record<RegisterField, true>>;

export function emptyRegister(today: string): RegisterValues {
  return {
    kind: "",
    receiptMethod: "",
    senderName: "",
    senderInn: "",
    refNumber: "",
    refDate: "",
    signedBy: "",
    receivedAt: today,
    subject: "",
    summary: "",
    documentDue: "",
    urgent: false,
    deal: null,
    relatedNumber: "",
    attachments: [],
    addresseeId: "",
    draftKind: "",
    draftResponsibleId: "",
    draftDue: "",
    draftText: "",
    draftAcquaintIds: [],
    sourceMailId: null,
  };
}

export function registerFieldId(field: RegisterField): string {
  return `reg-${field.replace(/_/g, "-")}`;
}

const INN = /^\d{9,14}$/;

/** Обязательные поля SPEC-v3 §3.2a п. 1: вид, способ, корреспондент, дата поступления (не позже сегодня), тема, файл. */
export function validateRegister(values: RegisterValues, today: string): RegisterErrors {
  const errors: RegisterErrors = {};
  if (!values.kind) errors.kind = true;
  if (!values.receiptMethod) errors.receipt_method = true;
  if (!values.senderName.trim()) errors.sender_name = true;
  if (values.senderInn.trim() && !INN.test(values.senderInn.trim())) errors.sender_inn = true;
  if (!values.receivedAt || values.receivedAt > today) errors.received_at = true;
  if (!values.subject.trim()) errors.subject = true;
  const hasFile = values.attachments.some((a) => a.status === "done" && a.id);
  if (!hasFile && values.sourceMailId === null) errors.file_ids = true;
  return errors;
}

/** Номер заявки из подписи выбора «ЗВ-2026-104 · Название · Компания». */
function dealNumber(choice: DealChoice): string | null {
  const head = choice.label.split(" · ")[0]?.trim();
  return head || null;
}

function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function toRegisterBody(values: RegisterValues): LetterRegisterIn {
  const ids = values.attachments.flatMap((a) => (a.status === "done" && a.id ? [a.id] : []));
  return {
    kind: values.kind,
    receipt_method: values.receiptMethod as LetterReceiptMethod,
    sender_name: values.senderName.trim(),
    sender_inn: text(values.senderInn),
    received_at: values.receivedAt,
    subject: values.subject.trim(),
    summary: text(values.summary),
    sender_ref_number: text(values.refNumber),
    sender_ref_date: values.refDate || null,
    signed_by: text(values.signedBy),
    document_due: values.documentDue || null,
    urgent: values.urgent,
    erp_deal_id: values.deal?.erp_deal_id ?? null,
    deal_number: values.deal ? dealNumber(values.deal) : null,
    related_number: text(values.relatedNumber),
    file_ids: [...new Set(ids)],
    addressee_id: values.addresseeId || null,
    resolution_draft: draftOf(values),
    source_mail_id: values.sourceMailId,
  };
}

/** Проект резолюции из формы регистрации (P8b): у «Для сведения» нет ответственного и срока; тип не выбран — проекта нет. */
export function draftOf(values: RegisterValues): LetterRegisterIn["resolution_draft"] {
  if (!values.draftKind) return null;
  const executor = values.draftKind !== "info";
  return {
    kind: values.draftKind,
    responsible_id: executor && values.draftResponsibleId ? values.draftResponsibleId : null,
    due: executor && values.draftDue ? values.draftDue : null,
    text: text(values.draftText),
    co_executor_ids: [],
    acquaint_ids: values.draftAcquaintIds,
  };
}
