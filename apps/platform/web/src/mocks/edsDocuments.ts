import { HttpResponse, http } from "msw";

import type {
  EdsDealOptions,
  EdsDocument,
  EdsDocumentIn,
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
  documentId,
  personOf,
  readEds,
  writeEds,
} from "./fixtures/edsDocuments";
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
  };
}

interface FormBody {
  subject?: string;
  text?: string;
  amount?: { amount: string; currency: string } | null;
  due_date?: string | null;
  file_ids?: string[];
  erp_deal_id?: number | null;
  recipient?: { name: string; inn?: string | null } | null;
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

/** Отправка: служебка, заявление и отчёт открывают маршрут, письмо регистрируется сразу. */
function submitDocument(doc: MockDocument, state: EdsMock): void {
  if (doc.kind === "letter_out") {
    doc.number = numberFor(state, "letter_out");
    doc.status = "sent";
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

export const edsDocumentsHandlers = [
  http.get("*/eds/documents", ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (!allows(held, EDS_READ)) return forbidden("eds.memo.create", "read");
    const url = new URL(request.url);
    const scope = url.searchParams.get("scope") ?? "mine";
    const kinds = url.searchParams.getAll("kind");
    const statuses = url.searchParams.getAll("status");
    const cursor = url.searchParams.get("cursor");
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const state = readEds();
    if (scope === "all") {
      if (!allows(held, REGISTRY)) return forbidden("eds.inbox", "read");
      // Реестр EDS сумм и сроков не отдаёт (`RegistryItem`): только номер, тема, статус и ответственный.
      const rows: EdsDocumentRow[] = [
        ...state.documents.map((doc) => ({ ...rowOf(doc), amount: null, due_date: null })),
        ...state.registry.map((entry): EdsDocumentRow => ({
          kind: entry.kind,
          id: entry.id,
          number: entry.number,
          subject: entry.title,
          status: entry.status,
          author: entry.responsible,
          amount: null,
          due_date: null,
          created_at: entry.registered_at,
          openable: false,
          ...(entry.project_ref ? { project_ref: entry.project_ref } : {}),
        })),
      ];
      return HttpResponse.json(
        page(rows.filter((row) => matches(row, kinds, statuses)).sort(newestFirst), cursor, limit),
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
      .filter((row) => matches(row, onlyDocuments, statuses))
      .sort(newestFirst);
    return HttpResponse.json(page(rows, cursor, limit));
  }),

  http.post("*/eds/documents", async ({ request }) => {
    const held = resources();
    if (!held) return sessionExpired();
    if (rank(held["eds.memo.create"]) < 2) return forbidden("eds.memo.create", "full");
    const body = (await request.json()) as EdsDocumentIn;
    if (body.kind === "letter_out" && rank(held["eds.inbox"]) < 2) {
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
    state.documents.push(doc);
    if (key) state.idempotency = { ...state.idempotency, [key]: doc.id };
    if (body.submit) {
      if (doc.text.includes(SERVER_DOWN)) {
        writeEds(state);
        return backendDown(doc, true);
      }
      submitDocument(doc, state);
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
    // Чужой черновик EDS не показывает никому (#298) — «не найден»; чужой возвращённый — «только автор».
    if (doc.ownerId !== ownerId() && doc.status === "draft") {
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
      submitDocument(doc, state);
    }
    writeEds(state);
    return HttpResponse.json(detail(doc, state, ownerId()));
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
