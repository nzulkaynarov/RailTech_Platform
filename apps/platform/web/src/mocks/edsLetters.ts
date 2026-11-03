import { HttpResponse, http } from "msw";

import { activeLetterKinds, isActiveValue } from "./dictionaries";
import { markMailRegistered } from "./inboundMail";
import { findDuplicates } from "./edsLetterDuplicates";
import type {
  LetterCard,
  LetterDuplicateCheckIn,
  LetterDuplicateList,
  LetterMarkDuplicateIn,
  LetterPage,
  LetterRegisterIn,
  LetterRejectIn,
  LetterReturnIn,
  LetterRow,
  LetterStatus,
  ResolutionIn,
  QueueItem,
} from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import type { MockRole } from "./fixtures/roles";
import { COMPANY_TIME_ZONE } from "../shared/lib/format";
import {
  CANDIDATES,
  DIRECTOR,
  REGISTRAR,
  findLetter,
  readLetters,
  writeLetters,
} from "./fixtures/letters";
import { buildMe, readSession, sessionRoles } from "./mockSession";
import {
  canReadLetter,
  draftFrom,
  personOf,
  rowExtras,
  trackOf,
  withOffice,
} from "./edsInstructions";

/**
 * Моки EDS · Входящие письма и резолюция (D1-3, BFF 0.16.0). Права — как в BFF: список, карточка и вложения — `eds.inbox` не ниже
 * чтения; резолюция, возврат, отказ и кандидаты — `eds.inbox: full`. Ошибки EDS — те же коды и подкоды (`due_in_past`,
 * `invalid_state`), чтобы экран и e2e видели настоящее поведение. «Маржа не ниже» без группы `cost_margin` не отдаётся.
 */
type Level = "read" | "full";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "eds" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

function access(): {
  level: Level | undefined;
  register: boolean;
  margin: boolean;
} | null {
  const session = readSession();
  if (!session) return null;
  // Права операций — по объединению ролей, а не по активной роли («вид»), как в BFF.
  const me = buildMe({ ...session, activeRole: null });
  if (!me) return null;
  return {
    level: me.resources["eds.inbox"],
    register: me.resources["eds.inbox.register"] === "full",
    margin: (me.restricted_fields ?? []).includes("cost_margin"),
  };
}

/** P8: регистрация — раздел `eds.inbox.register`; читать письма может и тот, у кого только регистрация. */
function guardRegister() {
  const held = access();
  if (!held) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  if (!held.register) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.inbox.register",
        need: "full",
      }),
    };
  }
  return { margin: held.margin };
}

function guard(need: Level) {
  const held = access();
  if (!held) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  const ok = held.level === "full" || (need === "read" && (held.level === "read" || held.register));
  if (!ok) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.inbox",
        need,
      }),
    };
  }
  return { margin: held.margin };
}

const companyToday = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());

function present(raw: LetterCard, margin: boolean): LetterCard {
  const letter = withOffice(raw);
  if (margin || !letter.resolution) return letter;
  const resolution = { ...letter.resolution };
  delete resolution.min_margin_pct;
  return { ...letter, resolution };
}

function row(letter: LetterCard): LetterRow {
  return {
    id: letter.id,
    number: letter.number,
    subject: letter.subject,
    client_name: letter.sender.name,
    request_number: letter.request?.number ?? null,
    received_at: letter.received_at,
    status: letter.status,
    urgent: letter.urgent,
    due: letter.resolution?.due ?? null,
    kind: letter.kind ?? null,
    ...rowExtras(letter),
  };
}

const squash = (value: string | null | undefined) =>
  (value ?? "").trim().replace(/\s+/g, " ").toLowerCase();

