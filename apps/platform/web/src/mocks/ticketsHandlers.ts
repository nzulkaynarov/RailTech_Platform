import { HttpResponse, http } from "msw";

import type {
  Notification,
  QueueItem,
  Ticket,
  TicketCreate,
  TicketReply,
  TicketRow,
  TicketStatus,
  TicketStatusChange,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { type MockRole, computeAccess } from "./fixtures/roles";
import { DEMO_USERS } from "./fixtures/users";
import { buildMe, readSession, sessionRoles, updateSession } from "./mockSession";
import {
  type StoredTicket,
  addNote,
  numberOf,
  rateExceeded,
  readTickets,
  seqOf,
  writeTickets,
} from "./ticketsStore";

/**
 * Моки W15-H7 (BFF 0.24.0): «Написать администратору», «Мои обращения», Настройки · Обращения сотрудников и первый вход.
 * Правила как у CRM: тема из списка, текст 1–4000, не больше пяти обращений в час, свои обращения видит только автор,
 * ответ и статус — раздел `admin` полный, чтение — от чтения; ответ и решение уходят автору в колокольчик.
 */
const SUBJECTS = ["access", "notification", "template", "error", "other"] as const;
const MOVES: Record<TicketStatus, readonly TicketStatus[]> = {
  new: ["in_progress", "resolved"],
  in_progress: ["resolved"],
  resolved: ["in_progress"],
};

function me() {
  const session = readSession();
  return session ? buildMe(session) : undefined;
}

function snippet(text: string, limit = 110): string {
  const flat = text.split(/\s+/).filter(Boolean).join(" ");
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1).trimEnd()}…`;
}

function row(t: StoredTicket): TicketRow {
  return {
    number: numberOf(t.seq),
    subject: t.subject,
    status: t.status,
    author: { id: t.authorId, name: t.authorName },
    ...(t.authorRole ? { author_role: t.authorRole } : {}),
    ...(t.page ? { page: t.page } : {}),
    preview: snippet(t.body, 140),
    replies: t.messages.length,
    created_at: t.createdAt,
    updated_at: t.updatedAt,
  };
}

function full(t: StoredTicket): Ticket {
  return {
    ...row(t),
    body: t.body,
    messages: t.messages.map((m) => ({
      author_name: m.author_name,
      body: m.body,
      created_at: m.created_at,
    })),
    ...(t.resolvedAt ? { resolved_at: t.resolvedAt } : {}),
  };
}

const invalid = (field: string, reason: string, message: string) =>
  failure(422, "VALIDATION_FAILED", message, "crm", { fields: [field], reason });

/** Администраторы мока — все, у кого в ролях есть раздел `admin` полным уровнем. */
function adminIds(): string[] {
  return DEMO_USERS.filter((u) => {
    const roles = sessionRoles({
      userId: u.id,
      activeRole: null,
      language: "ru",
      mustChangePassword: false,
    });
    return roles ? computeAccess(roles.all).resources["admin"] === "full" : false;
  }).map((u) => u.id);
}

/** Уведомления CRM текущего сотрудника — для ленты колокольчика (`crm:<seq>`). */
export function crmNotificationsOf(userId: string): Notification[] {
  return readTickets()
    .notes.filter((n) => n.userId === userId)
    .map((n) => ({
      id: `crm:${String(n.seq)}`,
      tab: n.tab,
      title: n.title,
      ...(n.subtitle ? { subtitle: n.subtitle } : {}),
      ...(n.ticketNumber
        ? {
            object: {
              kind: "ticket" as const,
              number: n.ticketNumber,
              path:
                n.kind === "ticket_new"
                  ? `/admin/tickets/${encodeURIComponent(n.ticketNumber)}?panel=open&tab=card`
                  : `/help/requests/${encodeURIComponent(n.ticketNumber)}`,
            },
          }
        : {}),
      created_at: n.createdAt,
      read: n.read,
    }));
}

const SUBJECT_TITLE: Record<(typeof SUBJECTS)[number], string> = {
  access: "Нужен доступ к разделу",
  notification: "Не приходит уведомление",
  template: "Нужен шаблон документа",
  error: "Ошибка",
  other: "Другое",
};

/** «Мои задачи» администратора: новые обращения (вид `ticket`, раздел `admin` полный) — как у BFF; директору строк нет. */
export function ticketQueueItems(view: readonly MockRole[]): QueueItem[] {
  const role = view.find((r) => r.access["admin"] === "full");
  if (!role) return [];
  return readTickets()
    .tickets.filter((t) => t.status === "new")
    .sort((a, b) => a.seq - b.seq)
    .map((t) => ({
      id: `ticket:${String(t.seq)}`,
      role_id: role.id,
      kind: "ticket" as const,
      title: `Ответить на обращение ${numberOf(t.seq)}`,
      subtitle: [t.authorName, SUBJECT_TITLE[t.subject], snippet(t.body, 80)].join(" · "),
      due_label: "today" as const,
      object: {
        kind: "ticket" as const,
        number: numberOf(t.seq),
        path: `/admin/tickets/${encodeURIComponent(numberOf(t.seq))}?panel=open&tab=card`,
      },
    }));
}

export function markCrmNoteRead(userId: string, id: string): boolean {
  const state = readTickets();
  let found = false;
  for (const n of state.notes) {
    if (n.userId !== userId) continue;
    if (id === "all" || `crm:${String(n.seq)}` === id) {
      n.read = true;
      found = true;
    }
  }
  writeTickets(state);
  return found;
}

export const ticketsHandlers = [
  http.get("*/admin/tickets", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const subject = q.get("subject");
    const limit = Number(q.get("limit") ?? 50);
    const offset = Number(q.get("offset") ?? 0);
    const all = readTickets().tickets;
    const order = { new: 0, in_progress: 1, resolved: 2 } as const;
    const items = all
      .filter((t) => (!status || t.status === status) && (!subject || t.subject === subject))
      .sort(
        (a, b) =>
          order[a.status] - order[b.status] ||
          b.updatedAt.localeCompare(a.updatedAt) ||
          b.seq - a.seq,
      );
    const count = (s: TicketStatus) => all.filter((t) => t.status === s).length;
    return HttpResponse.json({
      items: items.slice(offset, offset + limit).map(row),
      total: items.length,
      counts: { new: count("new"), in_progress: count("in_progress"), resolved: count("resolved") },
    });
  }),

  http.get("*/admin/tickets/:number", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const seq = seqOf(decodeURIComponent(String(params["number"])));
    const ticket = readTickets().tickets.find((t) => t.seq === seq);
    return ticket ? HttpResponse.json(full(ticket)) : failure(404, "NOT_FOUND", "Не найдено.");
  }),

  http.post("*/admin/tickets/:number/reply", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as TicketReply;
    const text = body.body.trim();
    if (!text) return invalid("body", "ticket_reply_empty", "Напишите ответ.");
    if (text.length > 4000) {
      return invalid(
        "body",
        "ticket_reply_too_long",
        "Ответ длиннее 4000 символов: сократите его.",
      );
    }
    const state = readTickets();
    const seq = seqOf(decodeURIComponent(String(params["number"])));
    const ticket = state.tickets.find((t) => t.seq === seq);
    if (!ticket) return failure(404, "NOT_FOUND", "Не найдено.");
    const target: TicketStatus =
      body.status ?? (ticket.status === "new" ? "in_progress" : ticket.status);
    if (target !== ticket.status && !MOVES[ticket.status].includes(target)) {
      return failure(409, "CONFLICT", "Так сменить статус нельзя: обновите страницу.", "crm", {
        reason: "ticket_status_transition",
      });
    }
    const now = new Date().toISOString();
    ticket.messages.push({
      author_name: me()?.name ?? "Администратор",
      body: text,
      created_at: now,
    });
    if (target !== ticket.status) {
      ticket.status = target;
      ticket.resolvedAt = target === "resolved" ? now : undefined;
    }
    ticket.updatedAt = now;
    addNote(state, {
      userId: ticket.authorId,
      kind: "ticket_reply",
      tab: "system",
      title: `Ответ на обращение ${numberOf(ticket.seq)}`,
      subtitle: snippet(text),
      ticketNumber: numberOf(ticket.seq),
    });
    writeTickets(state);
    return HttpResponse.json(full(ticket));
  }),

  http.post("*/admin/tickets/:number/status", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as TicketStatusChange;
    const state = readTickets();
    const seq = seqOf(decodeURIComponent(String(params["number"])));
    const ticket = state.tickets.find((t) => t.seq === seq);
    if (!ticket) return failure(404, "NOT_FOUND", "Не найдено.");
    if (!MOVES[ticket.status].includes(body.status)) {
      return failure(409, "CONFLICT", "Так сменить статус нельзя: обновите страницу.", "crm", {
        reason: "ticket_status_transition",
      });
    }
    const now = new Date().toISOString();
    ticket.status = body.status;
    ticket.updatedAt = now;
    ticket.resolvedAt = body.status === "resolved" ? now : undefined;
    if (body.status === "resolved") {
      addNote(state, {
        userId: ticket.authorId,
        kind: "ticket_resolved",
        tab: "system",
        title: `Обращение ${numberOf(ticket.seq)} решено`,
        subtitle: snippet(ticket.body),
        ticketNumber: numberOf(ticket.seq),
      });
    }
    writeTickets(state);
    return HttpResponse.json(full(ticket));
  }),

  http.post("*/tickets", async ({ request }) => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const input = (await request.json()) as TicketCreate;
    if (!SUBJECTS.includes(input.subject)) {
      return invalid("subject", "ticket_subject_unknown", "Выберите тему из списка.");
    }
    const text = input.body.trim();
    if (!text) return invalid("body", "ticket_text_empty", "Опишите, что случилось.");
    if (text.length > 4000) {
      return invalid("body", "ticket_text_too_long", "Текст длиннее 4000 символов: сократите его.");
    }
    if (input.page && (!input.page.startsWith("/") || input.page.startsWith("//"))) {
      return invalid("page", "ticket_page_invalid", "Адрес страницы указан неверно.");
    }
    const state = readTickets();
    if (rateExceeded(state, user.id)) {
      return HttpResponse.json(
        {
          code: "TOO_MANY_REQUESTS",
          message: "Вы отправили слишком много обращений. Подождите немного и повторите.",
          source: "crm",
          details: { reason: "ticket_rate_limited" },
        },
        { status: 429, headers: { "Retry-After": "600" } },
      );
    }
    const now = new Date().toISOString();
    const roleName =
      user.roles.find((r) => r.id === user.active_role)?.name ??
      user.roles.map((r) => r.name).join(", ");
    const ticket: StoredTicket = {
      seq: state.nextTicket++,
      subject: input.subject,
      status: "new",
      authorId: user.id,
      authorName: user.name,
      authorRole: roleName,
      ...(input.page ? { page: input.page } : {}),
      body: text,
      messages: [],
      createdAt: now,
      updatedAt: now,
    };
    state.tickets.push(ticket);
    for (const adminId of adminIds()) {
      if (adminId === user.id) continue;
      addNote(state, {
        userId: adminId,
        kind: "ticket_new",
        tab: "system",
        title: `Новое обращение ${numberOf(ticket.seq)}`,
        subtitle: `${user.name}: ${snippet(text)}`,
        ticketNumber: numberOf(ticket.seq),
      });
    }
    writeTickets(state);
    return HttpResponse.json(full(ticket), { status: 201 });
  }),

  http.get("*/tickets", () => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const mine = readTickets()
      .tickets.filter((t) => t.authorId === user.id)
      .sort((a, b) => b.seq - a.seq);
    return HttpResponse.json({ items: mine.map(row) });
  }),

  http.get("*/tickets/:number", ({ params }) => {
    const user = me();
    if (!user) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const seq = seqOf(decodeURIComponent(String(params["number"])));
    const ticket = readTickets().tickets.find((t) => t.seq === seq && t.authorId === user.id);
    return ticket ? HttpResponse.json(full(ticket)) : failure(404, "NOT_FOUND", "Не найдено.");
  }),

  http.put("*/me/onboarding", () => {
    const session = readSession();
    if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    updateSession({ onboardingDone: true });
    const next = readSession();
    const current = next ? buildMe(next) : undefined;
    return current ? HttpResponse.json(current) : failure(401, "SESSION_EXPIRED", "Сессия истекла");
  }),
];
