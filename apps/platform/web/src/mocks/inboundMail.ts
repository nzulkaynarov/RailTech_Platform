import { HttpResponse, delay, http } from "msw";

import type {
  EdsFile,
  ImapConnector,
  ImapHistory,
  ImapSettingsIn,
  InboundMailCounts,
  InboundMailItem,
  InboundMailPerson,
  InboundMailView,
  QueueCard,
  QueueItem,
} from "../shared/api/generated/model";
import { resetDictionariesMock, setMailTypeUsage } from "./dictionaries";
import { type StoredMail, minutesAgo, seed } from "./inboundMailSeed";
import { resetMailTypesMock, resolveType, setRuleApplier } from "./mailTypes";
import { readSession, sessionRoles } from "./mockSession";
import type { MockRole } from "./fixtures/roles";

/**
 * Моки входящей почты общего ящика (W18A-P2, W18A-P2-3): очередь первой линии, «в работе», цепочки, адресаты, карточка,
 * действия, приём в «Подключениях». Хранилище — `localStorage` страницы, как у обращений: разобранное письмо не возвращается
 * после перезагрузки. `localStorage["rt-pf-mock-imap-off"] = "1"` — приём не настроен. Данные вымышленные. «Я» — сотрудник
 * сессии; его id в письмах совпадает с `Me.id`, чтобы «в работе у меня» сходилось (в настоящем BFF это числовой id CRM).
 * Сотрудник без раздела первой линии видит только свои письма: исполнитель или «адресовано лично».
 */
const KEY = "rt-pf-mock-inbound-mail";
export const MOCK_IMAP_OFF_KEY = "rt-pf-mock-imap-off";
const PDF = "%PDF-1.4\n% mock\n";

interface Viewer {
  id: string;
  name: string;
  full: boolean;
  /** Право загружать прайсы (`erp.stock: full` + цены поставщиков) — по объединению ВСЕХ ролей человека. */
  stock: boolean;
}

function viewer(): Viewer {
  const session = readSession();
  const roles = session ? sessionRoles(session) : undefined;
  const full = roles?.view.some((r) => r.access["crm.leads.triage"] === "full") ?? false;
  const stock = roles
    ? roles.all.some((r) => r.access["erp.stock"] === "full") &&
      roles.all.some((r) => r.restricted_fields.includes("supplier_prices"))
    : false;
  return { id: roles?.user.id ?? "u-demo-registrar", name: roles?.user.name ?? "Я", full, stock };
}

function person(v: Viewer): InboundMailPerson {
  return { id: v.id as unknown as number, name: v.name };
}

const isMine = (mail: StoredMail, v: Viewer) =>
  mail.assignee !== null && String(mail.assignee.id) === v.id;

/** Письма, где сотрудник назван (соадресат, «для сведения») — только «лично адресованные». */
function named(mail: StoredMail, v: Viewer): boolean {
  return (
    mail.personal &&
    [...mail.to, ...mail.cc].some((a) => a.staff !== null && String(a.staff.id) === v.id)
  );
}

function visible(mail: StoredMail, v: Viewer): boolean {
  return v.full || isMine(mail, v) || named(mail, v);
}

/** Письма «из истории», которые «Загрузить письма за период» найдёт в ящике (старше 3 дней). */
function historyMails(): StoredMail[] {
  const [first] = seed();
  if (!first) return [];
  const day = 24 * 60;
  const mk = (
    id: number,
    email: string,
    name: string,
    subject: string,
    text: string,
    age: number,
  ) => ({
    ...first,
    id,
    from_email: email,
    from_name: name,
    subject,
    received_at: minutesAgo(1),
    sent_at: minutesAgo(age * day),
    activity_at: minutesAgo(age * day),
    preview: text,
    text,
    attachments_count: 0,
    attachments: [],
    skipped: [],
    inns: [],
    client: null,
    to: first.to.slice(0, 1),
    cc: [],
    unread: true,
    assist: { status: "none" as const, kind: null, summary: null, action: null },
    from_history: true,
    messages: [
      {
        id,
        from_email: email,
        from_name: name,
        at: minutesAgo(age * day),
        text,
        text_tail: "",
        html: null,
        html_remote_images: 0,
        attachments: [],
        new_participant: false,
      },
    ],
    journal: [],
  });
  return [
    mk(
      31,
      "office@partner-demo.example",
      "ООО «Демо-Партнёр»",
      "Договор поставки — подписанный экземпляр",
      "Направляем подписанный с нашей стороны договор поставки № 14.",
      9,
    ),
    mk(
      32,
      "sklad@logist-demo.example",
      "Демо-Логистика",
      "Счёт за хранение за сентябрь",
      "Счёт за ответственное хранение груза за сентябрь.",
      21,
    ),
  ];
}

