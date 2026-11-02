import { HttpResponse, http } from "msw";

import type {
  EdsStaffList,
  InstructionCompleteIn,
  InstructionExtensionDecisionIn,
  InstructionExtensionIn,
  LetterCard,
  LetterInstruction,
  LetterResolutionDraft,
  Notification,
  OfficeResolutionIn,
  PersonRef,
  QueueItem,
  ResolutionDraftIn,
} from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import { COMPANY_TIME_ZONE } from "../shared/lib/format";
import { DEMO_USERS } from "./fixtures/users";
import { findLetter, readLetters, writeLetters } from "./fixtures/letters";
import type { MockRole } from "./fixtures/roles";
import { buildMe, readSession, sessionRoles } from "./mockSession";

/**
 * Моки поручений по входящим (P8b, SPEC-v3 §3.2a; BFF 0.31.0): путь резолюции (`track`), подсказка срока, резолюция трёх
 * типов, проект делопроизводителя, поручения, перенос, ознакомление, «Мои задачи» и колокольчик. Правила — как у EDS:
 * путь `calc` — письмо по заявке клиента (связь с заявкой и нет вида документа), остальное — `office`; срочные не
 * продлеваются; перенос решает автор резолюции; все поручения исполнены → письмо «Исполнено», контроль снят.
 */

const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: COMPANY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());

function failure(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return HttpResponse.json(
    { code, message, source: "eds", details: { backend_status: status, ...details } },
    { status },
  );
}
const invalid = (field: string, reason: string, message: string) =>
  failure(422, "VALIDATION_FAILED", message, { fields: [field], reason });
const conflict = (reason: string, message: string) => failure(409, "CONFLICT", message, { reason });

/** Сотрудники мока, которых можно выбрать (без отключённого). */
const STAFF = DEMO_USERS.filter((u) => !u.loginError);

export function personOf(id: string): PersonRef | undefined {
  const user = DEMO_USERS.find((u) => u.id === id);
  return user ? { id: user.id, name: user.name, initials: user.initials } : undefined;
}

function me(): PersonRef | undefined {
  const session = readSession();
  const user = session ? sessionRoles(session)?.user : undefined;
  return user ? { id: user.id, name: user.name, initials: user.initials } : undefined;
}

function access() {
  const session = readSession();
  const built = session ? buildMe({ ...session, activeRole: null }) : undefined;
  return {
    resolve: built?.resources["eds.inbox"] === "full",
    register: built?.resources["eds.inbox.register"] === "full",
    read: Boolean(built?.resources["eds.inbox"] || built?.resources["eds.inbox.register"]),
  };
}

// --- путь, подсказка срока, признаки ------------------------------------------------------------

/** Путь резолюции (решает EDS): письмо по заявке клиента — расчёт по зонам; с видом документа — делопроизводство. */
export function trackOf(letter: LetterCard): "calc" | "office" {
  if (letter.track) return letter.track;
  return !letter.kind && letter.request ? "calc" : "office";
}

const DAY = 86_400_000;
const iso = (d: Date) => d.toISOString().slice(0, 10);
const parse = (value: string) => new Date(`${value}T00:00:00Z`);
const weekend = (d: Date) => d.getUTCDay() === 0 || d.getUTCDay() === 6;

/** Подсказка срока (бенчмарк СЭД §6.4): срок по документу минус рабочий день, иначе 3/10 дней, выходной → понедельник. */
export function suggestedDue(letter: LetterCard, now = today()): string | null {
  if (trackOf(letter) !== "office") return null;
  let due: Date;
  if (letter.document_due) {
    due = new Date(parse(letter.document_due).getTime() - DAY);
    while (weekend(due)) due = new Date(due.getTime() - DAY);
  } else {
    const from = parse(letter.registered_at.slice(0, 10));
    due = new Date(from.getTime() + (letter.urgent ? 3 : 10) * DAY);
    while (weekend(due)) due = new Date(due.getTime() + DAY);
  }
  const value = iso(due);
  return value < now ? now : value;
}

