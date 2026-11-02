import { HttpResponse, delay, http } from "msw";

import type {
  EdsFile,
  ImapConnector,
  InboundMail,
  InboundMailItem,
  QueueCard,
  QueueItem,
} from "../shared/api/generated/model";
import type { MockRole } from "./fixtures/roles";

/**
 * Моки входящей почты общего ящика (W18A-P2): очередь первой линии, карточка письма, действия, приём в «Подключениях».
 * Хранилище — `localStorage` страницы, как у обращений: письмо, разобранное делопроизводителем, не возвращается после
 * перезагрузки. `localStorage["rt-pf-mock-imap-off"] = "1"` — приём не настроен (пустая очередь и подсказка). Данные
 * вымышленные.
 */
const KEY = "rt-pf-mock-inbound-mail";
export const MOCK_IMAP_OFF_KEY = "rt-pf-mock-imap-off";
const PDF = "%PDF-1.4\n% mock\n";

type StoredMail = InboundMail;

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function seed(): StoredMail[] {
  const base = {
    to: ["info@company.example"],
    skipped: [],
    too_large: false,
    inns: [],
    letter_number: null,
    letter_ref: null,
    result_lead: null,
    archive_reason: null,
    handled_at: null,
    replies: [],
    lead: null,
    client: null,
  } satisfies Partial<StoredMail>;
  return [
    {
      ...base,
      id: 17,
      status: "new",
      from_email: "buh@supplier-demo.example",
      from_name: "ООО «Демо-Поставка»",
      subject: "Акт сверки за октябрь",
      received_at: minutesAgo(25),
      sent_at: minutesAgo(26),
      preview: "Добрый день! Направляем акт сверки взаимных расчётов за октябрь 2026 года.",
      text:
        "Добрый день!\n\nНаправляем акт сверки взаимных расчётов за октябрь 2026 года. Просим подписать и " +
        "вернуть скан до 10 ноября.\n\nС уважением,\nбухгалтерия ООО «Демо-Поставка»\nИНН 301234567",
      attachments_count: 1,
      attachments: [
        { index: 0, name: "акт-сверки-октябрь.pdf", content_type: "application/pdf", size: 48213 },
      ],
      skipped: [{ name: "macros.xlsm", reason: "type" }],
      inns: ["301234567"],
      client: { id: 42, number: "42", name: "ООО «Демо-Поставка»" },
      assist: {
        status: "done",
        kind: "supplier_doc",
        summary: "Поставщик прислал акт сверки за октябрь, просит подписать до 10 ноября.",
        action: "register",
      },
    },
    {
      ...base,
      id: 18,
      status: "new",
      from_email: "zakaz@rail-client-demo.example",
      from_name: "Алия Демо",
      subject: "Запрос КП на стрелочные переводы",
      received_at: minutesAgo(70),
      sent_at: minutesAgo(71),
      preview: "Здравствуйте. Просим направить коммерческое предложение на 6 стрелочных переводов.",
      text:
        "Здравствуйте.\n\nПросим направить коммерческое предложение на 6 стрелочных переводов Р65 с поставкой " +
        "в Ташкент до конца года.\n\nАлия Демо, отдел снабжения",
      attachments_count: 0,
      attachments: [],
      // Подсказки ещё нет: помощник — только по кнопке «Подсказать» (решение юриста 2026-11-02)
      assist: { status: "none", kind: null, summary: null, action: null },
    },
    {
      ...base,
      id: 19,
      status: "new",
      from_email: "news@promo-demo.example",
      from_name: "Промо-рассылка",
      subject: "Скидки недели на канцтовары",
      received_at: minutesAgo(180),
      sent_at: minutesAgo(181),
      preview: "Только до пятницы — скидки до 30% на бумагу и картриджи.",
      text: "Только до пятницы — скидки до 30% на бумагу и картриджи.",
      attachments_count: 0,
      attachments: [],
      assist: {
        status: "done",
        kind: "other",
        summary: "Рекламная рассылка канцтоваров.",
        action: "archive",
      },
    },
  ];
}

let memory: StoredMail[] | null = null;

/** Тесты: начальные письма заново. */
export function resetInboundMailMock(): void {
  memory = null;
}