let memory: StoredMail[] | null = null;

/** Тесты: начальные письма заново. */
export function resetInboundMailMock(): void {
  memory = null;
  // Типы и правила живут рядом с письмами: сброс почты возвращает стартовый набор.
  resetMailTypesMock();
  resetDictionariesMock();
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

/** Кто подтверждает оплату (роль с «Платежи: полный») — адресаты «Передать бухгалтеру». */
const HANDOVER_TARGETS: Record<"payments" | "price", InboundMailPerson[]> = {
  payments: [{ id: "u-demo-accountant" as unknown as number, name: "Демо Бухгалтеров" }],
  price: [{ id: "u-demo-supply" as unknown as number, name: "Демо Снабженцев" }],
};

const CARD_ONLY = new Set([
  "to",
  "cc",
  "text",
  "attachments",
  "skipped",
  "too_large",
  "inns",
  "messages",
  "replies",
  "journal",
  "reply_all_copy",
  "personal_label",
  "reply_to",
  "reply_options",
]);

/** Строка списка — карточка без полей, которые есть только у неё. */
function itemOf(mail: StoredMail): InboundMailItem {
  return Object.fromEntries(
    Object.entries(withType(mail)).filter(([key]) => !CARD_ONLY.has(key)),
  ) as unknown as InboundMailItem;
}

/** Тип письма с актуальными названием, цветом и действием из справочника (админ мог их поменять). */
function withType(mail: StoredMail): StoredMail {
  if (!mail.type) return mail;
  return { ...mail, type: resolveType(mail.type.code, mail.type.source) ?? mail.type };
}

function update(id: number, change: (mail: StoredMail) => StoredMail): StoredMail | null {
  const mails = read();
  const at = mails.findIndex((m) => m.id === id);
  const current = mails[at];
  if (!current) return null;
  const next = change(current);
  mails[at] = next;
  write(mails);
  return next;
}

const failure = (
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
) =>
  HttpResponse.json({ code, message, source: "crm", ...(details ? { details } : {}) }, { status });
const conflict = () => failure(409, "CONFLICT", "Письмо уже обработано: обновите очередь.");
const notFound = () => failure(404, "NOT_FOUND", "Письмо не найдено.");
const forbidden = () => failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");

const timeOf = (iso: string | null) =>
  iso
    ? new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Tashkent",
      }).format(new Date(iso))
    : "";

function heldBy(mail: StoredMail) {
  const name = mail.assignee?.name ?? "";
  return failure(409, "CONFLICT", `Письмо уже в работе у ${name} с ${timeOf(mail.assigned_at)}.`, {
    reason: "mail_in_work_by_other",
    assignee_name: name,
    assigned_at: mail.assigned_at,
  });
}

function logged(
  mail: StoredMail,
  v: Viewer,
  action: string,
  detail: string | null = null,
): StoredMail {
  return {
    ...mail,
    journal: [...mail.journal, { at: new Date().toISOString(), action, actor: person(v), detail }],
  };
}

function assigned(mail: StoredMail, v: Viewer, action: string): StoredMail {
  return logged(
    {
      ...mail,
      status: "in_work",
      assignee: person(v),
      assigned_at: new Date().toISOString(),
      thread_reply: false,
    },
    v,
    action,
  );
}

type Claim = { mail: StoredMail } | { response: Response };

