import { HttpResponse, http } from "msw";

import type {
  EdsDealOptions,
  EdsDocument,
  EdsDocumentIn,
  EdsDocumentMailing,
  EdsLetterIn,
  EdsLetterhead,
  EdsDocumentPage,
  EdsDocumentRow,
  EdsDocumentUpdateIn,
  EdsRegistryKind,
  EdsRouteStep,
} from "../shared/api/generated/model";
import {
  ACCOUNTANT,
  DIRECTOR,
  EDS_MOCK_NOW,
  type EdsMock,
  MOCK_DEALS,
  type MockDocument,
  type MockLetter,
  documentId,
  personOf,
  readEds,
  writeEds,
} from "./fixtures/edsDocuments";
import {
  closeReplyInstructions,
  noticeMailFailed,
  noticeRegistrationRequested,
  noticeReplyRegistered,
} from "./edsInstructions";
import letterSampleUrl from "./fixtures/letter-sample.pdf?url";
import { readLetters } from "./fixtures/letters";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки EDS · Создать документ и «Мои документы» (D1-5, BFF 0.17.0). Права — как в BFF: список, карточка и вложения читает любой
 * раздел EDS; создаёт и грузит файлы `eds.memo.create`; реестр «Все» — чтение входящих, проектов или платежей; письмо
 * регистрирует роль с полным доступом к входящим; связь с проектом — чтение `crm.clients` или `eds.projects`. Ошибки EDS —
 * те же коды (`VALIDATION_FAILED` с полями, `CONFLICT` `invalid_state`, `PAYLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`).
 * Отказ сервера при отправке показывает правило «`[сбой]` в тексте»: документ создаётся, отправка отклонена, ответ называет
 * сохранённый черновик (`details.document_id`).
 */
type Level = "read" | "full";
type Rule = readonly [resource: string, need: Level];

const EDS_READ: readonly Rule[] = [
  ["eds.memo.create", "read"],
  ["eds.memo.approve", "read"],
  ["eds.inbox", "read"],
  ["eds.drafts", "read"],
  ["eds.projects", "read"],
  ["eds.payments", "read"],
];
const REGISTRY: readonly Rule[] = [
  ["eds.inbox", "read"],
  ["eds.projects", "read"],
  ["eds.payments", "read"],
];
const DOCUMENT_KINDS: readonly EdsRegistryKind[] = ["memo", "application", "report", "letter_out"];
const MAX_UPLOAD = 25 * 1024 * 1024;
const BAD_EXTENSIONS = /\.(exe|bat|cmd|sh|js|msi)$/i;

function fail(
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
): Response {
  return HttpResponse.json(
    { code, message, source: "eds", ...(details ? { details } : {}) },
    { status },
  );
}

const sessionExpired = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );

function forbidden(resource: string, need: Level): Response {
  return HttpResponse.json(
    {
      code: "FORBIDDEN",
      message: "Раздел или действие не положены вашей роли.",
      source: "bff",
      details: { resource, need },
    },
    { status: 403 },
  );
}

const rank = (level: Level | undefined) => (level === "full" ? 2 : level === "read" ? 1 : 0);

function resources(): Record<string, Level> | null {
  const session = readSession();
  if (!session) return null;
  // Права операций — по объединению ролей, а не по активной роли («вид»), как в BFF.
  return buildMe({ ...session, activeRole: null })?.resources ?? null;
}

function allows(held: Record<string, Level>, rules: readonly Rule[]): boolean {
  return rules.some(([resource, need]) => rank(held[resource]) >= rank(need));
}

function ownerId(): string {
  return readSession()?.userId ?? "";
}

