import { HttpResponse, http } from "msw";

import type { AssistIn, ReplyIn, TeamNoteIn } from "../shared/api/generated/model";
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
import { buildMe, currentActor, readSession } from "./mockSession";

/**
 * Моки «Клиенты · Ждут ответа» (D1-1, BFF 0.20.0). Права — как в BFF: чтение — `crm.leads` от чтения, действия и шаблоны —
 * `crm.leads` полный (директор только смотрит). Отказы — коды CRM (`lead_taken`, `take_first`, `delivery_failed`), чтобы экран
 * и e2e видели настоящее поведение. Повтор ответа с тем же `client_message_id` не добавляет второе сообщение.
 */
type Level = "read" | "full";

function guard(need: Level) {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const level = buildMe({ ...session, activeRole: null })?.resources["crm.leads"];
  if (level === "full" || (need === "read" && level === "read")) return null;
  return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
    resource: "crm.leads",
    need,
  });
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

  http.get("*/api/v1/crm/reply-templates", () => {
    const denied = guard("full");
    if (denied) return denied;
    return HttpResponse.json({ items: readKb().templates });
  }),
];
