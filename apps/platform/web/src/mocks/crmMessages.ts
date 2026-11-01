import { HttpResponse, http } from "msw";

import { QUEUE, allows } from "../app/rbac.generated";
import type {
  AssistIn,
  HandOverIn,
  Notification,
  QueueItem,
  ReplyIn,
  TeamNoteIn,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { emitMockHint } from "./eventStream";
import { readKb } from "./fixtures/kb";
import {
  type LeadMock,
  MOCK_INBOX_EMPTY_KEY,
  MOCK_TELEGRAM_DOWN_KEY,
  MOCK_TELEGRAM_UNKNOWN_KEY,
  mockFlag,
  readMessages,
  writeMessages,
} from "./fixtures/messages";
import type { MockRole } from "./fixtures/roles";
import { allUsers } from "./fixtures/users";
import { buildMe, currentActor, readSession } from "./mockSession";

/**
 * Моки «Клиенты · Ждут ответа» (D1-1, BFF 0.22.0). Права — как в BFF: чтение — `crm.leads` от чтения, действия и шаблоны —
 * `crm.leads` полный (директор только смотрит). Отказы — коды CRM (`lead_taken`, `take_first`, `delivery_failed`), чтобы экран
 * и e2e видели настоящее поведение. Повтор ответа с тем же `client_message_id` не добавляет второе сообщение.
 */
type Level = "read" | "full" | "triage";

/** Чтение — `crm.leads` от чтения или первая линия (`crm.leads.triage`, D17G-1); действия — `crm.leads` полный. */
function guard(need: Level) {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const resources = buildMe({ ...session, activeRole: null })?.resources ?? {};
  const level = resources["crm.leads"];
  const triage = resources["crm.leads.triage"] === "full";
  if (need === "triage" && triage) return null;
  if (need === "full" && level === "full") return null;
  if (need === "read" && (level === "full" || level === "read" || triage)) return null;
  return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
    resource: need === "triage" ? "crm.leads.triage" : "crm.leads",
    need: need === "read" ? "read" : "full",
  });
}

/** Кому передать лида: держатели «работы с клиентом» (`crm.leads: full`) — менеджер, менеджер-универсал. */
function leadManagers() {
  return allUsers()
    .filter((u) => u.roles.some((r) => r === "MANAGER" || r === "MANAGER_ALL"))
    .filter((u) => !u.email.startsWith("disabled@"))
    .map((u) => ({ id: u.id, name: u.name, initials: u.initials }));
}

function find(lead: string): { state: ReturnType<typeof readMessages>; row: LeadMock } | null {
  const state = readMessages();
  const row = state.leads.find((l) => l.item.lead === lead.toUpperCase());
  return row ? { state, row } : null;
}

const notFound = () => failure(404, "NOT_FOUND", "Лид не найден.", "crm");

function me() {
  const actor = currentActor();
  const name = actor?.name ?? "Сотрудник";
  return { id: actor?.id ?? "0", name, initials: name.slice(0, 1) };
}

/** Только моки: клиент пишет в бота — сообщение в переписку и подсказка потока, как от BFF. */
export function mockClientWrites(lead: string, text: string): void {
  const found = find(lead);
  if (!found) return;
  const { state, row } = found;
  const now = new Date().toISOString();
  state.nextId += 1;
  row.messages.push({
    id: state.nextId,
    author: "lead",
    author_name: null,
    text,
    created_at: now,
    attachments: [],
    delivery: null,
  });
  row.item.unread = true;
  row.item.last_message_at = now;
  row.item.note.last_message = text;
  writeMessages(state);
  emitMockHint({
    topics: ["counters", "queue", "messages"],
    reason: "uz.railtech.crm.lead.message_added.v1",
  });
}

if (typeof window !== "undefined") {
  (window as unknown as { __rtMockClientWrites?: typeof mockClientWrites }).__rtMockClientWrites =
    mockClientWrites;
}

