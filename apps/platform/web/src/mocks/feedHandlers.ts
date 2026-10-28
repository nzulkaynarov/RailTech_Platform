import { HttpResponse, http } from "msw";

import type { Notification, Sources } from "../shared/api/generated/model";
import {
  activityToday,
  cardsForView,
  menuCountersFor,
  notificationSeed,
  queueForView,
  searchIndex,
} from "./fixtures/feeds";
import { computeAccess, type MockRole } from "./fixtures/roles";
import { readSession, sessionRoles } from "./mockSession";
import { crmNotificationsOf, markCrmNoteRead, ticketQueueItems } from "./ticketsHandlers";
import { stockQueueItems } from "./erpStock";
import { coveredQueueItems } from "./profileStore";

/**
 * Имитация сбоя ERP для скриншотов и e2e: `localStorage["rt-pf-mock-erp-down"] = "1"` (страница с MSW читает его при
 * каждом запросе). Агрегаты отдают только данные CRM и `sources.erp = "unavailable"`, как будет делать BFF.
 */
export const MOCK_ERP_DOWN_KEY = "rt-pf-mock-erp-down";

function erpDown(): boolean {
  try {
    return window.localStorage.getItem(MOCK_ERP_DOWN_KEY) === "1";
  } catch {
    return false;
  }
}

/** То же для CRM: `localStorage["rt-pf-mock-crm-down"] = "1"` — очередь без лидов, `sources.crm = "unavailable"` (W15-H2). */
export const MOCK_CRM_DOWN_KEY = "rt-pf-mock-crm-down";

function crmDown(): boolean {
  try {
    return window.localStorage.getItem(MOCK_CRM_DOWN_KEY) === "1";
  } catch {
    return false;
  }
}

const sources = (): Sources => ({
  crm: crmDown() ? "unavailable" : "ok",
  erp: erpDown() ? "unavailable" : "ok",
});

function expired() {
  return HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );
}

/** Роли «вида»: явный `role` (id), иначе активная роль сессии, иначе все роли сотрудника (контракт BFF 0.3.0). */
function viewRoles(explicit: string | null): { all: MockRole[]; view: MockRole[] } | undefined {
  const session = readSession();
  const roles = session ? sessionRoles(session) : undefined;
  if (!session || !roles) return undefined;
  const chosen = roles.all.find((r) => r.id === (explicit ?? session.activeRole));
  return { all: roles.all, view: chosen ? [chosen] : roles.all };
}

/** Раздел «Моя очередь» — как `require("dashboard.queue")` BFF: без него очередь, счётчики и уведомления — 403. */
function noQueue(roles: { all: MockRole[] }) {
  if (computeAccess(roles.all).resources["dashboard.queue"]) return null;
  return HttpResponse.json(
    {
      code: "FORBIDDEN",
      message: "Раздел или действие не положены вашей роли.",
      source: "bff",
      details: { resource: "dashboard.queue", need: "read" },
    },
    { status: 403 },
  );
}

/** Прочитанные уведомления живут в памяти страницы: «Отметить все прочитанными» переживает опрос, но не перезагрузку. */
const readIds = new Set<string>();
let readAllAt = 0;