function nextNumber(): string {
  const max = Math.max(
    0,
    ...readLetters().map((l) => Number(/^ВХ-(\d+)\//.exec(l.number)?.[1] ?? 0)),
  );
  return `ВХ-${String(max + 1).padStart(3, "0")}/26`;
}

/**
 * Строки «Наложить резолюцию» по письмам, зарегистрированным делопроизводителем (P8): у кого вид работы `resolve_letter`.
 * Демо-строка ВХ-104/26 директора — в `fixtures/feeds.ts`.
 */
export function registeredQueueItems(view: readonly MockRole[]): QueueItem[] {
  const role = view.find((r) =>
    allows(r.access, QUEUE.resolve_letter.resource, QUEUE.resolve_letter.level),
  );
  if (!role) return [];
  return readLetters()
    .filter((l) => l.kind && l.status === "awaiting_resolution")
    .map((l) => ({
      id: `letter:${l.id}`,
      role_id: role.id,
      kind: "resolve_letter",
      title: `Наложить резолюцию на письмо ${l.number}`,
      subtitle: [l.sender.name, l.subject].filter(Boolean).join(" · "),
      due_label: l.urgent ? "today" : "later",
      object: {
        kind: "letter",
        number: l.number,
        title: `Письмо ${l.number}`,
        path: `/eds/inbox/${encodeURIComponent(l.number)}?panel=open&tab=resolution`,
      },
    }));
}

function refOf(request: Request): string {
  const path = new URL(request.url).pathname;
  const tail = path.slice(path.indexOf("/eds/letters/") + "/eds/letters/".length);
  try {
    return decodeURIComponent(tail);
  } catch {
    return tail;
  }
}

function invalid(field: string, reason: string, message: string) {
  return failure(422, "VALIDATION_FAILED", message, "eds", {
    backend_status: 422,
    fields: [field],
    reason,
  });
}

function notAwaiting(letter: LetterCard) {
  if (letter.status === "awaiting_resolution") return null;
  return failure(409, "CONFLICT", "Операция недоступна в текущем статусе письма.", "eds", {
    backend_status: 409,
    reason: "invalid_state",
  });
}

function update(id: string, change: (letter: LetterCard) => LetterCard): LetterCard | undefined {
  const all = readLetters();
  const index = all.findIndex((l) => l.id === id);
  const current = all[index];
  if (index < 0 || !current) return undefined;
  const next = change(current);
  writeLetters(all.map((l, i) => (i === index ? next : l)));
  return next;
}

const journalEntry = (action: string, comment: string | null): LetterCard["journal"][number] => ({
  at: new Date().toISOString(),
  action,
  by: DIRECTOR,
  comment,
});

export const edsLettersHandlers = [
  http.get("*/eds/letters", ({ request }) => {
    const held = guard("read");
    if (held.error) return held.error;
    const url = new URL(request.url);
    const statuses = url.searchParams.getAll("status") as LetterStatus[];
    const onControl = url.searchParams.get("on_control") === "true";
    const overdue = url.searchParams.get("overdue") === "true";
    const kindFilter = url.searchParams.get("kind");
    const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const start = Number(url.searchParams.get("cursor") ?? 0);
    const found = readLetters()
      .filter((l) => statuses.length === 0 || statuses.includes(l.status))
      .filter((l) => !onControl || rowExtras(l).on_control)
      .filter((l) => !overdue || rowExtras(l).overdue)
      .filter((l) => !kindFilter || l.kind === kindFilter)
      .filter(
        (l) =>
          q === "" ||
          `${l.number} ${l.subject} ${l.sender.name ?? ""} ${l.request?.number ?? ""}`
            .toLowerCase()
            .includes(q),
      );
    const items = found.slice(start, start + limit).map(row);
    const more = start + limit < found.length;
    const page: LetterPage = { items, next_cursor: more ? String(start + limit) : null };
    return HttpResponse.json(page);
  }),

  http.get("*/eds/letter-kinds", () => {
    const held = guard("read");
    if (held.error) return held.error;
    return HttpResponse.json(activeLetterKinds());
  }),

  http.get("*/eds/letter-duplicates", ({ request }) => {
    const held = guard("read");
    if (held.error) return held.error;
    const url = new URL(request.url);
    const ref = (url.searchParams.get("ref_number") ?? "").trim();
    const sender = squash(url.searchParams.get("sender_name"));
    const found: LetterDuplicateList = {
      items: readLetters()
        .filter((l) => ref && sender && (l.sender_ref.number ?? "").trim() === ref)
        .filter((l) => squash(l.sender.name) === sender)
        .slice(0, 5)
        .map((l) => ({
          id: l.id,
          number: l.number,
          subject: l.subject,
          received_at: l.received_at,
          status: l.status,
          path: `/eds/inbox/${encodeURIComponent(l.number)}`,
        })),
    };
    return HttpResponse.json(found);
  }),

  // EDS-DUP: фоновая проверка формы — то же письмо и похожие.
  http.post("*/eds/letters/duplicates-check", async ({ request }) => {
    const held = guard("read");
    if (held.error) return held.error;
    const probe = (await request.json()) as LetterDuplicateCheckIn;
    const found: LetterDuplicateList = { items: findDuplicates(readLetters(), probe) };
    return HttpResponse.json(found);
  }),

  // EDS-DUP: «Это дубль ВХ-…» — закрыть письмо со ссылкой на оригинал.
  http.post("*/eds/letters/:id/duplicate", async ({ request, params }) => {
    const held = guardRegister();
    if (held.error) return held.error;
    const letter = findLetter(String(params["id"]));
    if (!letter) return failure(404, "NOT_FOUND", "Письмо не найдено.", "eds");
    const body = (await request.json()) as LetterMarkDuplicateIn;
    if (letter.status === "duplicate") {
      return failure(409, "CONFLICT", "Письмо уже отмечено как дубль.", "eds", {
        backend_status: 409,
        reason: "invalid_state",
      });
    }
    const original = findLetter(body.original_number.trim());
    if (!original) return invalid("original_number", "not_found", "Входящего с таким номером нет.");
    if (original.id === letter.id) {
      return invalid("original_number", "same_letter", "Это то же письмо.");
    }
    const work = (letter.instructions ?? []).filter((i) => i.status === "in_work").length;
    const resolved = !["awaiting_resolution", "returned"].includes(letter.status);
    if (resolved && !body.confirm) {
      return failure(409, "CONFLICT", "Подтвердите отмену поручений.", "eds", {
        backend_status: 409,
        reason: "resolution_exists",
        status: letter.status,
        instructions: work,
      });
    }
    const comment = body.comment?.trim();
    const next = update(letter.id, (current) => ({
      ...current,
      status: "duplicate",
      on_control: false,
      duplicate_of: {
        number: original.number,
        path: `/eds/inbox/${encodeURIComponent(original.number)}`,
      },
      instructions: (current.instructions ?? []).map((i) =>
        i.status === "in_work" ? { ...i, status: "cancelled" as const } : i,
      ),
      acquaintances: (current.acquaintances ?? []).filter((a) => a.acknowledged_at),
      journal: [
        ...current.journal,
        journalEntry(
          "letter.marked_duplicate",
          `Дубль ${original.number}${comment ? `: ${comment}` : ""}`,
        ),
      ],
    }));
    return HttpResponse.json(next ? present(next, held.margin) : letter);
  }),

  http.post("*/eds/letters", async ({ request }) => {
    const held = guardRegister();
    if (held.error) return held.error;
    const body = (await request.json()) as LetterRegisterIn;
    // EDS-DUP: то же письмо — 409 с найденным ВХ; «Это другое письмо» — `force` с причиной.
    const [exact] = findDuplicates(readLetters(), body).filter((d) => d.match === "exact");
    if (body.force && !body.force_reason?.trim()) {
      return invalid("force_reason", "required", "Укажите, почему это другое письмо.");
    }
    if (exact && !body.force) {
      return failure(409, "CONFLICT", `Это письмо уже зарегистрировано: ${exact.number}.`, "eds", {
        backend_status: 409,
        reason: "duplicate_letter",
        duplicate: exact,
      });
    }
    const kind = activeLetterKinds().items.find((k) => k.code === body.kind);
    if (!kind) return invalid("kind", "unknown_kind", "Такого вида документа нет в справочнике.");
    if (!isActiveValue("receipt-methods", body.receipt_method)) {
      return invalid(
        "receipt_method",
        "unknown_method",
        "Такого способа получения нет в справочнике.",
      );
    }
    const related = body.related_number ? findLetter(body.related_number.trim()) : undefined;
    if (body.related_number && !related) {
      return invalid("related_number", "not_found", "Документ с таким номером не найден.");
    }
    const now = new Date().toISOString();
    const number = nextNumber();
    const addressee = body.addressee_id ? personOf(body.addressee_id) : DIRECTOR;
    if (!addressee) {
      return invalid("addressee_id", "not_active_employee", "Сотрудник не найден или отключён.");
    }
    const session = readSession();
    const user = session ? sessionRoles(session)?.user : undefined;
    const registrar = user ? (personOf(user.id) ?? REGISTRAR) : REGISTRAR;
    const draft = body.resolution_draft?.kind ? draftFrom(body.resolution_draft, registrar) : null;
    if (body.resolution_draft?.kind && !draft) {
      return invalid(
        "resolution_draft",
        "not_active_employee",
        "Сотрудник не найден или отключён.",
      );
    }
    const letter: LetterCard = {
      id: crypto.randomUUID(),
      number,
      status: "awaiting_resolution",
      subject: body.subject,
      summary: body.summary?.trim() || body.subject,
      urgent: Boolean(body.urgent) || kind.urgent,
      received_at: body.received_at,
      registered_at: now,
      registered_by: registrar,
      addressee,
      manager: null,
      sender: { name: body.sender_name, inn: body.sender_inn ?? null, contact: null },
      sender_ref: { number: body.sender_ref_number ?? null, date: body.sender_ref_date ?? null },
      client: null,
      request: body.deal_number
        ? {
            number: body.deal_number,
            title: null,
            path: `/erp/requests?request=${encodeURIComponent(body.deal_number)}&panel=open&tab=task`,
          }
        : null,
      stage: "RESOLUTION",
      lost_at_step: null,
      files: body.file_ids.map((id, index) => ({
        id,
        name: `скан-${String(index + 1)}.pdf`,
        content_type: "application/pdf",
        size: 120_000,
        uploaded_at: now,
      })),
      resolution: null,
      return_comment: null,
      reject_reason: null,
      journal: [
        { at: now, action: "letter.registered", by: registrar, comment: null },
        ...(exact && body.force
          ? [
              {
                at: now,
                action: "letter.duplicate_forced",
                by: registrar,
                comment: `Совпадает с ${exact.number}: ${body.force_reason?.trim() ?? ""}`,
              },
            ]
          : []),
      ],
      sources: { crm: "ok", erp: "ok" },
      kind: kind.code,
      receipt_method: body.receipt_method,
      signed_by: body.signed_by ?? null,
      document_due: body.document_due ?? null,
      related: related
        ? {
            kind: "letter_in",
            number: related.number,
            path: `/eds/inbox/${encodeURIComponent(related.number)}`,
          }
        : null,
      resolution_draft: draft,
    };
    writeLetters([letter, ...readLetters()]);
    // W18A-P2: ВХ из очереди «Входящая почта» — CRM снимает письмо с очереди по `letter.registered`
    if (body.source_mail_id) markMailRegistered(body.source_mail_id, number);
    return HttpResponse.json(present(letter, held.margin), { status: 201 });
  }),

  http.get("*/eds/resolution/assignees", () => {
    const held = guard("full");
    if (held.error) return held.error;
    return HttpResponse.json({
      zones: (["goods", "services", "payment_terms"] as const).map((zone) => ({
        zone,
        candidates: CANDIDATES[zone],
      })),
      directory: "ok",
    });
  }),

  http.get("*/eds/letter-files/:id", () => {
    // Файлы письма и отчётов скачивает и участник поручения без «Входящих» (решает EDS, P8b).
    if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    return new HttpResponse("демо-файл", {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": "attachment; filename*=UTF-8''demo.txt",
      },
    });
  }),

  http.get("*/eds/letters/*", ({ request }) => {
    const held = access();
    if (!held) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const letter = findLetter(refOf(request));
    if (!letter) {
      return failure(404, "NOT_FOUND", "Письмо не найдено.", "eds", { backend_status: 404 });
    }
    // P8b: без «Входящих» карточку видит участник поручения (исполнитель, «ознакомить», автор резолюции) — решает EDS.
    if (!canReadLetter(letter)) {
      return failure(403, "FORBIDDEN", "Нет права.", "eds", {
        backend_status: 403,
        permission: ["letters.read"],
      });
    }
    return HttpResponse.json(present(letter, held.margin));
  }),

  http.post("*/eds/letters/:id/resolution", async ({ request, params }) => {
    const held = guard("full");
    if (held.error) return held.error;
    const letter = findLetter(String(params["id"]));
    if (!letter) return failure(404, "NOT_FOUND", "Письмо не найдено.", "eds");
    const body = (await request.json()) as ResolutionIn;
    const conflict = notAwaiting(letter);
    if (conflict) return conflict;
    if (trackOf(letter) !== "calc") {
      return failure(409, "CONFLICT", "У письма другой путь резолюции.", "eds", {
        backend_status: 409,
        reason: "track_mismatch",
      });
    }
    if (body.due < companyToday()) {
      return invalid("due", "due_in_past", "Срок расчёта не может быть в прошлом.");
    }
    const all = Object.values(CANDIDATES).flat();
    const names = new Map(all.map((c) => [c.id, c.name]));
    if (body.assignees.some((a) => !names.has(a.id))) {
      return invalid("assignees", "not_active_employee", "Исполнитель не найден или отключён.");
    }
    const next = update(letter.id, (current) => ({
      ...current,
      status: "resolved",
      stage: "CALCULATION",
      resolution: {
        text: body.text,
        assignees: body.assignees.map((a) => ({
          person: {
            id: a.id,
            name: names.get(a.id) ?? a.id,
            initials: (names.get(a.id) ?? a.id).slice(0, 2).toUpperCase(),
          },
          zone: a.zone,
        })),
        due: body.due,
        min_margin_pct: body.min_margin_pct ?? null,
        decided_by: DIRECTOR,
        decided_at: new Date().toISOString(),
      },
      journal: [...current.journal, journalEntry("letter.resolved", body.text)],
    }));
    return HttpResponse.json(next ? present(next, held.margin) : letter);
  }),

  http.post("*/eds/letters/:id/return", async ({ request, params }) => {
    const held = guard("full");
    if (held.error) return held.error;
    const letter = findLetter(String(params["id"]));
    if (!letter) return failure(404, "NOT_FOUND", "Письмо не найдено.", "eds");
    const body = (await request.json()) as LetterReturnIn;
    const conflict = notAwaiting(letter);
    if (conflict) return conflict;
    const next = update(letter.id, (current) => ({
      ...current,
      status: "returned",
      stage: "REQUEST",
      return_comment: body.comment,
      journal: [...current.journal, journalEntry("letter.returned", body.comment)],
    }));
    return HttpResponse.json(next ? present(next, held.margin) : letter);
  }),

  http.post("*/eds/letters/:id/reject", async ({ request, params }) => {
    const held = guard("full");
    if (held.error) return held.error;
    const letter = findLetter(String(params["id"]));
    if (!letter) return failure(404, "NOT_FOUND", "Письмо не найдено.", "eds");
    const body = (await request.json()) as LetterRejectIn;
    const conflict = notAwaiting(letter);
    if (conflict) return conflict;
    const next = update(letter.id, (current) => ({
      ...current,
      status: "rejected",
      stage: "LOST",
      lost_at_step: 2,
      reject_reason: body.reason,
      journal: [...current.journal, journalEntry("letter.rejected", body.reason)],
    }));
    return HttpResponse.json(next ? present(next, held.margin) : letter);
  }),
];