export const crmMessagesHandlers = [
  http.get("*/api/v1/crm/messages", () => {
    const denied = guard("read");
    if (denied) return denied;
    const items = mockFlag(MOCK_INBOX_EMPTY_KEY) ? [] : readMessages().leads.map((l) => l.item);
    return HttpResponse.json({ items });
  }),

  http.get("*/api/v1/crm/messages/:lead", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    return found ? HttpResponse.json(found.row.card) : notFound();
  }),

  http.get("*/api/v1/crm/messages/:lead/thread", ({ params, request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const url = new URL(request.url);
    const before = Number(url.searchParams.get("before") ?? "0");
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const older = before > 0 ? found.row.messages.filter((m) => m.id < before) : found.row.messages;
    const items = older.slice(-limit);
    return HttpResponse.json({
      items,
      notes: before > 0 ? [] : [...found.row.notes].reverse(),
      has_more: older.length > items.length,
    });
  }),

  http.get("*/api/v1/crm/messages/:lead/attachments/:message/:index", () => {
    const denied = guard("read");
    if (denied) return denied;
    return new HttpResponse("%PDF-1.4 демо-файл\n", {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition":
          "attachment; filename*=UTF-8''%D0%97%D0%B0%D1%8F%D0%B2%D0%BA%D0%B0-demo.pdf",
      },
    });
  }),

  http.post("*/api/v1/crm/messages/:lead/take", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const { state, row } = found;
    const taker = me();
    if (row.item.assigned && row.item.assigned.id !== taker.id) {
      return failure(409, "CONFLICT", "Лида уже забрал другой сотрудник.", "crm", {
        reason: "lead_taken",
        assigned_user_name: row.item.assigned.name,
      });
    }
    row.item.assigned = taker;
    row.card.assigned = taker;
    row.card.owner_mode = "manager";
    if (row.item.handoff)
      row.item.handoff = { ...row.item.handoff, state: "taken", taken_by: taker };
    row.card.handoff = row.item.handoff;
    writeMessages(state);
    return HttpResponse.json({ id: null, ok: true });
  }),

  http.post("*/api/v1/crm/messages/:lead/reply", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as ReplyIn;
    const { state, row } = found;
    const done = state.sent[body.client_message_id];
    if (done !== undefined) {
      // Повтор тем же ключом: второго сообщения нет (как CRM); итог неизвестен — «не подтверждено»
      const sent = row.messages.find((m) => m.id === done);
      if (sent?.delivery === "sending" || sent?.delivery === "unconfirmed") {
        sent.delivery = "unconfirmed";
        writeMessages(state);
        return failure(409, "CONFLICT", "Доставка не подтверждена.", "crm", {
          reason: "delivery_unconfirmed",
        });
      }
      return HttpResponse.json({ id: done });
    }
    if (row.card.owner_mode !== "manager") {
      return failure(409, "CONFLICT", "Сначала заберите лида.", "crm", { reason: "take_first" });
    }
    if (mockFlag(MOCK_TELEGRAM_UNKNOWN_KEY)) {
      state.nextId += 1;
      row.messages.push({
        id: state.nextId,
        author: "manager",
        author_name: me().name,
        text: body.text,
        created_at: new Date().toISOString(),
        attachments: [],
        delivery: "sending",
      });
      state.sent[body.client_message_id] = state.nextId;
      writeMessages(state);
      return failure(502, "INTEGRATION_FAILED", "Внешний сервис не ответил.", "crm", {
        reason: "delivery_unknown",
        backend_status: 502,
      });
    }
    if (mockFlag(MOCK_TELEGRAM_DOWN_KEY)) {
      return failure(502, "INTEGRATION_FAILED", "Внешний сервис не ответил.", "crm", {
        reason: "delivery_failed",
        backend_status: 502,
      });
    }
    state.nextId += 1;
    row.messages.push({
      id: state.nextId,
      author: "manager",
      author_name: me().name,
      text: body.text,
      created_at: new Date().toISOString(),
      attachments: [],
      delivery: null,
    });
    row.item.unread = false;
    state.sent[body.client_message_id] = state.nextId;
    writeMessages(state);
    return HttpResponse.json({ id: state.nextId });
  }),

  http.post("*/api/v1/crm/messages/:lead/note", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as TeamNoteIn;
    const { state, row } = found;
    state.nextId += 1;
    row.notes.push({
      id: state.nextId,
      author_name: me().name,
      text: body.text,
      created_at: new Date().toISOString(),
      visible_to_bot: false,
    });
    writeMessages(state);
    return HttpResponse.json({ id: state.nextId }, { status: 201 });
  }),

  http.post("*/api/v1/crm/messages/:lead/assist", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as AssistIn;
    const text =
      body.mode === "improve" && body.text
        ? `${body.text.trim()} Если удобно, созвонимся сегодня.`
        : `${found.row.card.name.split(" ")[0] ?? ""}, добрый день! Подготовлю коммерческое предложение и пришлю сегодня.`;
    return HttpResponse.json({ text, notice: null });
  }),

  http.post("*/api/v1/crm/messages/:lead/return-to-bot", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const { state, row } = found;
    row.card.owner_mode = "bot";
    row.card.handoff = null;
    row.item.handoff = null;
    writeMessages(state);
    return HttpResponse.json({ id: null, ok: true });
  }),

  http.get("*/api/v1/crm/lead-managers", () => {
    const denied = guard("triage");
    if (denied) return denied;
    return HttpResponse.json({ items: leadManagers() });
  }),

  http.post("*/api/v1/crm/messages/:lead/hand-over", async ({ params, request }) => {
    const denied = guard("triage");
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as HandOverIn;
    const { state, row } = found;
    if (row.card.owner_mode === "manager" && row.card.assigned) {
      return failure(409, "CONFLICT", "Лида уже забрал другой сотрудник.", "crm", {
        reason: "lead_taken",
        assigned_user_name: row.card.assigned.name,
      });
    }
    const target = leadManagers().find((m) => m.id === body.user_id);
    if (!target) {
      return failure(422, "VALIDATION_FAILED", "Выберите активного менеджера.", "crm", {
        reason: "inactive_colleague",
        fields: ["user_id"],
      });
    }
    const by = me();
    const now = new Date().toISOString();
    const reasons = row.item.handoff?.reasons ?? [];
    row.item.handoff = {
      priority: row.item.handoff?.priority === "hot" ? "hot" : "warm",
      state: "open",
      reasons: reasons.includes("handed_over") ? reasons : [...reasons, "handed_over"],
      reason_text: body.note,
      recommendation: row.item.handoff?.recommendation ?? null,
      created_at: row.item.handoff?.created_at ?? now,
      sla_due_at: new Date(Date.now() + 15 * 60_000).toISOString(),
      snoozed_until: null,
      taken_by: null,
      handed_by: by,
      request_type: body.request_type ?? null,
    };
    row.item.group = "handoff";
    row.item.assigned = target;
    row.card.assigned = target;
    row.card.owner_mode = "waiting";
    row.card.handoff = row.item.handoff;
    state.nextId += 1;
    row.notes.push({
      id: state.nextId,
      author_name: by.name,
      text: body.note,
      created_at: now,
      visible_to_bot: false,
    });
    state.handovers = [
      ...(state.handovers ?? []),
      {
        seq: state.nextId,
        lead: row.item.lead,
        name: row.item.name,
        to: target.id,
        by: by.name,
        note: body.note,
        at: now,
        read: false,
      },
    ];
    writeMessages(state);
    emitMockHint({ topics: ["counters", "queue", "messages"], reason: "mock.lead.handed_over" });
    return HttpResponse.json({ id: null, ok: true });
  }),

  http.get("*/api/v1/crm/reply-templates", () => {
    const denied = guard("full");
    if (denied) return denied;
    return HttpResponse.json({ items: readKb().templates });
  }),
];

