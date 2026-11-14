import { HttpResponse, http } from "msw";

import type {
  EdsStaffList,
  InstructionCompleteIn,
  InstructionReturnIn,
  InstructionExtensionDecisionIn,
  InstructionExtensionIn,
  LetterCard,
  LetterCloseIn,
  CoExecutorIn,
  LetterInstruction,
  LetterReply,
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
import { type MockDocument, readEds, writeEds } from "./fixtures/edsDocuments";
import { readDictionaries } from "./dictionaries";
import { findLetter, readLetters, writeLetters } from "./fixtures/letters";
import type { MockRole } from "./fixtures/roles";
import { buildMe, readSession, sessionRoles } from "./mockSession";

/** Рабочий экран и карточка исходящего: адреса, как их строит BFF (`outgoing_document_path`, `letter_task_path`). */
const outgoingPath = (documentId: string) =>
  `/eds/documents?scope=all&doc=${documentId}&panel=open`;

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
    admin: built?.resources["admin"] === "full",
    // пункт 1.6: автор документа выбирает согласующих и получателей копии
    author: built?.resources["eds.memo.create"] === "full",
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
    replies: repliesOf(letter),
  };
}

/** Итог отправки по последней попытке (как `reply.mail_state` EDS). */
function mailOf(doc: MockDocument): Pick<LetterReply, "mail" | "mail_reason"> {
  const last = doc.letter?.mailings.at(-1);
  if (!last) return { mail: "none", mail_reason: null };
  if (last.status === "sent") return { mail: "sent", mail_reason: null };
  if (last.status === "failed") return { mail: "failed", mail_reason: last.reason };
  return { mail: "sending", mail_reason: null };
}