function notificationsFor(roles: readonly MockRole[]): Notification[] {
  const now = Date.now();
  const seen = new Set<string>();
  return roles
    .flatMap((role) => notificationSeed(role.demo))
    .filter((n) => (seen.has(n.id) ? false : (seen.add(n.id), true)))
    .map(({ ago, ...n }) => ({
      ...n,
      created_at: new Date(now - ago).toISOString(),
      read: n.read || readIds.has(n.id) || readAllAt > 0,
    }))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/**
 * Моки Dashboard, уведомлений и поиска (PLT-14): данные зависят от роли сессии, чтобы сценарии и скриншоты не плавали.
 * Ответы совпадают по форме с BFF (`platform-bff.yaml`); недоступный источник тесты имитируют через `server.use`.
 */
export const feedHandlers = [
  http.get("*/queue/cards", ({ request }) => {
    const roles = viewRoles(new URL(request.url).searchParams.get("role"));
    if (!roles) return expired();
    const denied = noQueue(roles);
    if (denied) return denied;
    const cards = cardsForView(roles.view).filter((c) => !erpDown() || c.path.startsWith("/crm"));
    return HttpResponse.json({ cards, sources: sources() });
  }),

  http.get("*/queue", ({ request }) => {
    const roles = viewRoles(new URL(request.url).searchParams.get("role"));
    if (!roles) return expired();
    const denied = noQueue(roles);
    if (denied) return denied;
    const rank = { overdue: 0, today: 1, tomorrow: 2, memo: 3, later: 4 } as const;
    const own = [
      ...queueForView(roles.view),
      ...ticketQueueItems(roles.view), // обращения живут в CRM, как и лиды
      ...stockQueueItems(roles.view), // просроченные заказы поставщикам (ERP, D2-2)
    ]
      .filter((i) => (i.kind.endsWith("_lead") || i.kind === "ticket" ? !crmDown() : !erpDown()))
      .sort((a, b) => rank[a.due_label] - rank[b.due_label]);
    // Замещение (W15-H6): заместитель видит строки замещаемого с пометкой «за {имя}».
    const session = readSession();
    const userId = session ? sessionRoles(session)?.user.id : undefined;
    const answerRole = own.find((i) => i.kind === "answer_lead")?.role_id;
    const covered = userId && answerRole ? coveredQueueItems(userId, answerRole) : [];
    return HttpResponse.json({ items: [...own, ...covered], sources: sources() });
  }),

  http.get("*/menu-counters", () => {
    const roles = viewRoles(null);
    if (!roles) return expired();
    const denied = noQueue(roles);
    if (denied) return denied;
    const tickets = ticketQueueItems(roles.view).length;
    const stockOverdue = stockQueueItems(roles.view).length;
    return HttpResponse.json({
      // ERP не отвечает: бейджи разделов ERP (EDS, ERP, «Все проекты») не показываются, остаются очередь и CRM
      items: [
        ...menuCountersFor(
          queueForView(roles.view).filter((i) => !erpDown() || i.kind.endsWith("_lead")).length,
        ).filter((c) => !erpDown() || c.module === "crm" || c.section === "queue"),
        // «Расчёт · Склад»: просроченные заказы поставщикам (D2-2)
        ...(stockOverdue > 0 && !erpDown()
          ? [{ module: "erp" as const, section: "stock", count: stockOverdue, attention: true }]
          : []),
        // «Настройки · Обращения сотрудников»: число новых обращений (W15-H7)
        ...(tickets > 0
          ? [{ module: "admin" as const, section: "tickets", count: tickets, attention: true }]
          : []),
      ],
      sources: sources(),
    });
  }),

  http.get("*/activity/today", () => {
    const roles = viewRoles(null);
    if (!roles) return expired();
    // Журнал ERP открыт администратору платформы: BFF отдаёт ему ту же ленту, без служебных записей входа (`sso.*`),
    // с человекочитаемыми строками (QA-P1-D-1).
    const items = erpDown() ? [] : activityToday();
    return HttpResponse.json({ items, sources: sources() });
  }),

  http.get("*/notifications", ({ request }) => {
    const roles = viewRoles(null);
    if (!roles) return expired();
    const denied = noQueue(roles);
    if (denied) return denied;
    const params = new URL(request.url).searchParams;
    const tab = params.get("tab") ?? "all";
    const mine = erpDown() ? [] : notificationsFor(roles.view);
    // Лента CRM (W15-H7): ответы на обращения, привязка Telegram; не зависит от недоступности ERP.
    const session = readSession();
    const userId = session ? sessionRoles(session)?.user.id : undefined;
    const crm = userId ? crmNotificationsOf(userId) : [];
    const all = [...mine, ...crm].sort((a, b) => b.created_at.localeCompare(a.created_at));
    const items = all.filter((n) => tab === "all" || n.tab === tab);
    return HttpResponse.json({
      items,
      next_cursor: null,
      unread_count: all.filter((n) => !n.read).length,
      sources: sources(),
    });
  }),

  http.post("*/notifications/read-all", () => {
    readAllAt = Date.now();
    const session = readSession();
    const user = session ? sessionRoles(session)?.user : undefined;
    if (user) markCrmNoteRead(user.id, "all");
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/notifications/:id/read", ({ params }) => {
    const id = String(params["id"]);
    if (id.startsWith("crm:")) {
      const session = readSession();
      const user = session ? sessionRoles(session)?.user : undefined;
      if (!user || !markCrmNoteRead(user.id, id)) {
        return HttpResponse.json(
          { code: "NOT_FOUND", message: "Не найдено.", source: "bff" },
          { status: 404 },
        );
      }
      return new HttpResponse(null, { status: 204 });
    }
    readIds.add(id);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/search", ({ request }) => {
    const roles = viewRoles(null);
    if (!roles) return expired();
    const q = new URL(request.url).searchParams.get("q") ?? "";
    if (q.trim().length < 2) {
      return HttpResponse.json(
        { code: "VALIDATION_FAILED", message: "Слишком короткий запрос", source: "bff" },
        { status: 422 },
      );
    }
    const resources = new Set(Object.keys(computeAccess(roles.view).resources));
    const groups = searchIndex(q, resources).filter((g) => !erpDown() || g.module === "crm");
    return HttpResponse.json({ groups, sources: sources() });
  }),
];

/** Сбросить состояние «прочитано» между тестами. */
export function resetFeedMocks(): void {
  readIds.clear();
  readAllAt = 0;
}
