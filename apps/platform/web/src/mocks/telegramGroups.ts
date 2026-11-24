import { HttpResponse, http } from "msw";

import type {
  ClientTelegramGroup,
  TelegramGroup,
  TelegramGroupBindIn,
  ThreadMessage,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Групп с клиентами» (ТГ-1б, ADR-0032): список групп, привязка по коду, отключение, группа клиента для карточки и лента
 * группы (`L-9001`). Права — как у BFF: всё — раздел `crm.clients`: чтение от чтения, привязка и отключение — полный.
 * Коды: `K7M2QX` — рабочий для ждущей группы, `OLD111` — просрочен (409), любой другой — не найден (404).
 */
export const GROUP_LEAD = "L-9001";
export const GOOD_CODE = "K7M2QX";
export const EXPIRED_CODE = "OLD111";
const WAITING_CHAT = -1002000000002;
const BOUND_CLIENT = 3;

const SINCE = "2026-11-20T08:30:00Z";

function seed(): TelegramGroup[] {
  return [
    {
      chat_id: -1002000000001,
      title: "Рельс-Сервис · заявки",
      state: "connected",
      client_id: BOUND_CLIENT,
      client_name: "ООО Рельс-Сервис Демо",
      lead: GROUP_LEAD,
      bound_at: SINCE,
      detected_at: "2026-11-19T10:00:00Z",
    },
    {
      chat_id: WAITING_CHAT,
      title: "Вагоноремонт · поставки",
      state: "waiting_code",
      client_id: null,
      client_name: null,
      lead: null,
      bound_at: null,
      detected_at: "2026-11-24T12:15:00Z",
    },
    {
      chat_id: -1002000000003,
      title: "Север-Транс · общий чат",
      state: "needs_admin",
      client_id: 4,
      client_name: "АО Север-Транс",
      lead: "L-9002",
      bound_at: "2026-11-22T09:10:00Z",
      detected_at: "2026-11-21T09:00:00Z",
    },
    {
      chat_id: -1002000000004,
      title: "Тест-группа",
      state: "code_expired",
      client_id: null,
      client_name: null,
      lead: null,
      bound_at: null,
      detected_at: "2026-11-15T09:00:00Z",
    },
  ];
}

let groups = seed();

/** Только для тестов: вернуть начальное состояние. */
export function resetTelegramGroups(): void {
  groups = seed();
}

function allowed(need: "read" | "full", resources: readonly string[]) {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const me = buildMe({ ...session, activeRole: null });
  const ok = resources.some((r) => {
    const level = me?.resources[r];
    return level === "full" || (need === "read" && level === "read");
  });
  return ok
    ? null
    : failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", { need });
}

const group = (id: number) => groups.find((g) => g.chat_id === id);

const FEED: ThreadMessage[] = [
  {
    id: 9101,
    author: "lead",
    author_name: "Алишер Каримов",
    text: "Добрый день! Когда отгрузка по заявке ЗВ-2026-0042?",
    created_at: "2026-11-24T07:05:00Z",
    attachments: [],
    channel: "group",
  },
  {
    id: 9102,
    author: "manager",
    author_name: "Дилшод Менеджеров",
    text: "Здравствуйте, отгрузка в четверг. Накладная во вложении.",
    created_at: "2026-11-24T07:12:00Z",
    attachments: [
      {
        index: 0,
        name: "Накладная-0042.pdf",
        mime: "application/pdf",
        size: 48210,
        url: `/api/v1/crm/messages/${GROUP_LEAD}/attachments/9102/0`,
      },
    ],
    channel: "group",
  },
  {
    id: 9103,
    author: "lead",
    author_name: "Алишер Каримов",
    text: "Спасибо. Вот чертёж, он большой.",
    created_at: "2026-11-24T07:20:00Z",
    attachments: [
      {
        index: 0,
        name: "Чертёж-узла.zip",
        mime: "application/zip",
        size: null,
        url: null,
        note: "файл больше 20 МБ — откройте в группе",
      },
    ],
    channel: "group",
  },
];

export const telegramGroupsHandlers = [
  http.get("*/api/v1/crm/telegram-groups", () => {
    const denied = allowed("read", ["crm.clients"]);
    return denied ?? HttpResponse.json({ items: groups });
  }),

  http.post("*/api/v1/crm/telegram-groups/bind", async ({ request }) => {
    const denied = allowed("full", ["crm.clients"]);
    if (denied) return denied;
    const body = (await request.json()) as TelegramGroupBindIn;
    if (body.code === EXPIRED_CODE) {
      return failure(409, "CONFLICT", "Код истёк.", "crm", { reason: "code_expired" });
    }
    const target = group(WAITING_CHAT);
    if (body.code !== GOOD_CODE || !target) {
      return failure(404, "NOT_FOUND", "Код не найден.", "crm", { reason: "code_not_found" });
    }
    const bound: TelegramGroup = {
      ...target,
      state: "connected",
      client_id: body.client_id,
      client_name: `Клиент ${String(body.client_id)}`,
      lead: "L-9003",
      bound_at: new Date().toISOString(),
    };
    groups = groups.map((g) => (g.chat_id === WAITING_CHAT ? bound : g));
    return HttpResponse.json(bound);
  }),

  http.post("*/api/v1/crm/telegram-groups/:chatId/unbind", ({ params }) => {
    const denied = allowed("full", ["crm.clients"]);
    if (denied) return denied;
    const id = Number(params["chatId"]);
    if (!group(id)) return failure(404, "NOT_FOUND", "Группа не найдена.", "crm");
    groups = groups.map((g) => (g.chat_id === id ? { ...g, state: "disconnected" } : g));
    return HttpResponse.json({ id: null, ok: true });
  }),

  http.get("*/api/v1/crm/clients/:id/telegram-group", ({ params }) => {
    const denied = allowed("read", ["crm.clients"]);
    if (denied) return denied;
    const found = groups.find(
      (g) =>
        g.client_id === Number(params["id"]) &&
        (g.state === "connected" || g.state === "needs_admin"),
    );
    const body: ClientTelegramGroup = { group: found ?? null };
    return HttpResponse.json(body);
  }),

  // Лента группы — до общего мока переписки; чужие номера уходят дальше
  http.get(`*/api/v1/crm/messages/${GROUP_LEAD}/thread`, () => {
    const denied = allowed("read", ["crm.leads", "chats.external"]);
    return denied ?? HttpResponse.json({ items: FEED, notes: [], has_more: false });
  }),
];