function today(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function rowOf(doc: MockDocument): EdsDocumentRow {
  return {
    kind: doc.kind,
    id: doc.id,
    number: doc.number,
    subject: doc.subject,
    status: doc.status,
    author: personOf(doc.ownerId),
    amount: doc.amount,
    due_date: doc.due_date,
    created_at: doc.created_at,
    openable: true,
  };
}

function matches(row: EdsDocumentRow, kinds: string[], statuses: string[]): boolean {
  return (
    (kinds.length === 0 || kinds.includes(row.kind)) &&
    (statuses.length === 0 || statuses.includes(row.status))
  );
}

function newestFirst(a: EdsDocumentRow, b: EdsDocumentRow): number {
  return b.created_at.localeCompare(a.created_at);
}

function page(rows: EdsDocumentRow[], cursor: string | null, limit: number): EdsDocumentPage {
  const start = cursor ? Number(cursor) || 0 : 0;
  const items = rows.slice(start, start + limit);
  const end = start + limit;
  return { items, next_cursor: end < rows.length ? String(end) : null };
}

function stepsOf(doc: MockDocument): EdsRouteStep[] {
  const withAccountant = doc.kind === "memo" && doc.amount !== null;
  const director = (status: EdsRouteStep["status"]): EdsRouteStep => {
    const decided = doc.decisions.find((d) => d.step === 1);
    return {
      label: "Директор",
      status,
      decided_by: status === "current" || status === "pending" ? null : DIRECTOR,
      decided_at: decided && status !== "current" ? decided.at : null,
      comment: decided?.comment ?? null,
    };
  };
  const accountant = (status: EdsRouteStep["status"]): EdsRouteStep => ({
    label: "Бухгалтер",
    status,
    decided_by: status === "approved" ? ACCOUNTANT : null,
    decided_at: status === "approved" ? EDS_MOCK_NOW : null,
    comment: null,
  });
  const tail = (status: EdsRouteStep["status"]) => (withAccountant ? [accountant(status)] : []);
  switch (doc.status) {
    case "on_approval":
      return [director("current"), ...tail("pending")];
    case "to_accountant":
      return [director("approved"), accountant("current")];
    case "approved":
      return [director("approved")];
    case "paid":
      return [director("approved"), accountant("approved")];
    case "rejected":
      return [director("rejected")];
    case "returned":
      return [director("returned")];
    default:
      return [];
  }
}

function detail(doc: MockDocument, state: EdsMock, me: string): EdsDocument {
  const deal = MOCK_DEALS.find((candidate) => candidate.erp_deal_id === doc.erp_deal_id);
  const editable =
    doc.ownerId === me &&
    (doc.status === "draft" || (doc.status === "returned" && doc.kind !== "letter_out"));
  return {
    id: doc.id,
    kind: doc.kind,
    number: doc.number,
    status: doc.status,
    version: doc.version,
    subject: doc.subject,
    text: doc.text,
    author: personOf(doc.ownerId),
    addressee: null,
    amount: doc.amount,
    due_date: doc.due_date,
    files: doc.file_ids.flatMap((id) => {
      const file = state.files[id];
      return file ? [file] : [];
    }),
    deal:
      doc.erp_deal_id === null
        ? null
        : { erp_deal_id: doc.erp_deal_id, number: deal?.number ?? null },
    recipient: doc.recipient,
    route: stepsOf(doc),
    decisions: doc.decisions,
    can_edit: editable,
    created_at: doc.created_at,
    updated_at: doc.updated_at,
    in_reply_to: replyToOf(doc),
    signed_at: doc.signed_at ?? null,
    signed_by: doc.signed_by_user_id ? personOf(doc.signed_by_user_id) : null,
    signing_authority_id: doc.signing_authority_id ?? null,
    signatory_basis: doc.signatory_basis ?? null,
    signatory_basis_text: doc.signatory_basis_text ?? null,
    acting_for: doc.acting_for_user_id ? personOf(doc.acting_for_user_id) : null,
    verification_code: doc.verification_code ?? null,
    verification_url: doc.verification_code
      ? `https://cabinet.railtech.uz/v/${doc.verification_code}`
      : null,
    dispatch_method: doc.dispatch_method ?? null,
    ...letterFields(doc, me),
  };
}

/** «В ответ на ВХ-…» (EDS-REPLY-1): номер, тема и ссылка входящего — карточка во «Входящих» или экран поручения. */
function replyToOf(doc: MockDocument): EdsDocument["in_reply_to"] {
  if (doc.kind !== "letter_out" || !doc.replyTo) return null;
  const letter = readLetters().find((l) => l.number === doc.replyTo);
  const held = resources();
  const inbox = Boolean(held && (held["eds.inbox"] || held["eds.inbox.register"]));
  return {
    number: doc.replyTo,
    subject: letter?.subject ?? "",
    path:
      inbox || !letter
        ? `/eds/inbox/${encodeURIComponent(doc.replyTo)}`
        : `/eds/tasks/${letter.id}`,
  };
}

/** Поля письма на бланке (P4) и права на регистрацию — как считает BFF: раздел `eds.inbox.register` (полный). */
function letterFields(doc: MockDocument, me: string): Partial<EdsDocument> {
  if (doc.kind !== "letter_out") return {};
  const register = canRegister();
  const letter = doc.letter;
  const draft = doc.status === "draft";
  return {
    letter: letter
      ? {
          body: letter.body,
          recipient_attention: letter.recipient_attention,
          recipient_email: letter.recipient_email,
          signatory_name: letter.signatory_name,
          signatory_position: letter.signatory_position,
          pdf: letter.pdf,
          mailings: letter.mailings,
          registration_requested: letter.registration_requested
            ? {
                by: personOf(letter.registration_requested.ownerId),
                at: letter.registration_requested.at,
              }
            : null,
        }
      : null,
    can_register:
      draft && register && (doc.ownerId === me || Boolean(letter?.registration_requested)),
    can_request_registration: draft && !register && doc.ownerId === me,
    can_sign:
      doc.can_sign ?? (draft && (me === "u-demo-director" || Boolean(doc.signing_authority_id))),
  };
}

function canRegister(): boolean {
  const held = resources();
  return Boolean(held && held["eds.inbox.register"] === "full");
}

/** Ответ почтового сервиса в демо: адрес с «nosmtp» — «Почта не настроена», остальное уходит. */
const NO_SMTP = "Почта не настроена — Настройки · Подключения · Почта";

/**
 * Фон EDS в демо: PDF «готов» со второго опроса, отправка адресату ждёт итоговый PDF, затем «передано почтовому сервису»
 * и итог CRM. Каждый опрос карточки или PDF продвигает на шаг.
 */
function advance(doc: MockDocument): boolean {
  const letter = doc.letter;
  if (!letter) return false;
  let changed = false;
  const now = new Date().toISOString();
  if (letter.pdf?.status === "pending") {
    letter.pdfPolls += 1;
    if (letter.pdfPolls >= 2) {
      letter.pdf = { ...letter.pdf, status: "ready", pages: 1, ready_at: now };
    }
    changed = true;
  }
  letter.mailings = letter.mailings.map((mailing): EdsDocumentMailing => {
    if (mailing.status === "awaiting_pdf" && letter.pdf?.status === "ready") {
      changed = true;
      return { ...mailing, status: "requested" };
    }
    if (mailing.status === "requested") {
      changed = true;
      const failed = mailing.to.some((address) => address.includes("nosmtp"));
      return failed
        ? { ...mailing, status: "failed", reason: NO_SMTP, finished_at: now }
        : { ...mailing, status: "sent", finished_at: now };
    }
    return mailing;
  });
  // EDS-REPLY-1: письмо не ушло — автору и делопроизводителям уведомление (один раз, при переходе в «не отправлено»)
  const failedNow = letter.mailings.find((m) => m.status === "failed" && m.finished_at === now);
  if (failedNow) noticeMailFailed(doc, failedNow.reason);
  return changed;
}

function requestPdf(letter: MockLetter, final: boolean): void {
  letter.pdf = {
    status: "pending",
    final,
    error: null,
    pages: null,
    requested_at: new Date().toISOString(),
    ready_at: null,
  };
  letter.pdfPolls = 0;
}

function queueMailing(letter: MockLetter): void {
  if (!letter.recipient_email) return;
  letter.mailings.push({
    id: crypto.randomUUID(),
    to: [letter.recipient_email],
    status: "awaiting_pdf",
    reason: null,
    requested_by: personOf(ownerId()),
    requested_at: new Date().toISOString(),
    finished_at: null,
  });
}

export const MOCK_LETTERHEAD: EdsLetterhead = {
  configured: true,
  company_name: "ООО «RailTech»",
  requisites: [
    "г. Ташкент, Мирабадский р-н, ул. Афросиаб, 12",
    "ИНН 305123456 · р/с 20208000900123456001, АКБ «Капиталбанк», МФО 01088",
  ],
  signatory_name: "Каримов А. А.",
  signatory_position: "Директор",
  has_logo: false,
  updated_at: "2026-11-01T06:00:00Z",
};

interface FormBody {
  subject?: string;
  text?: string;
  amount?: { amount: string; currency: string } | null;
  due_date?: string | null;
  file_ids?: string[];
  erp_deal_id?: number | null;
  recipient?: { name: string; inn?: string | null } | null;
  letter?: EdsLetterIn | null;
  send?: boolean;
}

/** Проверка формы, как её делают BFF и EDS: тема и текст, сумма больше нуля, «нужно до» не в прошлом, адресат письма. */
function validationError(body: FormBody, letter: boolean): Response | null {
  const fields: string[] = [];
  if (!body.subject?.trim()) fields.push("subject");
  if (!body.text?.trim()) fields.push("text");
  if (body.amount && Number(body.amount.amount) <= 0) fields.push("amount");
  if (body.due_date && body.due_date < today()) fields.push("due_date");
  if (letter && !body.recipient?.name.trim()) fields.push("recipient");
  if (body.erp_deal_id && !MOCK_DEALS.some((d) => d.erp_deal_id === body.erp_deal_id)) {
    fields.push("erp_deal_id");
  }
  return fields.length > 0
    ? fail(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", { fields })
    : null;
}

function applyForm(doc: MockDocument, body: FormBody): void {
  if (body.subject !== undefined) doc.subject = body.subject.trim();
  if (body.text !== undefined) doc.text = body.text.trim();
  if ("amount" in body) doc.amount = body.amount ?? null;
  if ("due_date" in body) doc.due_date = body.due_date ?? null;
  if ("erp_deal_id" in body) doc.erp_deal_id = body.erp_deal_id ?? null;
  if (body.recipient !== undefined && doc.kind === "letter_out") {
    doc.recipient = body.recipient
      ? { name: body.recipient.name, inn: body.recipient.inn ?? null }
      : null;
  }
  if (body.file_ids) {
    doc.file_ids = [...new Set([...doc.file_ids, ...body.file_ids])];
  }
  if (body.letter && doc.kind === "letter_out") {
    const prev = doc.letter;
    doc.letter = {
      body: body.letter.body,
      recipient_attention: body.letter.recipient_attention ?? null,
      recipient_email: body.letter.recipient_email ?? null,
      signatory_name: body.letter.signatory_name ?? null,
      signatory_position: body.letter.signatory_position ?? null,
      pdf: prev?.pdf ?? null,
      pdfPolls: prev?.pdfPolls ?? 0,
      mailings: prev?.mailings ?? [],
      registration_requested: prev?.registration_requested ?? null,
    };
  }
  doc.updated_at = new Date().toISOString();
}

function numberFor(state: EdsMock, kind: MockDocument["kind"]): string {
  const year = "2026";
  const pad = (n: number, width: number) => String(n).padStart(width, "0");
  switch (kind) {
    case "memo":
      return `СЗ-${year}/${pad(state.next.memo++, 3)}`;
    case "application":
      return `ЗЯ-${year}/${pad(state.next.application++, 3)}`;
    case "report":
      return `ОТ-${year}/${pad(state.next.report++, 3)}`;
    case "letter_out":
      return `ИСХ-${pad(state.next.outgoing++, 3)}/26`;
  }
}

/**
 * Отправка: служебка, заявление и отчёт открывают маршрут, письмо регистрируется сразу; у письма на бланке — итоговый PDF с
 * номером и, при `send`, строка журнала отправки адресату.
 */
function submitDocument(doc: MockDocument, state: EdsMock, send = false): void {
  if (doc.kind === "letter_out") {
    doc.number = numberFor(state, "letter_out");
    doc.status = "sent";
    if (doc.letter?.body) {
      requestPdf(doc.letter, true);
      if (send) queueMailing(doc.letter);
    }
    if (doc.replyTo) {
      const closed = closeReplyInstructions(doc.replyTo, doc.number);
      noticeReplyRegistered(doc, closed);
    }
  } else {
    if (doc.status === "returned") doc.version += 1;
    doc.status = "on_approval";
  }
  doc.updated_at = new Date().toISOString();
}

const SERVER_DOWN = "[сбой]";

function backendDown(doc: MockDocument, created: boolean): Response {
  return fail(503, "BACKEND_UNAVAILABLE", "Сервис временно недоступен.", {
    backend_status: 503,
    document_id: doc.id,
    saved: true,
    created,
  });
}

/**
 * Файл из multipart без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`, а мок работает и там,
 * и в браузере. Размер — по числу байт содержимого части.
 */
export async function parseUploadedFile(
  request: Request,
): Promise<{ name: string; size: number; type: string } | null> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  if (!boundary) return null;
  const text = new TextDecoder().decode(await request.arrayBuffer());
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const name = /filename="([^"]*)"/.exec(head)?.[1];
    if (name === undefined || !/name="file"/.test(head)) continue;
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    return {
      name,
      size: new TextEncoder().encode(body).length,
      type: /Content-Type:\s*([^\r\n]+)/i.exec(head)?.[1] ?? "",
    };
  }
  return null;
}