const TRIAGE = QUEUE.triage_lead;
const TAKE = QUEUE.take_lead;

/**
 * Строки «Моих задач» из моков «Ждут ответа» (D17G-1): первой линии — «Разобрать лида» по свободным лидам, менеджеру —
 * «Новый лид от делопроизводителя» с запиской по переданным ему. Как в BFF (`feeds/queue.py`).
 */
export function handOverQueueItems(
  view: readonly MockRole[],
  userId: string | undefined,
): QueueItem[] {
  const leads = readMessages().leads;
  const out: QueueItem[] = [];
  const taker = view.find((r) => allows(r.access, TAKE.resource, TAKE.level));
  const triager = view.find((r) => allows(r.access, TRIAGE.resource, TRIAGE.level));
  for (const { item } of leads) {
    const handed = Boolean(item.handoff?.reasons.includes("handed_over") && item.assigned);
    const object = {
      kind: "lead" as const,
      number: item.lead,
      title: item.name,
      path: `/crm/messages?lead=${item.lead}`,
    };
    if (handed && taker && item.assigned?.id === userId && item.handoff?.state !== "taken") {
      out.push({
        id: `lead:${item.lead}:handed`,
        role_id: taker.id,
        kind: "take_lead",
        title: `Новый лид от делопроизводителя ${item.lead}`,
        subtitle: [
          item.name,
          item.handoff?.reason_text,
          `передал(а) ${item.handoff?.handed_by?.name ?? ""}`,
        ]
          .filter(Boolean)
          .join(" · "),
        due_label: "today",
        ...(item.handoff?.sla_due_at ? { due_at: item.handoff.sla_due_at } : {}),
        object,
      });
    } else if (!taker && triager && !item.assigned && item.group !== "mine") {
      out.push({
        id: `lead:${item.lead}:triage`,
        role_id: triager.id,
        kind: "triage_lead",
        title: `Разобрать лида ${item.lead}`,
        subtitle: [item.name, item.note.request].filter(Boolean).join(" · "),
        due_label: "today",
        object,
      });
    }
  }
  return out;
}

/** Колокольчик менеджера: «Новый лид от делопроизводителя» (CRM `lead_handed_over`, D17G-1). */
export function handOverNotificationsOf(userId: string): Notification[] {
  return (readMessages().handovers ?? [])
    .filter((h) => h.to === userId)
    .map((h) => ({
      id: `crm:h${String(h.seq)}`,
      tab: "decisions" as const,
      title: `Новый лид от делопроизводителя ${h.lead}`,
      subtitle: h.note,
      object: { kind: "lead" as const, number: h.lead, path: `/crm/messages?lead=${h.lead}` },
      created_at: h.at,
      read: h.read,
    }));
}
