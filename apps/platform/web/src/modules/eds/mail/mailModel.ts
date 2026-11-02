import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import type { EdsFile, InboundMail } from "../../../shared/api/generated/model";
import type { Attachment } from "../new/formModel";
import type { RegisterValues } from "../register/registerModel";

export const ADMIN_MAIL_PATH = "/admin/integrations?card=mail&panel=open";

export function mailPath(id: number): string {
  return `/eds/mail/${String(id)}`;
}

export function registerFromMailPath(id: number): string {
  return `/eds/register?mail=${String(id)}`;
}

/** Вид документа формы P8 по подсказке помощника: только однозначные случаи, остальное выбирает человек. */
const KIND_BY_ASSIST: Partial<Record<string, string>> = {
  supplier_doc: "supplier",
  other: "other",
};

/** Дата поступления письма в поясе компании (`YYYY-MM-DD`). */
export function receivedDate(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent" }).format(new Date(iso));
}

const SUMMARY_MAX = 2000;

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
  return {
    kind: (mail.assist.kind && KIND_BY_ASSIST[mail.assist.kind]) ?? "",
    receiptMethod: "email",
    senderName: mail.client?.name ?? (mail.from_name || mail.from_email),
    senderInn: mail.inns.length === 1 ? (mail.inns[0] ?? "") : "",
    receivedAt: receivedDate(mail.received_at),
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