/** Конечные статусы по виду — как в EDS (eds.yaml 0.15.0, `stage`). */
const DONE_STATUSES: Record<string, readonly string[]> = {
  letter_in: ["executed", "noted", "duplicate", "closed", "rejected"],
  letter_out: ["approved", "rejected", "paid", "sent"],
  memo: ["approved", "rejected", "paid", "sent"],
  application: ["approved", "rejected", "paid", "sent"],
  report: ["approved", "rejected", "paid", "sent"],
  quote: ["rejected"],
  contract: ["signed", "rejected"],
  invoice: ["paid"],
  act: ["signed"],
};

function inStage(row: EdsDocumentRow, stage: string | null): boolean {
  if (stage !== "open" && stage !== "done") return true;
  const done = (DONE_STATUSES[row.kind] ?? []).includes(row.status);
  return stage === "done" ? done : !done;
}

export const edsDocumentsHandlers = [
  http.get("*/eds/documents", ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (!allows(held, EDS_READ)) return forbidden("eds.memo.create", "read");
    const url = new URL(request.url);
    const scope = url.searchParams.get("scope") ?? "mine";
    const kinds = url.searchParams.getAll("kind");
    const statuses = url.searchParams.getAll("status");
    const stage = url.searchParams.get("stage");
    const cursor = url.searchParams.get("cursor");
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const state = readEds();
    if (scope === "all") {
      if (!allows(held, REGISTRY)) return forbidden("eds.inbox", "read");
      // Реестр EDS сроков не отдаёт; сумма строки — с 0.15.0 (КП, договор, счёт, акт, документ с суммой).
      const rows: EdsDocumentRow[] = [
        ...state.documents.map((doc) => ({ ...rowOf(doc), due_date: null })),
        ...state.registry.map((entry): EdsDocumentRow => ({
          kind: entry.kind,
          id: entry.id,
          number: entry.number,
          subject: entry.title,
          status: entry.status,
          author: entry.responsible,
          amount: entry.amount ?? null,
          due_date: null,
          created_at: entry.registered_at,
          openable: false,
          ...(entry.project_ref ? { project_ref: entry.project_ref } : {}),
        })),
      ];
      return HttpResponse.json(
        page(
          rows
            .filter((row) => matches(row, kinds, statuses) && inStage(row, stage))
            .sort(newestFirst),
          cursor,
          limit,
        ),
      );
    }
    const onlyDocuments = kinds.filter((kind) => DOCUMENT_KINDS.includes(kind as EdsRegistryKind));
    if (kinds.length > 0 && onlyDocuments.length === 0) {
      return HttpResponse.json({ items: [], next_cursor: null });
    }
    const me = ownerId();
    const rows = state.documents
      .filter((doc) => doc.ownerId === me)
      .map(rowOf)
      .filter((row) => matches(row, onlyDocuments, statuses) && inStage(row, stage))
      .sort(newestFirst);
    return HttpResponse.json(page(rows, cursor, limit));
  }),

  http.post("*/eds/documents", async ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (rank(held["eds.memo.create"]) < 2) return forbidden("eds.memo.create", "full");
    const body = (await request.json()) as EdsDocumentIn;
    // P4 (B-P8B-4): черновик письма готовит любой, регистрирует — раздел `eds.inbox.register`.
    if (body.kind === "letter_out" && body.submit && !canRegister()) {
      return fail(403, "FORBIDDEN", "Действие не положено вашей роли.", {
        permission: "letters.register",
      });
    }
    const invalid = validationError(body, body.kind === "letter_out");
    if (invalid) return invalid;
    const state = readEds();
    const key = request.headers.get("Idempotency-Key");
    const replay = key ? state.documents.find((d) => d.id === state.idempotency?.[key]) : undefined;
    if (replay) return HttpResponse.json(detail(replay, state, ownerId()), { status: 201 });
    const now = new Date().toISOString();
    state.next.doc += 1;
    const doc: MockDocument = {
      id: documentId(state.next.doc),
      kind: body.kind,
      number: body.kind === "letter_out" ? null : numberFor(state, body.kind),
      status: "draft",
      version: 1,
      subject: "",
      text: "",
      ownerId: ownerId(),
      amount: null,
      due_date: null,
      file_ids: [],
      erp_deal_id: null,
      recipient: null,
      decisions: [],
      created_at: now,
      updated_at: now,
    };
    applyForm(doc, body);
    if (body.kind === "letter_out" && body.in_reply_to_number) {
      doc.replyTo = body.in_reply_to_number.trim();
    }
    state.documents.push(doc);
    if (key) state.idempotency = { ...state.idempotency, [key]: doc.id };
    if (body.submit) {
      if (doc.text.includes(SERVER_DOWN)) {
        writeEds(state);
        return backendDown(doc, true);
      }
      submitDocument(doc, state, body.send === true);
    }
    writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()), { status: 201 });
  }),

  http.get("*/eds/documents/:id", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (!allows(held, EDS_READ)) return forbidden("eds.memo.create", "read");
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    // Чужой документ виден, если роли открыт реестр; иначе — как в EDS: «не найден».
    if (!doc || (doc.ownerId !== ownerId() && !allows(held, REGISTRY))) {
      return fail(404, "NOT_FOUND", "Документ не найден.");
    }
    if (advance(doc)) writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()));
  }),

  http.put("*/eds/documents/:id", async ({ request, params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (rank(held["eds.memo.create"]) < 2) return forbidden("eds.memo.create", "full");
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc || (doc.ownerId !== ownerId() && !allows(held, REGISTRY))) {
      return fail(404, "NOT_FOUND", "Документ не найден.");
    }
    // Чужой черновик EDS не показывает никому (#298) — «не найден» (кроме письма, переданного делопроизводителю на
    // регистрацию, P4); чужой возвращённый — «только автор».
    const handedOver = Boolean(doc.letter?.registration_requested) && canRegister();
    if (doc.ownerId !== ownerId() && doc.status === "draft" && !handedOver) {
      return fail(404, "NOT_FOUND", "Документ не найден.");
    }
    if (doc.ownerId !== ownerId() && doc.status === "returned") {
      return fail(403, "FORBIDDEN", "Править документ может только его автор.", {
        reason: "not_author",
      });
    }
    if (doc.status !== "draft" && doc.status !== "returned") {
      return fail(409, "CONFLICT", "Документ нельзя править в текущем статусе.", {
        reason: "invalid_state",
        status: doc.status,
      });
    }
    const body = (await request.json()) as EdsDocumentUpdateIn;
    const invalid = validationError(body, doc.kind === "letter_out");
    if (invalid) return invalid;
    applyForm(doc, body);
    if (body.submit) {
      if (doc.text.includes(SERVER_DOWN)) {
        writeEds(state);
        return backendDown(doc, false);
      }
      if (doc.kind === "letter_out" && !canRegister()) {
        writeEds(state);
        return fail(403, "FORBIDDEN", "Действие не положено вашей роли.", {
          permission: "letters.register",
          document_id: doc.id,
          saved: true,
          created: false,
        });
      }
      submitDocument(doc, state, body.send === true);
    }
    writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()));
  }),

  http.get("*/eds/letterhead", () => {
    const held = resources();
    if (!held) return sessionExpired();
    return HttpResponse.json(MOCK_LETTERHEAD);
  }),

  http.post("*/eds/documents/:id/pdf", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc || doc.kind !== "letter_out") return fail(404, "NOT_FOUND", "Документ не найден.");
    if (!doc.letter?.body) {
      return fail(409, "CONFLICT", "У письма нет текста на бланке.", { reason: "no_body" });
    }
    // Тот же ввод — тот же PDF (кэш по хешу в EDS): готовый или строящийся не перезапрашивается.
    if (
      !doc.letter.pdf ||
      doc.letter.pdf.status === "failed" ||
      doc.letter.pdf.final !== (doc.status === "sent")
    ) {
      requestPdf(doc.letter, doc.status === "sent");
    } else if (doc.letter.pdf.status === "ready" && doc.updated_at > doc.letter.pdf.requested_at) {
      requestPdf(doc.letter, doc.status === "sent");
    }
    writeEds(state);
    return HttpResponse.json(doc.letter.pdf, { status: 202 });
  }),

  http.get("*/eds/documents/:id/pdf", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc?.letter?.pdf) {
      return fail(404, "NOT_FOUND", "PDF не запрашивался.", { reason: "pdf_not_requested" });
    }
    if (advance(doc)) writeEds(state);
    return HttpResponse.json(doc.letter.pdf);
  }),

  http.get("*/eds/documents/:id/pdf/file", async ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    const doc = readEds().documents.find((candidate) => candidate.id === params["id"]);
    if (!doc?.letter?.pdf) return fail(404, "NOT_FOUND", "PDF не запрашивался.");
    if (doc.letter.pdf.status !== "ready") {
      return fail(409, "CONFLICT", "PDF ещё готовится.", { reason: "pdf_not_ready" });
    }
    // Демо-PDF — настоящий рендер `rt-docs` образца ответа на требование ГНК (бланк, адресат, список, таблица, подпись).
    let pdf: ArrayBuffer;
    try {
      pdf = await (await fetch(letterSampleUrl)).arrayBuffer();
    } catch {
      // vitest (Node): адреса ассета Vite нет — достаточно заголовка PDF
      pdf = new TextEncoder().encode("%PDF-1.7\n%%EOF\n").buffer;
    }
    return new HttpResponse(pdf, {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": `inline; filename*=UTF-8''${encodeURIComponent("letter.pdf")}`,
      },
    });
  }),

  http.post("*/eds/documents/:id/registration-request", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc || doc.ownerId !== ownerId()) return fail(404, "NOT_FOUND", "Документ не найден.");
    if (doc.status !== "draft") {
      return fail(409, "CONFLICT", "Письмо уже зарегистрировано.", { reason: "invalid_state" });
    }
    if (!doc.letter?.body) {
      return fail(409, "CONFLICT", "У письма нет текста на бланке.", { reason: "no_body" });
    }
    if (!doc.letter.registration_requested) {
      doc.letter.registration_requested = { ownerId: ownerId(), at: new Date().toISOString() };
      noticeRegistrationRequested(doc);
    }
    writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()));
  }),

  http.post("*/eds/documents/:id/send", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (!canRegister()) return forbidden("eds.inbox.register", "full");
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc?.letter) return fail(404, "NOT_FOUND", "Документ не найден.");
    if (doc.status !== "sent") {
      return fail(409, "CONFLICT", "Письмо ещё не зарегистрировано.", { reason: "invalid_state" });
    }
    if (!doc.letter.recipient_email) {
      return fail(422, "VALIDATION_FAILED", "Укажите почту адресата.", {
        fields: ["recipient_email"],
      });
    }
    queueMailing(doc.letter);
    writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()));
  }),

  http.post("*/eds/documents/:id/sign", async ({ params, request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    const state = readEds();
    const doc = state.documents.find((candidate) => candidate.id === params["id"]);
    if (!doc || doc.kind !== "letter_out") return fail(404, "NOT_FOUND", "Документ не найден.");
    if (doc.status !== "draft") {
      return fail(409, "CONFLICT", "Письмо уже зарегистрировано или подписано.", {
        reason: "invalid_state",
      });
    }
    const body = (await request.json().catch(() => ({}))) as {
      dispatch_method?: "email" | "paper" | "courier" | "edo" | "other";
      send?: boolean;
    };
    const dispatchMethod = body.dispatch_method ?? "paper";
    const send = Boolean(body.send);
    const me = ownerId();

    doc.number = numberFor(state, "letter_out");
    doc.status = "sent";
    doc.signed_at = new Date().toISOString();
    doc.signed_by_user_id = me;
    doc.signatory_basis = "charter";
    doc.signatory_basis_text = "на основании Устава";
    doc.verification_code = `RT-26-${Math.random().toString(36).substring(2, 6).toUpperCase()}`;
    doc.dispatch_method = dispatchMethod;
    doc.updated_at = new Date().toISOString();

    if (doc.letter?.body) {
      requestPdf(doc.letter, true);
      if (send && doc.letter.recipient_email) {
        queueMailing(doc.letter);
      }
    }
    if (doc.replyTo) {
      const closed = closeReplyInstructions(doc.replyTo, doc.number);
      noticeReplyRegistered(doc, closed);
    }
    writeEds(state);
    return HttpResponse.json(detail(doc, state, me));
  }),

  http.post("*/eds/document-files", async ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (rank(held["eds.memo.create"]) < 2) return forbidden("eds.memo.create", "full");
    const file = await parseUploadedFile(request);
    if (file === null) {
      return fail(422, "VALIDATION_FAILED", "Файл нужно передать формой multipart.", {
        fields: ["file"],
      });
    }
    if (file.size > MAX_UPLOAD) {
      return fail(413, "PAYLOAD_TOO_LARGE", "Файл больше 25 МБ.", { max_bytes: MAX_UPLOAD });
    }
    if (BAD_EXTENSIONS.test(file.name)) {
      return fail(415, "UNSUPPORTED_MEDIA_TYPE", "Допустимы PDF, изображения и документы Office.");
    }
    const state = readEds();
    state.next.doc += 1;
    const id = documentId(state.next.doc);
    const stored = {
      id,
      name: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
    };
    state.files[id] = stored;
    writeEds(state);
    return HttpResponse.json(stored, { status: 201 });
  }),

  http.get("*/eds/document-files/:id", ({ params }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (!allows(held, EDS_READ)) return forbidden("eds.memo.create", "read");
    const file = readEds().files[String(params["id"])];
    if (!file) return fail(404, "NOT_FOUND", "Файл не найден.");
    return new HttpResponse(`Демонстрационное содержимое файла «${file.name}».`, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`,
      },
    });
  }),

  http.get("*/eds/deal-options", ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (
      !allows(held, [
        ["crm.clients", "read"],
        ["eds.projects", "read"],
      ])
    ) {
      return forbidden("crm.clients", "read");
    }
    const typed = (new URL(request.url).searchParams.get("q") ?? "").trim().toLowerCase();
    // Латинская запись префикса номера (раскладка клавиатуры): zv -> ЗВ, pr -> ПР.
    const needle = typed.replace(/^zv/, "зв").replace(/^pr/, "пр");
    const items = MOCK_DEALS.filter(
      (deal) =>
        needle === "" ||
        [deal.number, deal.title, deal.company].some((part) => part.toLowerCase().includes(needle)),
    ).map((deal) => ({ ...deal }));
    const body: EdsDealOptions = { items, sources: { crm: "ok", erp: "ok" } };
    return HttpResponse.json(body);
  }),
];
