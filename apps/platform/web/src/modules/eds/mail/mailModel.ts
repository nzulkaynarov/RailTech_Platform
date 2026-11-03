import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "../../../shared/api/errors";
import type {
  EdsFile,
  InboundMail,
  InboundMailCounts,
  InboundMailMessage,
  InboundMailReply,
  InboundMailTypeDefaultAction,
  InboundMailView,
} from "../../../shared/api/generated/model";
import type { Attachment } from "../new/formModel";
import type { RegisterValues } from "../register/registerModel";

export const ADMIN_MAIL_PATH = "/admin/mail";
/** Вкладка «Подозрительные» списка «Входящая почта» (W18A-P2-2). */
export const SPAM_TAB_PATH = "/eds/mail?tab=spam";

/** Список писем первой линии и «моих» писем сотрудника без раздела первой линии (W18A-P2-3). */
export const MAIL_LIST_PATH = "/eds/mail";
export const OWN_MAIL_LIST_PATH = "/eds/my-mail";

export function listPath(own: boolean): string {
  return own ? OWN_MAIL_LIST_PATH : MAIL_LIST_PATH;
}

export function mailPath(id: number, own = false): string {
  return `${listPath(own)}/${String(id)}`;
}

export type MailTab = InboundMailView;

/** Вкладки по порядку: первая линия — шесть, сотрудник со своим письмом — три. */
export const CLERK_TABS: readonly MailTab[] = ["new", "mine", "in_work", "done", "spam", "all"];
export const OWN_TABS: readonly MailTab[] = ["mine", "done", "all"];
/** Вкладки, где можно выбрать письма и отправить в архив пачкой (первая линия). */
export const BULK_TABS: readonly MailTab[] = ["new", "in_work", "all", "spam"];

/** «Вернуть в Новые» у разобранного архивом, ответом или «прайс загружен» (ничего не потеряно). */
export function canReturn(mail: Pick<InboundMail, "status" | "result">): boolean {
  const outcome = mail.result?.outcome;
  return (
    mail.status === "done" &&
    (outcome === "archived" || outcome === "replied" || outcome === "price")
  );
}

/** Ключ слова статуса: «Новое · ответ в цепочке» у разобранного, на которое ответил клиент. */
export function statusKey(mail: Pick<InboundMail, "status" | "thread_reply">): string {
  return mail.status === "new" && mail.thread_reply
    ? "mail.status.newReply"
    : `mail.status.${mail.status}`;
}

export function tabCount(counts: InboundMailCounts, tab: MailTab): number {
  return counts[tab];
}

/** Письмо уже ведёт другой сотрудник (409 `mail_in_work_by_other` BFF): имя и время взятия из `details`. */
export function inWorkByOther(error: unknown): { name: string; since: string | null } | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (error.details["reason"] !== "mail_in_work_by_other") return null;
  const name = error.details["assignee_name"];
  const since = error.details["assigned_at"];
  return {
    name: typeof name === "string" ? name : "",
    since: typeof since === "string" ? since : null,
  };
}

export function registerFromMailPath(id: number): string {
  return `/eds/register?mail=${String(id)}`;
}

/** Действия по типу письма (MAIL-TYPES): порядок меню «Другое действие»; что делает каждое, решает код CRM. */
export const MAIL_ACTIONS: readonly InboundMailTypeDefaultAction[] = [
  "register_incoming",
  "create_lead",
  "supplier_price",
  "to_accountant",
  "archive_mailing",
  "reply_template",
  "suspicious",
];

/** Существующая загрузка прайса поставщика (CAT-1): «Расчёт · Номенклатура и поставщики · Загрузка прайса». */
export const PRICE_UPLOAD_PATH = "/erp/catalog?part=import";

/** Дата поступления письма в поясе компании (`YYYY-MM-DD`). */
export function receivedDate(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent" }).format(new Date(iso));
}

const SUMMARY_MAX = 2000;

/** Когда письмо пришло в ящик: у загруженного «из истории» — дата самого письма, а не день загрузки (W18A-P2-2). */
export function arrivedAt(
  mail: Pick<InboundMail, "from_history" | "sent_at" | "received_at">,
): string {
  return mail.from_history && mail.sent_at ? mail.sent_at : mail.received_at;
}

/** Предзаполнение формы «Зарегистрировать входящее» из письма (W18A-P2): человек проверяет и правит. */
export function prefillFromMail(
  mail: InboundMail,
  files: readonly EdsFile[],
): Partial<RegisterValues> {
  const attachments: Attachment[] = files.map((file) => ({
    key: file.id,
    id: file.id,
    name: file.name,
    size: file.size,
    status: "done",
  }));
  const summary = mail.assist.summary ?? mail.text.slice(0, SUMMARY_MAX);
  // Адресат — сотрудник из «Кому», «ознакомить» — сотрудники из копии (1С:Документооборот, Directum: «Адресат» и «Для сведения»)
  const addressee = mail.to.find((a) => a.staff)?.staff;
  const acquaint = [
    ...new Set(mail.cc.flatMap((a) => (a.staff ? [String(a.staff.id)] : []))),
  ].filter((id) => id !== String(addressee?.id));
  return {
    ...(addressee ? { addresseeId: String(addressee.id) } : {}),
    ...(acquaint.length > 0 ? { draftKind: "info" as const, draftAcquaintIds: acquaint } : {}),
    kind: "",
    receiptMethod: "email",
    senderName: mail.client?.name ?? (mail.from_name || mail.from_email),
    senderInn: mail.inns.length === 1 ? (mail.inns[0] ?? "") : "",
    receivedAt: receivedDate(arrivedAt(mail)),
    subject: mail.subject.slice(0, 300),
    summary,
    attachments,
    sourceMailId: mail.id,
  };
}

/** После действия по письму — свежие очередь, бейджи «Моих задач» и меню. */
export function useRefreshMail(): () => Promise<void> {
  const client = useQueryClient();
  return useCallback(
    () =>
      client.invalidateQueries({
        predicate: (query) => {
          const head = query.queryKey[0];
          return (
            typeof head === "string" &&
            (head.startsWith("/api/v1/inbound-mail") ||
              head.startsWith("/api/v1/queue") ||
              head.startsWith("/api/v1/menu-counters"))
          );
        },
      }),
    [client],
  );
}

export type TimelineEntry =
  | { kind: "in"; at: string; message: InboundMailMessage }
  | { kind: "out"; at: string; reply: InboundMailReply };

/** Переписка записи одним списком по времени: входящие письма и наши ответы из журнала почты. */
export function timeline(mail: Pick<InboundMail, "messages" | "replies">): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...mail.messages.map((message) => ({ kind: "in" as const, at: message.at, message })),
    ...mail.replies.map((reply) => ({
      kind: "out" as const,
      at: reply.sent_at ?? reply.created_at,
      reply,
    })),
  ];
  return entries.sort((a, b) => a.at.localeCompare(b.at));
}