/** Ответы на ВХ (EDS-REPLY-1): исходящие «в ответ на» это письмо, видимые смотрящему — свой черновик, зарегистрированное, переданное делопроизводителю. */
function repliesOf(letter: LetterCard): LetterReply[] {
  const user = me();
  if (!user) return [];
  const register = access().register;
  return readEds()
    .documents.filter((d) => d.kind === "letter_out" && d.replyTo === letter.number)
    .filter(
      (d) =>
        d.ownerId === user.id ||
        d.status === "sent" ||
        (register && Boolean(d.letter?.registration_requested)),
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((d) => ({
      document_id: d.id,
      number: d.number,
      subject: d.subject,
      state:
        d.status === "sent"
          ? ("registered" as const)
          : d.letter?.registration_requested
            ? ("registration_requested" as const)
            : ("draft" as const),
      author: personOf(d.ownerId) ?? user,
      ...mailOf(d),
      path: outgoingPath(d.id),
      created_at: d.created_at,
    }));
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
  /** Уведомление про исходящее (ответ на ВХ, EDS-REPLY-1): ведёт в его карточку */
  documentId?: string;
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

function notifyDocument(
  userIds: readonly string[],
  title: string,
  subtitle: string,
  letter: LetterCard,
  documentId: string,
  number: string,
) {
  const createdAt = new Date().toISOString();
  for (const userId of new Set(userIds)) {
    notes.push({
      seq: nextNote++,
      userId,
      title,
      subtitle,
      number,
      letterId: letter.id,
      documentId,
      createdAt,
      read: false,
    });
  }
}

/** Держатели раздела регистрации (`letters.register` EDS): им уходит «Зарегистрируйте ответ» и «Не отправлено». */
function registrarIds(): string[] {
  return DEMO_USERS.filter(
    (u) =>
      !u.loginError &&
      buildMe({
        userId: u.id,
        activeRole: null,
        language: "ru",
        mustChangePassword: false,
      })?.resources["eds.inbox.register"] === "full",
  ).map((u) => u.id);
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
      object: n.documentId
        ? { kind: "memo", number: n.number, path: outgoingPath(n.documentId) }
        : { kind: "letter", number: n.number, path: tasksPath(n.letterId) },
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
  const roleFor = (kind: "instruction" | "instruction_extension" | "acquaint" | "register_reply") =>
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
  // EDS-REPLY-1: «Зарегистрировать ИСХ» — ответы, переданные на регистрацию (держателю раздела регистрации)
  const registerRole = roleFor("register_reply");
  if (registerRole) {
    for (const doc of readEds().documents) {
      const requested = doc.letter?.registration_requested;
      if (doc.kind !== "letter_out" || doc.status !== "draft" || !requested) continue;
      const to = doc.replyTo;
      items.push({
        id: `register_reply:${doc.id}`,
        role_id: registerRole,
        kind: "register_reply",
        title: to ? `Зарегистрировать ИСХ: ответ на ${to}` : "Зарегистрировать ИСХ",
        subtitle: [doc.subject, personOf(doc.ownerId)?.name].filter(Boolean).join(" · "),
        due_label: "today",
        object: {
          kind: "memo",
          number: to ?? doc.subject,
          title: doc.subject,
          path: outgoingPath(doc.id),
        },
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
export function closeReplyInstructions(letterNumber: string, outgoingNumber: string): string[] {
  const letter = readLetters().find((l) => l.number === letterNumber);
  const user = me();
  if (!letter || !user) return [];
  const now = new Date().toISOString();
  let next = letter;
  const closed: string[] = [];
  for (const instruction of letter.instructions ?? []) {
    if (instruction.kind !== "reply" || instruction.status !== "in_work") continue;
    closed.push(instruction.person.id);
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
  if (closed.length === 0) return [];
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

/** «Передать на регистрацию»: делопроизводители узнают сразу (кроме того, кто передал). */
export function noticeRegistrationRequested(doc: MockDocument): void {
  const letter = doc.replyTo ? readLetters().find((l) => l.number === doc.replyTo) : undefined;
  if (!letter) return;
  const author = personOf(doc.ownerId);
  notifyDocument(
    registrarIds().filter((id) => id !== doc.ownerId),
    `Зарегистрируйте ответ на ${letter.number}`,
    [doc.subject, author?.name].filter(Boolean).join(" · "),
    letter,
    doc.id,
    letter.number,
  );
}

/** ИСХ зарегистрирован: исполнителю закрытого поручения и автору ответа (кроме того, кто зарегистрировал). */
export function noticeReplyRegistered(doc: MockDocument, closedExecutors: readonly string[]): void {
  const letter = doc.replyTo ? readLetters().find((l) => l.number === doc.replyTo) : undefined;
  const actor = me()?.id;
  if (!letter || !doc.number) return;
  notifyDocument(
    [...closedExecutors, doc.ownerId].filter((id) => id !== actor),
    `Ответ зарегистрирован: ${doc.number}`,
    `На ${letter.number} · ${closedExecutors.length > 0 ? "поручение исполнено" : doc.subject}`,
    letter,
    doc.id,
    doc.number,
  );
}

/** Письмо не ушло адресату: автор и делопроизводители узнают сразу (повтор — «Отправить адресату ещё раз»). */
export function noticeMailFailed(doc: MockDocument, reason: string | null): void {
  const letter = doc.replyTo ? readLetters().find((l) => l.number === doc.replyTo) : undefined;
  if (!letter) return;
  notifyDocument(
    [doc.ownerId, ...registrarIds()],
    `Не отправлено: ${doc.number ?? doc.subject}`,
    reason ?? "Письмо не ушло адресату",
    letter,
    doc.id,
    doc.number ?? letter.number,
  );
}

export const edsInstructionsHandlers = [
  http.get("*/eds/staff", () => {
    const held = access();
    if (!me()) return expired();
    // EDS-REG: администратору — люди общих шаблонов резолюций.
    if (!held.resolve && !held.register && !held.admin && !held.author)
      return forbiddenBff("eds.inbox");
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
            handed_to: null,
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

  // План 1.9: соисполнителя привлекает ответственный; срок не позже своего — правила как у EDS.
  http.post("*/eds/letters/:id/co-executors", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const letter = readLetters().find((l) => l.id === String(params["id"]));
    if (!letter) return notFound();
    const mine = (letter.instructions ?? []).find(
      (i) => i.person.id === user.id && i.role === "responsible",
    );
    if (!mine) {
      return failure(403, "FORBIDDEN", "Исход письма выбирает ответственный.", {
        reason: "not_responsible",
      });
    }
    if (mine.status !== "in_work" || letter.status !== "in_execution") {
      return conflict("invalid_state", "Поручение уже закрыто.");
    }
    const body = (await request.json()) as CoExecutorIn;
    if (body.due > mine.due)
      return invalid("due", "after_responsible_due", "Срок — не позже вашего.");
    const person = personOf(body.person_id);
    if (!person) return invalid("person_id", "not_active_employee", "Сотрудник не найден.");
    if ((letter.instructions ?? []).some((i) => i.person.id === person.id)) {
      return invalid("person_id", "already_assigned", "Сотрудник уже работает с этим письмом.");
    }
    const next: LetterCard = {
      ...letter,
      instructions: [
        ...(letter.instructions ?? []),
        {
          id: `co-${String(Date.now())}`,
          kind: "execute",
          role: "co_executor",
          person,
          due: body.due,
          text: body.text,
          status: "in_work",
          overdue: false,
          report: null,
          files: [],
          outgoing: null,
          handed_to: null,
          executed_at: null,
          extensions: [],
        },
      ],
      journal: [...letter.journal, entry("instruction.co_executor_added", user, body.text)],
    };
    return HttpResponse.json(save(next));
  }),

  // Исходы письма (решение владельца 2026-11-11) — правила как у EDS.
  http.post("*/eds/letters/:id/close", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const letter = readLetters().find((l) => l.id === String(params["id"]));
    if (!letter) return notFound();
    const mine = (letter.instructions ?? []).find(
      (i) => i.person.id === user.id && i.role === "responsible",
    );
    if (!mine) {
      return failure(403, "FORBIDDEN", "Исход письма выбирает ответственный.", {
        reason: "not_responsible",
      });
    }
    if (mine.status !== "in_work" || letter.status !== "in_execution") {
      return conflict("invalid_state", "Поручение уже закрыто.");
    }
    const body = (await request.json()) as LetterCloseIn;
    const reason = readDictionaries()["close-reasons"].find(
      (r) => r.code === body.reason && r.active,
    );
    if (!reason) return invalid("reason", "unknown", "Выберите причину из списка.");
    const comment = body.comment?.trim() || null;
    if (!comment && reason.attrs["comment_required"] === true) {
      return invalid("comment", "required", "Поясните причину.");
    }
    const now = new Date().toISOString();
    const report = `Закрыто без ответа: ${reason.name.ru}${comment ? `. ${comment}` : ""}`;
    const next: LetterCard = {
      ...letter,
      status: "closed",
      on_control: false,
      executed_at: now,
      close_reason: reason.code,
      close_comment: comment,
      instructions: (letter.instructions ?? []).map((i) =>
        i.id === mine.id
          ? { ...i, status: "executed", report, executed_at: now }
          : i.status === "in_work"
            ? { ...i, status: "cancelled", executed_at: now }
            : i,
      ),
      journal: [...letter.journal, entry("letter.closed", user, report)],
    };
    const author = letter.office_resolution?.decided_by.id;
    if (author) notify([author], `Закрыто без ответа: ${letter.number}`, letter, report);
    return HttpResponse.json(save(next));
  }),

  http.post("*/eds/letters/:id/reopen", ({ params }) => {
    const user = me();
    if (!user) return expired();
    const letter = readLetters().find((l) => l.id === String(params["id"]));
    if (!letter) return notFound();
    if (letter.office_resolution?.decided_by.id !== user.id) {
      return failure(403, "FORBIDDEN", "Вернуть письмо в работу может автор резолюции.", {
        reason: "not_resolution_author",
      });
    }
    if (letter.status !== "closed") return conflict("invalid_state", "Письмо не закрыто.");
    const closedAt = letter.executed_at;
    const next: LetterCard = {
      ...letter,
      status: "in_execution",
      on_control: true,
      executed_at: null,
      close_reason: null,
      close_comment: null,
      instructions: (letter.instructions ?? []).map((i) =>
        i.executed_at === closedAt
          ? { ...i, status: "in_work", report: null, executed_at: null }
          : i,
      ),
      journal: [...letter.journal, entry("letter.reopened", user)],
    };
    return HttpResponse.json(save(next));
  }),

  http.post("*/eds/instructions/:id/return", async ({ request, params }) => {
    const user = me();
    if (!user) return expired();
    const found = findInstruction(String(params["id"]));
    if (!found) return notFound();
    const { letter, instruction } = found;
    if (instruction.person.id !== user.id || instruction.role !== "responsible") {
      return failure(403, "FORBIDDEN", "Вернуть письмо может ответственный.", {
        reason: "not_responsible",
      });
    }
    if ((letter.instructions ?? []).some((i) => i.status === "executed")) {
      return conflict("instruction_executed", "Часть поручений уже исполнена.");
    }
    const body = (await request.json()) as InstructionReturnIn;
    const reason = body.reason.trim();
    if (!reason) return invalid("reason", "required", "Напишите причину.");
    const author = letter.office_resolution?.decided_by.id;
    const next: LetterCard = {
      ...letter,
      status: "awaiting_resolution",
      on_control: false,
      office_resolution: null,
      instructions: [],
      journal: [...letter.journal, entry("letter.returned_to_author", user, reason)],
    };
    if (author) notify([author], `Вернули письмо: ${letter.number}`, letter, reason);
    return HttpResponse.json(save(next));
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
    // План 1.9: «Передать в работу» — исход ответственного; записка — своя из реестра, заявка — сделка CRM
    let handed: LetterInstruction["handed_to"] = null;
    if (body.handed_to) {
      if (instruction.role !== "responsible") {
        return failure(403, "FORBIDDEN", "Передать письмо в работу может только ответственный.", {
          reason: "not_responsible",
        });
      }
      const ref = body.handed_to.id;
      if (body.handed_to.kind === "memo") {
        const memo = readEds().documents.find((d) => d.id === ref && d.kind !== "letter_out");
        if (!memo?.number) return invalid("handed_to", "not_found", "Объект не найден.");
        handed = { kind: "memo", number: memo.number, path: outgoingPath(memo.id) };
      } else {
        if (!/^[1-9]\d*$/.test(ref)) return invalid("handed_to", "not_found", "Объект не найден.");
        handed = { kind: "client_request", number: ref, path: null };
      }
    }
    if (!body.report?.trim() && files.length === 0 && !body.outgoing_number && !handed) {
      return invalid("report", "report_required", "Нужен отчёт или ИСХ.");
    }
    if (body.outgoing_number && !/^ИСХ-\d{3,}\/\d{2}$/.test(body.outgoing_number.trim())) {
      return invalid("outgoing_number", "not_found", "ИСХ с таким номером не найден.");
    }
    // EDS-REPLY-1: ИСХ «в ответ на» это письмо или без связи (связь записывается); чужой ответ — 409
    if (body.outgoing_number) {
      const state = readEds();
      const outgoing = state.documents.find(
        (d) => d.kind === "letter_out" && d.number === body.outgoing_number?.trim(),
      );
      if (outgoing?.replyTo && outgoing.replyTo !== letter.number) {
        return conflict(
          "outgoing_linked_elsewhere",
          `${outgoing.number ?? "ИСХ"} уже отвечает на ${outgoing.replyTo}.`,
        );
      }
      if (outgoing && !outgoing.replyTo) {
        outgoing.replyTo = letter.number;
        writeEds(state);
      }
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
      handed_to: handed,
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
