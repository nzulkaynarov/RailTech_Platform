import { HttpResponse, delay, http } from "msw";

import type {
  EdsFile,
  ImapConnector,
  ImapHistory,
  ImapSettingsIn,
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
 * вымышленные. W18A-P2-2: письмо из папки «Спам» — во вкладке «Подозрительные»; «Загрузить письма за период» в
 * «Подключениях» добавляет два письма «из истории» (не строками «Моих задач»).
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
    from_history: false,
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
    {
      ...base,
      id: 20,
      status: "spam",
      from_email: "tender@zavod-demo.example",
      from_name: "АО «Демо-Завод»",
      subject: "Приглашение к участию в тендере на поставку шпал",
      received_at: minutesAgo(240),
      sent_at: minutesAgo(241),
      preview:
        "Приглашаем принять участие в закупке железобетонных шпал. Документация во вложении.",
      text:
        "Добрый день!\n\nПриглашаем принять участие в закупке железобетонных шпал. Документация во вложении, " +
        "приём заявок до 20 ноября.\n\nОтдел закупок АО «Демо-Завод»",
      attachments_count: 0,
      attachments: [],
      assist: { status: "none", kind: null, summary: null, action: null },
    },
  ];
}

/** Письма, которые «Загрузить письма за период» найдёт в ящике (старше 3 дней — «из истории»). */
function historyMails(): StoredMail[] {
  const [first] = seed();
  if (!first) return [];
  const day = 24 * 60;
  return [
    {
      ...first,
      id: 31,
      from_email: "office@partner-demo.example",
      from_name: "ООО «Демо-Партнёр»",
      subject: "Договор поставки — подписанный экземпляр",
      received_at: minutesAgo(1),
      sent_at: minutesAgo(9 * day),
      preview: "Направляем подписанный с нашей стороны договор поставки № 14.",
      text: "Направляем подписанный с нашей стороны договор поставки № 14.",
      attachments_count: 0,
      attachments: [],
      skipped: [],
      inns: [],
      client: null,
      assist: { status: "none", kind: null, summary: null, action: null },
      from_history: true,
    },
    {
      ...first,
      id: 32,
      from_email: "sklad@logist-demo.example",
      from_name: "Демо-Логистика",
      subject: "Счёт за хранение за сентябрь",
      received_at: minutesAgo(1),
      sent_at: minutesAgo(21 * day),
      preview: "Счёт за ответственное хранение груза за сентябрь.",
      text: "Счёт за ответственное хранение груза за сентябрь.",
      attachments_count: 0,
      attachments: [],
      skipped: [],
      inns: [],
      client: null,
      assist: { status: "none", kind: null, summary: null, action: null },
      from_history: true,
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
    from_history: mail.from_history,
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

function byStatus(status: string, history: boolean | null): StoredMail[] {
  if (imapOff()) return [];
  return read()
    .filter((m) => m.status === status && (history === null || m.from_history === history))
    .sort((a, b) => (b.sent_at ?? b.received_at).localeCompare(a.sent_at ?? a.received_at));
}

/** Строки «Моих задач» — без писем «из истории» (как `history=false` у BFF). */
function waiting(): StoredMail[] {
  return byStatus("new", false);
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
  folders: [{ name: "INBOX", label: "INBOX", spam: false }],
  history: null,
};

/** Ход загрузки истории: каждое чтение настроек — ещё одна пачка, как фоновая задача. */
function advanceHistory(): void {
  const row = imap.history;
  if (!row || row.status !== "running") return;
  const processed = Math.min(row.found, row.processed + 1);
  let next: ImapHistory = { ...row, processed };
  if (processed >= row.found) {
    const known = new Set(read().map((m) => m.id));
    const fresh = historyMails().filter((m) => !known.has(m.id));
    write([...read(), ...fresh]);
    next = {
      ...next,
      status: "done",
      created: fresh.length,
      finished_at: new Date().toISOString(),
    };
  }
  imap = { ...imap, history: next };
}

const FOLDERS = [
  { name: "INBOX", label: "INBOX", junk: false, selectable: true },
  { name: "Sent", label: "Sent", junk: false, selectable: true },
  { name: "Spam", label: "Spam", junk: true, selectable: true },
  { name: "Trash", label: "Trash", junk: false, selectable: true },
];

function spamAction(id: number, change: (mail: StoredMail) => StoredMail) {
  const current = read().find((m) => m.id === id);
  if (!current) return notFound();
  if (current.status !== "spam") return conflict();
  update(id, change);
  return new HttpResponse(null, { status: 204 });
}

export const inboundMailHandlers = [
  http.get("*/inbound-mail", ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status") ?? "new";
    const raw = url.searchParams.get("history");
    const items = byStatus(status, raw === null ? null : raw === "true");
    return HttpResponse.json({
      items: items.map(itemOf),
      total: items.length,
      counts: {
        new: byStatus("new", null).length,
        history: byStatus("new", true).length,
        spam: byStatus("spam", null).length,
      },
      mailbox: {
        configured: !imapOff(),
        last_poll_at: imapOff() ? null : minutesAgo(1),
        last_ok_at: imapOff() ? null : minutesAgo(1),
        last_error_kind: null,
      },
    });
  }),
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
  http.post("*/inbound-mail/:id/not-spam", ({ params }) =>
    spamAction(Number(params.id), (mail) => ({ ...mail, status: "new" })),
  ),
  http.post("*/inbound-mail/:id/discard", ({ params }) =>
    spamAction(Number(params.id), (mail) => ({
      ...mail,
      status: "archived",
      archive_reason: "Спам",
      handled_at: new Date().toISOString(),
    })),
  ),
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
  http.get("*/admin/integrations/imap", () => {
    advanceHistory();
    return HttpResponse.json(imap);
  }),
  http.put("*/admin/integrations/imap", async ({ request }) => {
    const body = (await request.json()) as ImapSettingsIn;
    const folders = body.folders
      ? body.folders.map((f) => ({ name: f.name, label: f.name, spam: Boolean(f.spam) }))
      : imap.folders;
    imap = {
      ...imap,
      folders,
      host: body.host,
      port: body.port ?? 993,
      security: body.security ?? "ssl",
      mailbox: folders.find((f) => !f.spam)?.name ?? body.mailbox ?? "INBOX",
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
  http.post("*/admin/integrations/imap/folders", async () => {
    await delay(150);
    return HttpResponse.json({
      ok: true,
      error_kind: null,
      detail: null,
      folders: FOLDERS,
      spam_suggestion: "Spam",
    });
  }),
  http.post("*/admin/integrations/imap/history", async ({ request }) => {
    const body = (await request.json()) as { days: number };
    if (imap.history?.status === "running") return HttpResponse.json(imap.history);
    imap = {
      ...imap,
      history: {
        id: (imap.history?.id ?? 0) + 1,
        days: body.days,
        status: "running",
        found: 3,
        processed: 0,
        created: 0,
        limited: false,
        error_kind: null,
        started_at: new Date().toISOString(),
        finished_at: null,
      },
    };
    return HttpResponse.json(imap.history);
  }),
];

/** Тесты: настройки приёма заново. */
export function resetImapMock(): void {
  imap = { ...imap, folders: [{ name: "INBOX", label: "INBOX", spam: false }], history: null };
}