/** Первое действие берёт письмо; чужое «в работе» — 409; разобранное и подозрительное — «уже обработано». */
function claim(id: number, v: Viewer): Claim {
  const current = read().find((m) => m.id === id);
  if (!current || !visible(current, v)) return { response: current ? forbidden() : notFound() };
  if (current.status === "done" || current.status === "spam") return { response: conflict() };
  if (current.status !== "new" && !isMine(current, v)) return { response: heldBy(current) };
  if (current.status !== "new") return { mail: current };
  return { mail: update(id, (mail) => assigned(mail, v, "take")) ?? current };
}

function finish(
  id: number,
  v: Viewer,
  result: {
    outcome: "registered" | "lead" | "replied" | "archived" | "price" | "handled";
  } & Partial<NonNullable<StoredMail["result"]>>,
): void {
  update(id, (mail) => ({
    ...mail,
    status: "done",
    unread: false,
    result: {
      by: person(v),
      at: new Date().toISOString(),
      letter_number: null,
      letter_ref: null,
      lead: null,
      reason: null,
      ...result,
    },
  }));
}

/** Делопроизводитель зарегистрировал ВХ из письма — как CRM по событию `letter.registered`. */
export function markMailRegistered(id: number, number: string): void {
  const v = viewer();
  const current = read().find((m) => m.id === id);
  if (!current || current.status === "done" || current.status === "spam") return;
  finish(id, v, {
    outcome: "registered",
    letter_number: number,
    letter_ref: `/eds/inbox/${encodeURIComponent(number)}`,
  });
}

function clerkRole(view: readonly MockRole[]): MockRole | undefined {
  return view.find((r) => r.access["crm.leads.triage"] === "full");
}

function inView(
  mail: StoredMail,
  view: InboundMailView,
  v: Viewer,
  history: boolean | null,
): boolean {
  if (!visible(mail, v)) return false;
  const working = mail.status === "in_work" || mail.status === "registering";
  switch (view) {
    case "new":
      return mail.status === "new" && (history === null || mail.from_history === history);
    case "mine":
      return working && isMine(mail, v);
    case "in_work":
      return working;
    case "done":
      return mail.status === "done";
    case "spam":
      return mail.status === "spam";
    default:
      return mail.status !== "spam";
  }
}

function listOf(
  view: InboundMailView,
  history: boolean | null,
  q: string,
  type: string | null = null,
): StoredMail[] {
  if (imapOff()) return [];
  const v = viewer();
  const needle = q.trim().toLowerCase();
  return read()
    .filter((m) => inView(m, view, v, history))
    .filter((m) => !type || m.type?.code === type)
    .filter(
      (m) =>
        !needle ||
        [m.from_email, m.from_name, m.subject].some((s) => s.toLowerCase().includes(needle)),
    )
    .sort((a, b) => b.activity_at.localeCompare(a.activity_at));
}

function countsOf(): InboundMailCounts {
  const count = (view: InboundMailView, history: boolean | null = null) =>
    listOf(view, history, "").length;
  return {
    new: count("new"),
    history: count("new", true),
    mine: count("mine"),
    in_work: count("in_work"),
    done: count("done"),
    spam: count("spam"),
    all: count("all"),
    unread_new: listOf("new", null, "").filter((m) => m.unread).length,
  };
}

/** Строки «Моих задач» (как `mail_rows` BFF): Новые не «из истории» — первой линии, мои «в работе» — каждому. */
function taskMails(v: Viewer): StoredMail[] {
  if (imapOff()) return [];
  return read().filter(
    (m) =>
      visible(m, v) &&
      ((v.full && m.status === "new" && !m.from_history) ||
        ((m.status === "in_work" || m.status === "registering") && isMine(m, v))),
  );
}

export function inboundMailQueueItems(view: readonly MockRole[]): QueueItem[] {
  const v = viewer();
  const role = clerkRole(view) ?? view[0];
  if (!role) return [];
  return taskMails(v).map((mail) => {
    const mine = mail.status !== "new";
    const verb = !mine
      ? "Разобрать письмо"
      : mail.personal
        ? "Письмо вам лично"
        : "Письмо в работе";
    return {
      id: `mail:${String(mail.id)}`,
      role_id: role.id,
      kind: mine ? ("inbound_mail_mine" as const) : ("inbound_mail" as const),
      title: `${verb}: ${mail.subject}`,
      subtitle: [mail.from_name || mail.from_email, mail.assist.summary ?? mail.preview].join(
        " · ",
      ),
      due_label: "later" as const,
      object: {
        kind: "letter" as const,
        number: mail.from_email,
        title: mail.subject,
        path: `${v.full ? "/eds/mail" : "/eds/my-mail"}/${String(mail.id)}`,
      },
    };
  });
}