/** Карточка с полями P8b: путь, подсказка, просрочка поручений (признак на сегодня). */
export function withOffice(letter: LetterCard): LetterCard {
  const now = today();
  const instructions = (letter.instructions ?? []).map((i) => ({
    ...i,
    overdue: i.status === "in_work" && i.due < now,
  }));
  return {
    ...letter,
    track: trackOf(letter),
    on_control: letter.on_control ?? false,
    suggested_due: letter.status === "awaiting_resolution" ? suggestedDue(letter, now) : null,
    resolution_draft: letter.resolution_draft ?? null,
    office_resolution: letter.office_resolution ?? null,
    instructions,
    acquaintances: letter.acquaintances ?? [],
    executed_at: letter.executed_at ?? null,
  };
}

export function rowExtras(letter: LetterCard) {
  const card = withOffice(letter);
  const responsible = card.instructions?.find((i) => i.role === "responsible");
  return {
    track: card.track ?? "office",
    on_control: card.on_control ?? false,
    overdue: (card.instructions ?? []).some((i) => i.overdue),
    executor: responsible?.person ?? null,
    ...(responsible ? { due: responsible.due } : {}),
  };
}

/** Участник письма (исполнитель, «ознакомить», автор резолюции) видит его без раздела «Входящие» (решает EDS). */
export function isParticipant(letter: LetterCard, userId: string): boolean {
  return (
    (letter.instructions ?? []).some((i) => i.person.id === userId) ||
    (letter.acquaintances ?? []).some((a) => a.person.id === userId) ||
    letter.office_resolution?.decided_by.id === userId
  );
}

export function canReadLetter(letter: LetterCard): boolean {
  const user = me();
  return access().read || (user !== undefined && isParticipant(letter, user.id));
}

// --- колокольчик -----------------------------------------------------------------------------

interface Note {
  seq: number;
  userId: string;
  title: string;
  subtitle: string;
  number: string;
  letterId: string;
  createdAt: string;
  read: boolean;
}
let notes: Note[] = [];
let nextNote = 1;

function notify(userIds: readonly string[], title: string, letter: LetterCard, subtitle?: string) {
  const createdAt = new Date().toISOString();
  for (const userId of new Set(userIds)) {
    notes.push({
      seq: nextNote++,
      userId,
      title,
      subtitle: subtitle ?? letter.subject,
      number: letter.number,
      letterId: letter.id,
      createdAt,
      read: false,
    });
  }
}

/** Уведомления CRM по поручениям (`eds.notice.requested` → `staff_notifications`) — лента `crm:<id>` колокольчика. */
export function letterNotificationsOf(userId: string): Notification[] {
  return notes
    .filter((n) => n.userId === userId)
    .map((n) => ({
      id: `crm:eds-${String(n.seq)}`,
      tab: "decisions",
      title: n.title,
      subtitle: n.subtitle,
      object: {
        kind: "letter",
        number: n.number,
        path: tasksPath(n.letterId),
      },
      created_at: n.createdAt,
      read: n.read,
    }));
}

export function markLetterNoteRead(userId: string, id: string): boolean {
  let found = false;
  for (const n of notes) {
    if (n.userId === userId && (id === "all" || id === `crm:eds-${String(n.seq)}`)) {
      n.read = true;
      found = true;
    }
  }
  return found;
}

export function resetInstructionsMock(): void {
  notes = [];
  nextNote = 1;
}

// --- «Мои задачи» ----------------------------------------------------------------------------

/** Рабочий экран — по UUID письма, как отдаёт BFF (по номеру — реестр, которого у исполнителя может не быть). */
function tasksPath(letterId: string): string {
  return `/eds/tasks/${letterId}`;
}

