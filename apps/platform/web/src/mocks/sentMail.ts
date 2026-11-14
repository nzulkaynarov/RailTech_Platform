import { HttpResponse, http } from "msw";

import type { SentMail, SentMailStatus } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

/** «Почта · Отправленные» (план 2.8) на моках: журнал писем ансамбля с текстом по запросу и «Отправить ещё раз». */
const ROWS: (SentMail & { text: string })[] = [
  {
    id: "41",
    to: "gni-mirabad@example.uz",
    subject: "ИСХ-014/26 · Ответ на требование о пояснениях",
    status: "sent",
    error: null,
    source: "eds",
    attachments: 1,
    resendable: true,
    requested_by: "Демо Делопроизводителев",
    created_at: "2026-11-14T10:15:00+05:00",
    sent_at: "2026-11-14T10:15:04+05:00",
    path: "/eds/documents?scope=all&q=%D0%98%D0%A1%D0%A5-014%2F26",
    text: "Здравствуйте!\n\nНаправляем ответ на требование. Письмо — во вложении.\n\nС уважением,\nООО «RailTech»",
  },
  {
    id: "40",
    to: "zakupki@demo-rail.example.uz",
    subject: "КП-2026/118 · Коммерческое предложение",
    status: "sent",
    error: null,
    source: "erp",
    attachments: 1,
    resendable: true,
    requested_by: "Демо Менеджеров",
    created_at: "2026-11-13T16:40:00+05:00",
    sent_at: "2026-11-13T16:40:06+05:00",
    path: null,
    text: "Добрый день!\n\nНаправляем коммерческое предложение КП-2026/118.",
  },
  {
    id: "39",
    to: "old-address@example.uz",
    subject: "Приглашение в кабинет клиента",
    status: "failed",
    error: "Почтовый сервер адресата отказал: ящик не существует",
    source: "crm",
    attachments: 0,
    resendable: false,
    requested_by: "Демо Менеджеров",
    created_at: "2026-11-12T09:05:00+05:00",
    sent_at: null,
    path: null,
    // Приглашение (письмо со входом): текст не хранится и не отправляется ещё раз (MAIL-2).
    text: "",
  },
];

/** Строка списка без текста: текст — только отдельным запросом, как в CRM. */
function listed(row: SentMail & { text: string }): SentMail {
  return Object.fromEntries(
    Object.entries(row).filter(([key]) => key !== "text"),
  ) as unknown as SentMail;
}

const expired = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );

export const sentMailHandlers = [
  http.get("*/api/v1/mail/sent", ({ request }) => {
    if (!readSession()) return expired();
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const status = url.searchParams.get("status") as SentMailStatus | null;
    const items = ROWS.filter(
      (row) =>
        (!q || `${row.to} ${row.subject}`.toLowerCase().includes(q)) &&
        (!status || row.status === status),
    ).map(listed);
    return HttpResponse.json({ items, next_cursor: null });
  }),
  http.get("*/api/v1/mail/sent/:id", ({ params }) => {
    if (!readSession()) return expired();
    const row = ROWS.find((r) => r.id === params["id"]);
    if (!row)
      return HttpResponse.json(
        { code: "NOT_FOUND", message: "Не найдено", source: "crm" },
        { status: 404 },
      );
    return HttpResponse.json({
      id: row.id,
      text: row.text || null,
      attachments: row.attachments ? ["letter.pdf"] : [],
    });
  }),
  http.post("*/api/v1/mail/sent/:id/resend", ({ params }) => {
    if (!readSession()) return expired();
    const row = ROWS.find((r) => r.id === params["id"]);
    if (!row?.resendable)
      return HttpResponse.json(
        {
          code: "CONFLICT",
          message: "Письмо нельзя отправить ещё раз",
          source: "crm",
          details: { reason: "mail_not_resendable" },
        },
        { status: 409 },
      );
    const copy = {
      ...row,
      id: String(Math.max(...ROWS.map((r) => Number(r.id))) + 1),
      status: "queued" as const,
      resendable: false,
      error: null,
      sent_at: null,
      created_at: new Date().toISOString(),
    };
    ROWS.unshift(copy);
    return HttpResponse.json(listed(copy), { status: 201 });
  }),
];