function read(): StoredMail[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as StoredMail[];
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  memory ??= seed();
  return memory;
}

function write(mails: StoredMail[]): void {
  memory = mails;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(mails));
  } catch {
    // в памяти
  }
}

function imapOff(): boolean {
  try {
    return window.localStorage.getItem(MOCK_IMAP_OFF_KEY) === "1";
  } catch {
    return false;
  }
}

function itemOf(mail: StoredMail): InboundMailItem {
  return {
    id: mail.id,
    status: mail.status,
    from_email: mail.from_email,
    from_name: mail.from_name,
    subject: mail.subject,
    received_at: mail.received_at,
    sent_at: mail.sent_at,
    preview: mail.preview,
    attachments_count: mail.attachments_count,
    assist: mail.assist,
    client: mail.client,
    lead: mail.lead,
  };
}

function update(id: number, change: (mail: StoredMail) => StoredMail): StoredMail | null {
  const mails = read();
  const at = mails.findIndex((m) => m.id === id);
  if (at < 0) return null;
  const current = mails[at];
  if (!current) return null;
  const next = change(current);
  mails[at] = next;
  write(mails);
  return next;
}

const conflict = () =>
  HttpResponse.json(
    { code: "CONFLICT", message: "Письмо уже обработано: обновите очередь.", source: "crm" },
    { status: 409 },
  );
const notFound = () =>
  HttpResponse.json(
    { code: "NOT_FOUND", message: "Письмо не найдено.", source: "crm" },
    { status: 404 },
  );

/** Делопроизводитель зарегистрировал ВХ из письма — как CRM по событию `letter.registered`. */
export function markMailRegistered(id: number, number: string): void {
  update(id, (mail) =>
    mail.status === "new"
      ? {
          ...mail,
          status: "registered",
          letter_number: number,
          letter_ref: `/eds/inbox/${encodeURIComponent(number)}`,
          handled_at: new Date().toISOString(),
        }
      : mail,
  );
}

function clerkRole(view: readonly MockRole[]): MockRole | undefined {
  return view.find((r) => r.access["crm.leads.triage"] === "full");
}

function waiting(): StoredMail[] {
  return imapOff() ? [] : read().filter((m) => m.status === "new");
}

/** Строки «Моих задач» первой линии (как `mail_rows` BFF). */
export function inboundMailQueueItems(view: readonly MockRole[]): QueueItem[] {
  const role = clerkRole(view);
  if (!role) return [];
  return waiting().map((mail) => ({
    id: `mail:${String(mail.id)}`,
    role_id: role.id,
    kind: "inbound_mail" as const,
    title: `Разобрать письмо: ${mail.subject}`,
    subtitle: [mail.from_name || mail.from_email, mail.assist.summary ?? mail.preview].join(" · "),
    due_label: "later" as const,
    object: {
      kind: "letter" as const,
      number: mail.from_email,
      title: mail.subject,
      path: `/eds/mail/${String(mail.id)}`,
    },
  }));
}

export function inboundMailCards(view: readonly MockRole[]): QueueCard[] {
  if (!clerkRole(view)) return [];
  return [
    {
      key: "inbound_mail",
      label: "Входящая почта",
      count: waiting().length,
      hint: imapOff()
        ? "Почта не подключена — Настройки · Подключения · Почта"
        : "Документы · Входящая почта",
      path: "/eds/mail",
    },
  ];
}

export function inboundMailCounters(view: readonly MockRole[]) {
  if (!clerkRole(view)) return [];
  const count = waiting().length;
  return [{ module: "eds" as const, section: "mail", count, attention: count > 0 }];
}

let imap: ImapConnector = {
  configured: true,
  host: "imap.mail.example",
  port: 993,
  security: "ssl",
  mailbox: "INBOX",
  assist_enabled: true,
  username: "info@company.example",
  password_configured: true,
  password_last4: "x7Qa",
  password_updated_at: minutesAgo(60 * 24),
  secrets_enabled: true,
  last_poll_at: minutesAgo(1),
  last_ok_at: minutesAgo(1),
  last_error_kind: null,
  last_error: null,
};