/** Строки «Моих задач» (BFF `instruction`, `instruction_extension`, `acquaint`): одна на поручение, перенос, ознакомление. */
export function letterTaskQueueItems(view: readonly MockRole[]): QueueItem[] {
  const user = me();
  if (!user) return [];
  const roleFor = (kind: "instruction" | "instruction_extension" | "acquaint") =>
    view.find((r) => allows(r.access, QUEUE[kind].resource, QUEUE[kind].level))?.id;
  const items: QueueItem[] = [];
  const now = today();
  for (const raw of readLetters()) {
    const letter = withOffice(raw);
    const object = {
      kind: "letter" as const,
      number: letter.number,
      title: `Письмо ${letter.number}`,
      path: tasksPath(letter.id),
    };
    const sender = letter.sender.name;
    const instructionRole = roleFor("instruction");
    for (const i of letter.instructions ?? []) {
      if (instructionRole && i.person.id === user.id && i.status === "in_work") {
        const label = i.due < now ? "overdue" : i.due === now ? "today" : "later";
        items.push({
          id: `instruction:${i.id}`,
          role_id: instructionRole,
          kind: "instruction",
          title:
            i.kind === "reply"
              ? `Подготовить ответ на письмо ${letter.number}`
              : `Исполнить поручение по письму ${letter.number}`,
          subtitle: [sender, letter.subject].filter(Boolean).join(" · "),
          due_label: label,
          due_at: `${i.due}T18:00:00+05:00`,
          object,
        });
      }
      const pending = i.extensions.find((e) => e.status === "pending");
      const extensionRole = roleFor("instruction_extension");
      if (pending && extensionRole && letter.office_resolution?.decided_by.id === user.id) {
        items.push({
          id: `instruction_extension:${pending.id}`,
          role_id: extensionRole,
          kind: "instruction_extension",
          title: `Решить перенос срока по письму ${letter.number}`,
          subtitle: `${pending.requested_by.name} · до ${pending.new_due.split("-").reverse().join(".")} · ${pending.reason}`,
          due_label: "today",
          object,
        });
      }
    }
    const acquaintRole = roleFor("acquaint");
    const mine = (letter.acquaintances ?? []).find((a) => a.person.id === user.id);
    if (acquaintRole && mine && !mine.acknowledged_at) {
      items.push({
        id: `acquaint:${letter.id}`,
        role_id: acquaintRole,
        kind: "acquaint",
        title: `Ознакомиться с письмом ${letter.number}`,
        subtitle: [sender, letter.subject].filter(Boolean).join(" · "),
        due_label: "later",
        object,
      });
    }
  }
  return items;
}

// --- изменения ---------------------------------------------------------------------------------

function save(next: LetterCard): LetterCard {
  writeLetters(readLetters().map((l) => (l.id === next.id ? next : l)));
  return withOffice(next);
}

const entry = (action: string, by: PersonRef, comment: string | null = null) => ({
  at: new Date().toISOString(),
  action,
  by,
  comment,
});

function people(ids: readonly string[] | undefined): PersonRef[] | null {
  const found = (ids ?? []).map(personOf);
  return found.every(Boolean) ? (found as PersonRef[]) : null;
}

function findInstruction(
  id: string,
): { letter: LetterCard; instruction: LetterInstruction } | null {
  for (const letter of readLetters()) {
    const instruction = (letter.instructions ?? []).find((i) => i.id === id);
    if (instruction) return { letter, instruction };
  }
  return null;
}

function replaceInstruction(letter: LetterCard, next: LetterInstruction): LetterCard {
  return {
    ...letter,
    instructions: (letter.instructions ?? []).map((i) => (i.id === next.id ? next : i)),
  };
}

/** Проект резолюции из тела запроса; сотрудник не найден — `null`. */
export function draftFrom(body: ResolutionDraftIn, by: PersonRef): LetterResolutionDraft | null {
  const responsible = body.responsible_id ? personOf(body.responsible_id) : null;
  const co = people(body.co_executor_ids);
  const acquaint = people(body.acquaint_ids);
  if (responsible === undefined || !co || !acquaint) return null;
  return {
    kind: body.kind ?? null,
    responsible,
    due: body.due ?? null,
    text: body.text ?? null,
    co_executors: co,
    acquaint,
    drafted_by: by,
    drafted_at: new Date().toISOString(),
  };
}

function notAwaitingOffice(letter: LetterCard) {
  if (trackOf(letter) !== "office") {
    return conflict("track_mismatch", "У письма другой путь резолюции.");
  }
  if (letter.status !== "awaiting_resolution") {
    return conflict("invalid_state", "Операция недоступна в текущем статусе письма.");
  }
  return null;
}

const notFound = () => failure(404, "NOT_FOUND", "Не найдено.");
const expired = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );
const forbiddenBff = (resource: string) =>
  HttpResponse.json(
    {
      code: "FORBIDDEN",
      message: "Раздел или действие не положены вашей роли.",
      source: "bff",
      details: { resource, need: "full" },
    },
    { status: 403 },
  );

