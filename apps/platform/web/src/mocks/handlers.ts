import { HttpResponse, http, passthrough } from "msw";

import {
  getGetHealthMockHandler,
  getListNotificationsMockHandler,
  getGetMenuCountersMockHandler,
  getRailTechPlatformBFFAPICRMERPMock,
} from "../shared/api/generated/platform-bff.msw";
import type { ChangePasswordIn, LoginIn, MeUpdate } from "../shared/api/generated/model";
import { adminUsersHandlers } from "./adminUsers";
import { isEmployeeDisabled } from "./fixtures/employees";
import { DEMO_WRONG_CURRENT_PASSWORD, DEMO_WRONG_PASSWORD, findUser } from "./fixtures/users";
import {
  buildMe,
  buildSession,
  endSession,
  readSession,
  startSession,
  updateSession,
} from "./mockSession";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "crm" | "erp" = "bff",
) {
  return HttpResponse.json({ code, message, source }, { status });
}

const sessionExpired = () => failure(401, "SESSION_EXPIRED", "Сессия истекла");

/**
 * Моки API Платформы для `pnpm dev:mock`, e2e и тестов. Общий набор генерирует orval из контракта (случайные
 * данные faker); здесь поверх — состояние сессии и профиля на 6 ролей из фикстур (по `platform-rbac.yaml`) и
 * детерминированные счётчики, чтобы скриншоты и e2e не плавали. Вход принимает любой непустой пароль, кроме
 * `wrong-password`; адреса `disabled@`, `norole@`, `busy@`, `down@` дают ошибки входа.
 */
export const handlers = [
  // Сгенерированные orval обработчики слушают `*/queue`, `*/me`, `*/health`…: без этой «калитки» они перехватили бы и
  // переходы по страницам SPA (`/dashboard/queue`). API живёт только под `/api/v1/`, всё остальное — как есть.
  http.all("*", ({ request }) =>
    new URL(request.url).pathname.startsWith("/api/v1/") ? undefined : passthrough(),
  ),

  http.post("*/auth/login", async ({ request }) => {
    const body = (await request.json()) as LoginIn;
    const user = findUser(body.email);
    if (!user || body.password === DEMO_WRONG_PASSWORD) {
      return failure(401, "INVALID_CREDENTIALS", "Неверная почта или пароль", "crm");
    }
    if (user.loginError) {
      return failure(
        user.loginError.status,
        user.loginError.code,
        user.loginError.code,
        user.loginError.source,
      );
    }
    // Отключённого в Оргструктуре CRM не отличает от неверного пароля (Q-PLT-10-1).
    if (isEmployeeDisabled(user.id)) {
      return failure(401, "INVALID_CREDENTIALS", "Неверная почта или пароль", "crm");
    }
    const session = buildSession(startSession(user));
    return session ? HttpResponse.json(session) : failure(500, "INTERNAL_ERROR", "Нет сессии");
  }),

  http.post("*/auth/logout", () => {
    endSession();
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/auth/change-password", async ({ request }) => {
    const session = readSession();
    if (!session) return sessionExpired();
    const body = (await request.json()) as ChangePasswordIn;
    if (body.current_password === DEMO_WRONG_CURRENT_PASSWORD) {
      return failure(422, "WRONG_PASSWORD", "Текущий пароль неверен", "crm");
    }
    updateSession({ mustChangePassword: false });
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/auth/session", () => {
    const session = readSession();
    const body = session ? buildSession(session) : undefined;
    return body ? HttpResponse.json(body) : sessionExpired();
  }),

  http.get("*/me", () => {
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    return me ? HttpResponse.json(me) : sessionExpired();
  }),

  http.patch("*/me", async ({ request }) => {
    const current = readSession();
    if (!current) return sessionExpired();
    const body = (await request.json()) as MeUpdate;
    const user = buildMe(current);
    if (body.active_role && !user?.roles.includes(body.active_role)) {
      return failure(422, "VALIDATION_FAILED", "Роль не выдана сотруднику");
    }
    const next = updateSession({
      ...(body.language ? { language: body.language } : {}),
      ...("active_role" in body ? { activeRole: body.active_role ?? null } : {}),
    });
    const me = next ? buildMe(next) : undefined;
    return me ? HttpResponse.json(me) : sessionExpired();
  }),

  ...adminUsersHandlers,

  getGetHealthMockHandler({
    status: "ok",
    checks: { redis: "ok", crm: "ok", erp: "ok" },
    version: "0.2.0",
  }),

  getGetMenuCountersMockHandler({
    items: [
      { module: "dashboard", section: "queue", count: 3, attention: true },
      { module: "dashboard", section: "projects", count: 4, attention: false },
      { module: "crm", section: "messages", count: 1, attention: true },
      { module: "crm", section: "leads", count: 2, attention: true },
      { module: "eds", section: "inbox", count: 1, attention: true },
      { module: "eds", section: "drafts", count: 1, attention: true },
      { module: "eds", section: "approvals", count: 1, attention: true },
      { module: "eds", section: "payments", count: 2, attention: false },
      { module: "erp", section: "calc", count: 2, attention: true },
    ],
    sources: { crm: "ok", erp: "ok" },
  }),

  getListNotificationsMockHandler({
    items: [],
    next_cursor: null,
    unread_count: 3,
    sources: { crm: "ok", erp: "ok" },
  }),

  ...getRailTechPlatformBFFAPICRMERPMock(),
];