export const inboundMailHandlers = [
  http.get("*/inbound-mail", () =>
    HttpResponse.json({
      items: waiting().map(itemOf),
      total: waiting().length,
      mailbox: {
        configured: !imapOff(),
        last_poll_at: imapOff() ? null : minutesAgo(1),
        last_ok_at: imapOff() ? null : minutesAgo(1),
        last_error_kind: null,
      },
    }),
  ),
  http.get("*/inbound-mail/:id/attachments/:index", () =>
    HttpResponse.text(PDF, { headers: { "content-type": "application/octet-stream" } }),
  ),
  http.get("*/inbound-mail/:id", ({ params }) => {
    const mail = read().find((m) => m.id === Number(params.id));
    return mail ? HttpResponse.json(mail) : notFound();
  }),
  http.post("*/inbound-mail/:id/eds-files", async ({ params }) => {
    await delay(150);
    const mail = read().find((m) => m.id === Number(params.id));
    if (!mail) return notFound();
    const files: EdsFile[] = mail.attachments.map((a) => ({
      id: crypto.randomUUID(),
      name: a.name,
      content_type: a.content_type,
      size: a.size,
    }));
    return HttpResponse.json(files);
  }),
  http.post("*/inbound-mail/:id/assist", async ({ params }) => {
    await delay(150);
    const updated = update(Number(params.id), (mail) =>
      mail.assist.status === "done"
        ? mail
        : {
            ...mail,
            assist: {
              status: "done",
              kind: "buyer",
              summary: "Покупатель просит КП на стрелочные переводы с поставкой до конца года.",
              action: "lead",
            },
          },
    );
    return updated ? HttpResponse.json(updated.assist) : notFound();
  }),
  http.post("*/inbound-mail/:id/lead", ({ params }) => {
    const id = Number(params.id);
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    if (current.status !== "new") return conflict();
    const leadId = 2050 + id;
    update(id, (mail) => ({
      ...mail,
      status: "lead",
      result_lead: { id: leadId, number: `L-${String(leadId)}`, name: mail.from_name },
      handled_at: new Date().toISOString(),
    }));
    return HttpResponse.json({
      lead_id: leadId,
      lead_number: `L-${String(leadId)}`,
      created: true,
    });
  }),
  http.post("*/inbound-mail/:id/archive", async ({ params, request }) => {
    const id = Number(params.id);
    const body = (await request.json()) as { reason: string };
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    if (current.status !== "new") return conflict();
    update(id, (mail) => ({
      ...mail,
      status: "archived",
      archive_reason: body.reason,
      handled_at: new Date().toISOString(),
    }));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/reply", async ({ params, request }) => {
    const id = Number(params.id);
    await request.json();
    const now = new Date().toISOString();
    const updated = update(id, (mail) => ({
      ...mail,
      replies: [
        ...mail.replies,
        {
          id: mail.replies.length + 1,
          to_email: mail.from_email,
          subject: `Re: ${mail.subject}`,
          status: "queued",
          created_at: now,
          sent_at: null,
        },
      ],
    }));
    if (!updated) return notFound();
    return HttpResponse.json(updated.replies[updated.replies.length - 1]);
  }),
  http.get("*/admin/integrations/imap", () => HttpResponse.json(imap)),
  http.put("*/admin/integrations/imap", async ({ request }) => {
    const body = (await request.json()) as {
      host: string;
      port?: number;
      security?: "ssl" | "starttls";
      mailbox?: string;
      assist_enabled?: boolean;
      username?: string | null;
      imap_password?: string | null;
    };
    imap = {
      ...imap,
      host: body.host,
      port: body.port ?? 993,
      security: body.security ?? "ssl",
      mailbox: body.mailbox ?? "INBOX",
      assist_enabled: body.assist_enabled ?? true,
      username: body.username ?? imap.username,
      password_last4: body.imap_password ? body.imap_password.slice(-4) : imap.password_last4,
      configured: Boolean(body.host),
    };
    return HttpResponse.json(imap);
  }),
  http.post("*/admin/integrations/imap/check", () =>
    HttpResponse.json({ ok: true, error_kind: null, detail: null, messages: 128, latency_ms: 240 }),
  ),
];