/**
 * Хук регистрации ИСХ «в ответ на ВХ» (как `close_by_outgoing` EDS, P8b/P4): поручения «Подготовить ответ» письма в работе
 * → «Исполнено» со ссылкой на ИСХ; все исполнены — письмо «Исполнено», уведомление автору резолюции и делопроизводителю.
 */
export function closeReplyInstructions(letterNumber: string, outgoingNumber: string): number {
  const letter = readLetters().find((l) => l.number === letterNumber);
  const user = me();
  if (!letter || !user) return 0;
  const now = new Date().toISOString();
  let next = letter;
  let closed = 0;
  for (const instruction of letter.instructions ?? []) {
    if (instruction.kind !== "reply" || instruction.status !== "in_work") continue;
    closed += 1;
    next = replaceInstruction(next, {
      ...instruction,
      status: "executed",
      outgoing: {
        number: outgoingNumber,
        path: `/eds/documents?scope=all&q=${encodeURIComponent(outgoingNumber)}`,
      },
      executed_at: now,
    });
    next = {
      ...next,
      journal: [...next.journal, entry("instruction.executed", user, `Ответ ${outgoingNumber}`)],
    };
  }
  if (closed === 0) return 0;
  if ((next.instructions ?? []).every((i) => i.status === "executed")) {
    next = {
      ...next,
      status: "executed",
      on_control: false,
      executed_at: now,
      journal: [...next.journal, { ...entry("letter.executed", user), by: null }],
    };
    const ids = [next.office_resolution?.decided_by.id, next.registered_by?.id];
    notify(
      ids.filter((id): id is string => Boolean(id)),
      `Письмо ${letter.number} исполнено`,
      letter,
    );
  }
  save(next);
  return closed;
}

