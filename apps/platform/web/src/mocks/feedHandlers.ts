import { HttpResponse, http } from "msw";

import type { Notification, QueueItem, Sources } from "../shared/api/generated/model";
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

/**
 * Строка очереди без родного экрана (проект на стадии «Оплата») для e2e и снимков «Где сделать»:
 * `localStorage["rt-pf-mock-queue-stub"] = "1"` добавляет её к очереди директора (D1-6: у лидов, писем, КП и служебок
 * экраны уже есть, а проверять мост H1 надо на строке, у которой экрана нет).
 */
export const MOCK_QUEUE_STUB_KEY = "rt-pf-mock-queue-stub";

function queueStub(): boolean {
  try {
    return window.localStorage.getItem(MOCK_QUEUE_STUB_KEY) === "1";
  } catch {
    return false;
  }
}

const STUB_ROW: QueueItem = {
  id: "project:99:problem",
  role_id: "",
  kind: "problem_project",
  title: "Разобраться с проектом ПР-2026-099",
  subtitle: "АО «Демо-Рейл» · 9 дней на стадии «Оплата»",
  due_label: "later",
  object: {
    kind: "project",
    number: "ПР-2026-099",
    title: "Рельсовые скрепления",
    path: "/eds/projects/%D0%9F%D0%A0-2026-099?panel=open&tab=documents",
    step: "PAYMENT",
  },
};

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
    const own = queueForView(roles.view).filter((i) =>
      i.kind.endsWith("_lead") ? !crmDown() : !erpDown(),
    );
    const director = own.find((i) => i.kind === "resolve_letter");
    if (queueStub() && director) own.push({ ...STUB_ROW, role_id: director.role_id });
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
    return HttpResponse.json({
      // ERP не отвечает: бейджи разделов ERP (EDS, ERP, «Все проекты») не показываются, остаются очередь и CRM
      items: menuCountersFor(
        queueForView(roles.view).filter((i) => !erpDown() || i.kind.endsWith("_lead")).length,
      ).filter((c) => !erpDown() || c.module === "crm" || c.section === "queue"),
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
    const all = erpDown() ? [] : notificationsFor(roles.view);
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
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/notifications/:id/read", ({ params }) => {
    readIds.add(String(params["id"]));
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