export function inboundMailCards(view: readonly MockRole[]): QueueCard[] {
  if (!clerkRole(view)) return [];
  return [
    {
      key: "inbound_mail",
      label: "Входящая почта",
      count: taskMails(viewer()).length,
      hint: imapOff()
        ? "Почта не подключена — Настройки · Подключения · Почта"
        : "Документы · Входящая почта",
      path: "/eds/mail",
    },
  ];
}

export function inboundMailCounters(view: readonly MockRole[]) {
  if (!clerkRole(view)) return [];
  const count = taskMails(viewer()).length;
  return [{ module: "eds" as const, section: "mail", count, attention: count > 0 }];
}

let imap: ImapConnector = {
  configured: true,
  host: "imap.mail.example",
  port: 993,
  security: "ssl",
  mailbox: "INBOX",
  assist_enabled: true,
  personal_rule: true,
  personal_label: "Адресовано лично",
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
  trusted_auth_servers: [
    "yandex.ru",
    "yandex.net",
    "yandex.com",
    "google.com",
    "protection.outlook.com",
    "mail.ru",
    "zoho.com",
  ],
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

function card(id: number): StoredMail | Response {
  const mail = read().find((m) => m.id === id);
  if (!mail) return notFound();
  return visible(mail, viewer()) ? withType(mail) : forbidden();
}

export const inboundMailHandlers = [
  http.get("*/inbound-mail", ({ request }) => {
    const url = new URL(request.url);
    const view = (url.searchParams.get("view") ?? "new") as InboundMailView;
    const raw = url.searchParams.get("history");
    const items = listOf(
      view,
      raw === null ? null : raw === "true",
      url.searchParams.get("q") ?? "",
      url.searchParams.get("type"),
    );
    return HttpResponse.json({
      items: items.map(itemOf),
      total: items.length,
      counts: countsOf(),
      mailbox: {
        configured: !imapOff(),
        last_poll_at: imapOff() ? null : minutesAgo(1),
        last_ok_at: imapOff() ? null : minutesAgo(1),
        last_error_kind: null,
        personal_label: imap.personal_label,
      },
    });
  }),
  http.post("*/inbound-mail/bulk-archive", async ({ request }) => {
    const v = viewer();
    if (!v.full) return forbidden();
    const body = (await request.json()) as { ids: number[]; reason: string };
    const archived: number[] = [];
    const skipped: { id: number; reason: string; assignee: InboundMailPerson | null }[] = [];
    for (const id of body.ids) {
      const mail = read().find((m) => m.id === id);
      if (!mail) skipped.push({ id, reason: "missing", assignee: null });
      else if (mail.status === "done") skipped.push({ id, reason: "handled", assignee: null });
      else if (mail.status === "registering")
        skipped.push({ id, reason: "registering", assignee: mail.assignee });
      else if (mail.status === "in_work" && !isMine(mail, v))
        skipped.push({ id, reason: "in_work_by_other", assignee: mail.assignee });
      else {
        finish(id, v, { outcome: "archived", reason: body.reason });
        archived.push(id);
      }
    }
    return HttpResponse.json({ archived, skipped });
  }),
  http.get("*/inbound-mail/handover-targets", ({ request }) => {
    if (!viewer().full) return forbidden();
    const purpose =
      new URL(request.url).searchParams.get("purpose") === "price" ? "price" : "payments";
    return HttpResponse.json({ items: HANDOVER_TARGETS[purpose] });
  }),
  http.get("*/inbound-mail/:id/attachments/:index", () =>
    HttpResponse.text(PDF, { headers: { "content-type": "application/octet-stream" } }),
  ),
  http.get("*/inbound-mail/:id", ({ params }) => {
    const found = card(Number(params.id));
    return found instanceof Response ? found : HttpResponse.json(found);
  }),
  http.post("*/inbound-mail/:id/read", ({ params }) => {
    update(Number(params.id), (mail) => ({ ...mail, unread: false }));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/take", async ({ params, request }) => {
    const v = viewer();
    const id = Number(params.id);
    const body = (await request.json()) as { takeover?: boolean };
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    if (!v.full) return forbidden();
    if (body.takeover && current.status === "in_work" && !isMine(current, v)) {
      update(id, (mail) => assigned(mail, v, "takeover"));
      return new HttpResponse(null, { status: 204 });
    }
    const got = claim(id, v);
    return "response" in got ? got.response : new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/release", ({ params }) => {
    const v = viewer();
    const id = Number(params.id);
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    const returnable =
      current.status === "in_work" ||
      (current.status === "done" &&
        (current.result?.outcome === "archived" ||
          current.result?.outcome === "replied" ||
          current.result?.outcome === "price" ||
          current.result?.outcome === "handled"));
    if (!returnable)
      return failure(409, "CONFLICT", "Это письмо нельзя вернуть в «Новые».", {
        reason: "mail_not_returnable",
      });
    if (current.status === "in_work" && !isMine(current, v)) return heldBy(current);
    update(id, (mail) =>
      logged(
        {
          ...mail,
          status: "new",
          assignee: null,
          assigned_at: null,
          result: null,
          thread_reply: false,
        },
        v,
        "release",
      ),
    );
    return new HttpResponse(null, { status: 204 });
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
              kind: null,
              summary: "Покупатель просит КП на стрелочные переводы с поставкой до конца года.",
              action: null,
            },
            // Правило отправителя и выбор человека сильнее помощника.
            type: mail.type ?? resolveType("client_request", "ai"),
          },
    );
    return updated ? HttpResponse.json(updated.assist) : notFound();
  }),
  http.put("*/inbound-mail/:id/type", async ({ params, request }) => {
    const v = viewer();
    const id = Number(params.id);
    const body = (await request.json()) as { type_code: string | null };
    if (!v.full) return forbidden();
    if (!read().some((m) => m.id === id)) return notFound();
    const picked = body.type_code ? resolveType(body.type_code, "manual") : null;
    if (body.type_code && !picked)
      return failure(422, "VALIDATION_FAILED", "Такого типа нет.", { fields: ["type_code"] });
    if (picked && !picked.active)
      return failure(409, "CONFLICT", "Тип отключён.", { reason: "mail_type_inactive" });
    update(id, (mail) => logged({ ...mail, type: picked }, v, "type", picked?.name.ru ?? "—"));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/price", ({ params }) => {
    const v = viewer();
    const id = Number(params.id);
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    // Закрыть может тот, у кого есть право на прайсы, и либо ему передали письмо, либо он первая линия.
    if (!v.stock || (!v.full && !isMine(current, v))) return forbidden();
    const got = claim(id, v);
    if ("response" in got) return got.response;
    update(id, (mail) => logged(mail, v, "price"));
    finish(id, v, { outcome: "price" });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/complete", ({ params }) => {
    const v = viewer();
    const id = Number(params.id);
    const current = read().find((m) => m.id === id);
    if (!current) return notFound();
    if (!isMine(current, v)) return forbidden();
    if (current.status !== "in_work") return conflict();
    update(id, (mail) => logged(mail, v, "complete"));
    finish(id, v, { outcome: "handled" });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/suspicious", ({ params }) => {
    const v = viewer();
    const id = Number(params.id);
    if (!v.full) return forbidden();
    const got = claim(id, v);
    if ("response" in got) return got.response;
    update(id, (mail) =>
      logged({ ...mail, status: "spam", assignee: null, assigned_at: null }, v, "suspicious"),
    );
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/handover", async ({ params, request }) => {
    const v = viewer();
    const id = Number(params.id);
    const body = (await request.json()) as { user_id: number; purpose?: "payments" | "price" };
    if (!v.full) return forbidden();
    const target = HANDOVER_TARGETS[body.purpose ?? "payments"].find((t) => t.id === body.user_id);
    if (!target)
      return failure(409, "CONFLICT", "Некого выбрать.", { reason: "mail_no_handover_target" });
    const got = claim(id, v);
    if ("response" in got) return got.response;
    update(id, (mail) =>
      logged(
        {
          ...mail,
          status: "in_work",
          assignee: target,
          assigned_at: new Date().toISOString(),
        },
        v,
        "handover",
        target.name,
      ),
    );
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/lead", ({ params }) => {
    const v = viewer();
    const id = Number(params.id);
    if (!v.full) return forbidden();
    const got = claim(id, v);
    if ("response" in got) return got.response;
    const leadId = 2050 + id;
    const lead = { id: leadId, number: `L-${String(leadId)}`, name: got.mail.from_name };
    update(id, (mail) => logged(mail, v, "lead"));
    finish(id, v, { outcome: "lead", lead });
    return HttpResponse.json({ lead_id: leadId, lead_number: lead.number, created: true });
  }),
  http.post("*/inbound-mail/:id/archive", async ({ params, request }) => {
    const v = viewer();
    const id = Number(params.id);
    const body = (await request.json()) as { reason: string };
    if (!v.full) return forbidden();
    const got = claim(id, v);
    if ("response" in got) return got.response;
    update(id, (mail) => logged(mail, v, "archive", body.reason));
    finish(id, v, { outcome: "archived", reason: body.reason });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/inbound-mail/:id/not-spam", ({ params }) =>
    spamAction(Number(params.id), (mail) => ({ ...mail, status: "new" })),
  ),
  http.post("*/inbound-mail/:id/discard", ({ params }) =>
    spamAction(Number(params.id), (mail) => ({
      ...mail,
      status: "done",
      result: {
        outcome: "archived",
        by: person(viewer()),
        at: new Date().toISOString(),
        letter_number: null,
        letter_ref: null,
        lead: null,
        reason: "Спам",
      },
    })),
  ),
  http.post("*/inbound-mail/:id/reply", async ({ params, request }) => {
    const v = viewer();
    const id = Number(params.id);
    const body = (await request.json()) as { awaiting?: boolean; to?: string | null };
    const got = claim(id, v);
    if ("response" in got) return got.response;
    const now = new Date().toISOString();
    const reply = {
      id: got.mail.replies.length + 1,
      to_email: body.to ?? got.mail.reply_to,
      subject: `Re: ${got.mail.subject}`,
      status: "queued",
      created_at: now,
      sent_at: null,
      by: person(v),
    };
    update(id, (mail) => logged({ ...mail, replies: [...mail.replies, reply] }, v, "reply"));
    if (!body.awaiting) finish(id, v, { outcome: "replied" });
    return HttpResponse.json(reply);
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
      personal_rule: body.personal_rule ?? true,
      personal_label: body.personal_label ?? "Адресовано лично",
      username: body.username ?? imap.username,
      password_last4: body.imap_password ? body.imap_password.slice(-4) : imap.password_last4,
      configured: Boolean(body.host),
      trusted_auth_servers: body.trusted_auth_servers ?? imap.trusted_auth_servers,
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

// Правило отправителя, созданное из карточки, сразу ставит тип открытым «Новым» письмам (кроме выбранных человеком).
setRuleApplier((pattern, code, exceptId) => {
  const mails = read();
  let applied = 0;
  const next = mails.map((mail) => {
    const sender = mail.from_email.toLowerCase();
    const domain = sender.split("@")[1] ?? "";
    const hit = pattern.includes("@")
      ? sender === pattern
      : domain === pattern || domain.endsWith(`.${pattern}`);
    if (!hit || mail.status !== "new") return mail;
    // Тип по правилу — только письмам с подтверждённым отправителем.
    if (mail.sender_check) return mail;
    if (mail.id === exceptId) return mail;
    if (mail.type?.source === "manual" || mail.type?.source === "rule") return mail;
    applied += 1;
    return { ...mail, type: resolveType(code, "rule") };
  });
  const target = next.find((m) => m.id === exceptId);
  if (target && target.type?.source !== "manual") {
    const at = next.indexOf(target);
    next[at] = { ...target, type: resolveType(code, "rule") };
    applied += 1;
  }
  write(next);
  return applied;
});
setMailTypeUsage(() => new Set(read().flatMap((mail) => (mail.type ? [mail.type.code] : []))));