export const edsInstructionsHandlers = [
  http.get("*/eds/staff", () => {
    const held = access();
    if (!me()) return expired();
    if (!held.resolve && !held.register) return forbiddenBff("eds.inbox");
    const list: EdsStaffList = {
      items: STAFF.map((u) => ({ id: u.id, name: u.name, position: u.position })).sort((a, b) =>
        a.name.localeCompare(b.name, "ru"),
      ),
    };
    return HttpResponse.json(list);
  }),

  http.put("*/eds/letters/:id/resolution-draft", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const held = access();
    if (!held.resolve && !held.register) return forbiddenBff("eds.inbox.register");
    const letter = findLetter(String(params["id"]));
    if (!letter) return notFound();
    const blocked = notAwaitingOffice(letter);
    if (blocked) return blocked;
    const body = (await request.json()) as ResolutionDraftIn;
    if (body.due && body.due < today()) {
      return invalid("due", "due_in_past", "Срок не может быть в прошлом.");
    }
    const draft = draftFrom(body, user);
    if (!draft) return invalid("responsible_id", "not_active_employee", "Сотрудник не найден.");
    return HttpResponse.json(
      save({
        ...letter,
        resolution_draft: body.kind ? draft : null,
        journal: [...letter.journal, entry("letter.draft_saved", user)],
      }),
    );
  }),

  http.post("*/eds/letters/:id/office-resolution", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    if (!access().resolve) return forbiddenBff("eds.inbox");
    const letter = findLetter(String(params["id"]));
    if (!letter) return notFound();
    const blocked = notAwaitingOffice(letter);
    if (blocked) return blocked;
    const body = (await request.json()) as OfficeResolutionIn;
    const executor = body.kind !== "info";
    if (!executor && (body.responsible_id || body.due)) {
      return invalid("responsible_id", "not_allowed_for_info", "У «Для сведения» нет исполнителя.");
    }
    if (executor && (!body.responsible_id || !body.due)) {
      return invalid(body.responsible_id ? "due" : "responsible_id", "required", "Обязательно.");
    }
    if (executor && body.due && body.due < today()) {
      return invalid("due", "due_in_past", "Срок не может быть в прошлом.");
    }
    const responsible = body.responsible_id ? personOf(body.responsible_id) : null;
    const co = people(body.co_executor_ids);
    const acquaint = people(body.acquaint_ids);
    if (responsible === undefined || !co || !acquaint) {
      return invalid("responsible_id", "not_active_employee", "Сотрудник не найден или отключён.");
    }
    const now = new Date().toISOString();
    const instructions: LetterInstruction[] =
      executor && responsible && body.due
        ? [
            { person: responsible, role: "responsible" as const },
            ...co.map((person) => ({ person, role: "co_executor" as const })),
          ].map(({ person, role }) => ({
            id: crypto.randomUUID(),
            kind: body.kind,
            role,
            person,
            due: body.due ?? "",
            text: body.text,
            status: "in_work" as const,
            overdue: false,
            report: null,
            files: [],
            outgoing: null,
            executed_at: null,
            extensions: [],
          }))
        : [];
    const next: LetterCard = {
      ...letter,
      status: executor ? "in_execution" : "noted",
      stage: "RESOLUTION",
      on_control: executor,
      resolution_draft: null,
      office_resolution: {
        kind: body.kind,
        text: body.text,
        due: executor ? (body.due ?? null) : null,
        responsible: responsible ?? null,
        co_executors: co,
        acquaint,
        decided_by: user,
        decided_at: now,
      },
      instructions,
      acquaintances: acquaint.map((person) => ({ person, acknowledged_at: null })),
      journal: [...letter.journal, entry("letter.resolved", user, body.text)],
    };
    const saved = save(next);
    if (instructions.length > 0) {
      notify(
        instructions.map((i) => i.person.id),
        `Поручение по письму ${letter.number}`,
        letter,
        `${letter.subject} · срок ${(body.due ?? "").split("-").reverse().join(".")}`,
      );
    }
    if (acquaint.length > 0) {
      notify(
        acquaint.map((p) => p.id),
        `Ознакомиться с письмом ${letter.number}`,
        letter,
      );
    }
    return HttpResponse.json(saved);
  }),

  http.post("*/eds/letters/:id/acquaint", ({ params }) => {
    const user = me();
    if (!user) return expired();
    const letter = findLetter(String(params["id"]));
    const mine = letter?.acquaintances?.find((a) => a.person.id === user.id);
    if (!letter || !mine) return notFound();
    if (mine.acknowledged_at) return HttpResponse.json(withOffice(letter));
    return HttpResponse.json(
      save({
        ...letter,
        acquaintances: (letter.acquaintances ?? []).map((a) =>
          a.person.id === user.id ? { ...a, acknowledged_at: new Date().toISOString() } : a,
        ),
        journal: [...letter.journal, entry("letter.acknowledged", user)],
      }),
    );
  }),

  http.post("*/eds/instructions/:id/complete", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const found = findInstruction(String(params["id"]));
    if (!found) return notFound();
    const { letter, instruction } = found;
    if (instruction.person.id !== user.id) {
      return failure(403, "FORBIDDEN", "Поручение не ваше.", { reason: "not_executor" });
    }
    if (instruction.status !== "in_work") {
      return conflict("invalid_state", "Поручение уже исполнено.");
    }
    const body = (await request.json()) as InstructionCompleteIn;
    const files = body.file_ids ?? [];
    if (!body.report?.trim() && files.length === 0 && !body.outgoing_number) {
      return invalid("report", "report_required", "Нужен отчёт или ИСХ.");
    }
    if (body.outgoing_number && !/^ИСХ-\d{3,}\/\d{2}$/.test(body.outgoing_number.trim())) {
      return invalid("outgoing_number", "not_found", "ИСХ с таким номером не найден.");
    }
    const now = new Date().toISOString();
    let next = replaceInstruction(letter, {
      ...instruction,
      status: "executed",
      report: body.report?.trim() || null,
      files: files.map((id, index) => ({
        id,
        name: `отчёт-${String(index + 1)}.pdf`,
        content_type: "application/pdf",
        size: 64_000,
        uploaded_at: now,
      })),
      outgoing: body.outgoing_number
        ? {
            number: body.outgoing_number.trim(),
            path: `/eds/documents?scope=all&q=${encodeURIComponent(body.outgoing_number.trim())}`,
          }
        : null,
      executed_at: now,
    });
    next = {
      ...next,
      journal: [...next.journal, entry("instruction.executed", user, body.report ?? null)],
    };
    const all = (next.instructions ?? []).every((i) => i.status === "executed");
    if (all) {
      next = {
        ...next,
        status: "executed",
        on_control: false,
        executed_at: now,
        journal: [...next.journal, { ...entry("letter.executed", user), by: null }],
      };
      const author = next.office_resolution?.decided_by.id;
      const registrar = next.registered_by?.id;
      notify(
        [author, registrar].filter((id): id is string => Boolean(id)),
        `Письмо ${letter.number} исполнено`,
        letter,
      );
    }
    return HttpResponse.json(save(next));
  }),

  http.post("*/eds/instructions/:id/extension", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const found = findInstruction(String(params["id"]));
    if (!found) return notFound();
    const { letter, instruction } = found;
    if (instruction.person.id !== user.id) {
      return failure(403, "FORBIDDEN", "Поручение не ваше.", { reason: "not_executor" });
    }
    if (instruction.status !== "in_work") return conflict("invalid_state", "Поручение исполнено.");
    if (instruction.extensions.some((e) => e.status === "pending")) {
      return conflict("extension_pending", "Запрос уже ждёт решения.");
    }
    const body = (await request.json()) as InstructionExtensionIn;
    if (body.new_due <= instruction.due) {
      return invalid("new_due", "not_later", "Новый срок не позже текущего.");
    }
    const next = replaceInstruction(letter, {
      ...instruction,
      extensions: [
        ...instruction.extensions,
        {
          id: crypto.randomUUID(),
          old_due: instruction.due,
          new_due: body.new_due,
          reason: body.reason,
          status: "pending",
          requested_by: user,
          requested_at: new Date().toISOString(),
          decided_by: null,
          decided_at: null,
          comment: null,
        },
      ],
    });
    const author = letter.office_resolution?.decided_by.id;
    if (author) {
      notify([author], `Перенос срока по письму ${letter.number}`, letter, body.reason);
    }
    return HttpResponse.json(
      save({
        ...next,
        journal: [...next.journal, entry("instruction.extension_requested", user, body.reason)],
      }),
    );
  }),

  http.post("*/eds/instructions/:id/extension/decision", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    if (!access().resolve) return forbiddenBff("eds.inbox");
    const found = findInstruction(String(params["id"]));
    if (!found) return notFound();
    const { letter, instruction } = found;
    if (letter.office_resolution?.decided_by.id !== user.id) {
      return failure(403, "FORBIDDEN", "Перенос решает автор резолюции.", {
        reason: "not_resolution_author",
      });
    }
    const pending = instruction.extensions.find((e) => e.status === "pending");
    if (!pending) return conflict("no_pending_extension", "Запроса нет.");
    const body = (await request.json()) as InstructionExtensionDecisionIn;
    const approve = body.decision === "approve";
    // Росархив 5.14: срок срочного не продлевается — запрос принимается, одобрить нельзя, только отклонить.
    if (approve && letter.urgent) {
      return conflict("urgent_not_extendable", "Срок срочного письма не продлевается.");
    }
    const now = new Date().toISOString();
    let next = replaceInstruction(letter, {
      ...instruction,
      due: approve ? pending.new_due : instruction.due,
      extensions: instruction.extensions.map((e) =>
        e.id === pending.id
          ? {
              ...e,
              status: approve ? ("approved" as const) : ("rejected" as const),
              decided_by: user,
              decided_at: now,
              comment: body.comment ?? null,
            }
          : e,
      ),
    });
    if (approve && instruction.role === "responsible" && next.office_resolution) {
      next = { ...next, office_resolution: { ...next.office_resolution, due: pending.new_due } };
    }
    notify(
      [instruction.person.id],
      approve
        ? `Перенос срока одобрен: ${letter.number}`
        : `Перенос срока отклонён: ${letter.number}`,
      letter,
    );
    return HttpResponse.json(
      save({
        ...next,
        journal: [
          ...next.journal,
          entry(
            approve ? "instruction.extension_approved" : "instruction.extension_rejected",
            user,
            body.comment ?? null,
          ),
        ],
      }),
    );
  }),
];
